#!/usr/bin/env bash
#
# Build the Lambda deployment package.
#
# WHY THIS EXISTS
#
#   deploy.sh refuses to run without ${BUILD}/aether-lambda.zip. Until this
#   script existed the package was assembled by hand, which meant the deployed
#   artifact could not be reproduced from a clean clone — an awkward position
#   for a project whose central claim is byte-identical reproducibility.
#
# WHAT GOES IN
#
#   /var/task/
#     lambda_handler.py        Mangum entry point
#     backend/aether/...       the application (handler puts backend/ on sys.path)
#     fixtures/...             simulated data, resolved via config.REPO_ROOT
#     <dependencies>           installed flat, which is where Lambda looks
#
#   aether.config derives REPO_ROOT from __file__'s grandparent, so
#   backend/aether/config.py must sit two levels under the task root for
#   fixtures/ to resolve. Flattening the tree breaks fixture loading silently —
#   the import succeeds and the first data read fails.
#
# DETERMINISM
#
#   Entries are written in sorted order with a fixed timestamp, so two builds of
#   the same inputs produce a byte-identical zip. The manifest records the
#   resolved version of every dependency and the SHA-256 of the archive, which
#   is what makes "the deployed code is the tested code" checkable rather than
#   asserted.
#
# USAGE
#
#   bash deploy/build_lambda.sh
#   bash deploy/deploy.sh backend

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${AETHER_BUILD_DIR:-/d/aether-build}"
STAGE="${BUILD}/pkg"
ZIP="${BUILD}/aether-lambda.zip"
MANIFEST="${BUILD}/package-manifest.txt"

# Must match RUNTIME in deploy.sh. A mismatch produces a package whose compiled
# extensions cannot be imported, and the failure appears only at cold start as
# Runtime.ImportModuleError.
PY_VERSION="3.13"
ABI="cp313"

# Resolve an interpreter that actually runs. On Windows, `python3` is usually the
# Microsoft Store shim: it is on PATH, `command -v` finds it, and executing it
# prints an advertisement and exits non-zero. Candidates are therefore tested,
# not merely located.
PYTHON=""
for candidate in python python3 py; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
[[ -n "$PYTHON" ]] || { echo "No working Python interpreter on PATH." >&2; exit 1; }

say()  { printf '\n\033[36m▸ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

# --------------------------------------------------------------- requirements
#
# The runtime set, not the development set. Each exclusion below was checked
# against the source rather than assumed, because dropping a package that turns
# out to be imported fails at cold start and not at build time.
#
#   uvicorn           an ASGI *server*. Mangum is the adapter on Lambda, and
#                     nothing imports uvicorn outside scripts/dev.ps1.
#   sqlmodel          declared in pyproject and imported nowhere. It drags in
#                     SQLAlchemy, which is the single largest avoidable weight.
#   python-multipart  needed only for form uploads; the API has no UploadFile
#                     endpoint. Documents arrive by identifier, not by upload.
#   anthropic         imported lazily inside legal_clause.extract_terms and
#                     agents.guide, and reached only in live mode. The deployed
#                     function runs AETHER_MODE=replay. See the note below.
#   truststore        imported lazily and guarded by AETHER_USE_TRUSTSTORE,
#                     which deploy.sh sets false. It exists for the TLS
#                     interception on the build machine, not for Lambda.
#   certifi           never imported by aether; only outbound TLS would need it,
#                     and replay makes no outbound call.
#   pytest/hypothesis/httpx/faker/pandas   development and fixture generation.
#
# CONSEQUENCE, STATED PLAINLY: this package cannot serve AETHER_MODE=live.
# Setting that environment variable on the deployed function raises
# ModuleNotFoundError on the first extraction. Replay is the demo path and the
# only mode this artifact supports. Add "anthropic" below to change that.
RUNTIME_REQUIREMENTS=(
  "fastapi>=0.141.1"
  "mangum>=0.19.0"
  "pydantic>=2.12.5"
  "pydantic-settings>=2.13.1"
  "numpy>=2.4.3"
  "scipy>=1.18.0"
  "pypdf>=6.16.1"
)

# ---------------------------------------------------------------------- build

say "Cleaning ${STAGE}"
rm -rf "$STAGE"
mkdir -p "$STAGE" "$BUILD"
ok "clean"

say "Installing dependencies for linux/${ABI}"
# --platform is repeated because the wheel set spans two manylinux profiles;
# pip accepts any of the listed tags. --only-binary is mandatory with --platform:
# without it pip would build from source against *this* machine's interpreter.
"$PYTHON" -m pip install \
  --target "$STAGE" \
  --platform manylinux2014_x86_64 \
  --platform manylinux_2_28_x86_64 \
  --python-version "$PY_VERSION" \
  --implementation cp \
  --abi "$ABI" \
  --only-binary=:all: \
  --upgrade \
  --quiet \
  "${RUNTIME_REQUIREMENTS[@]}"
ok "installed $(find "$STAGE" -maxdepth 1 -name '*.dist-info' | wc -l) distributions"

say "Copying application and fixtures"
mkdir -p "${STAGE}/backend"
cp -r "${ROOT}/backend/aether" "${STAGE}/backend/aether"
cp -r "${ROOT}/fixtures" "${STAGE}/fixtures"
cp "${ROOT}/deploy/lambda_handler.py" "${STAGE}/lambda_handler.py"
ok "application, fixtures and handler staged"

say "Stripping what Lambda will never execute"
before=$(du -sm "$STAGE" | cut -f1)
# numpy and scipy ship their test suites inside the wheel — roughly 60 MB, and
# the largest single reduction available. numpy/testing/ is a public helper
# module and is NOT matched here: only directories named exactly "tests" go.
find "$STAGE" -type d -name tests -prune -exec rm -rf {} +
find "$STAGE" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGE" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.pyi' \) -delete

# bin/ holds console-script launchers. Built on Windows they are .exe stubs,
# which cannot execute on Lambda's Linux runtime, and pip regenerates them with
# differing bytes on every install — so they are simultaneously dead weight and
# the reason two builds of identical inputs used to produce different archives.
rm -rf "${STAGE}/bin"

# RECORD is install bookkeeping for pip's uninstaller and lists a hash per
# installed file, including the launchers above. Nothing reads it at runtime —
# importlib.metadata resolves versions from METADATA — and leaving it would
# carry the launchers' variability back into the archive.
find "$STAGE" -type f -path '*.dist-info/RECORD' -delete
after=$(du -sm "$STAGE" | cut -f1)
ok "unzipped ${before} MB → ${after} MB"

if [[ "$after" -gt 250 ]]; then
  warn "unzipped size exceeds the 250 MB Lambda limit — deployment will fail"
fi

say "Writing the deterministic archive"
rm -f "$ZIP"
"$PYTHON" - "$STAGE" "$ZIP" <<'PY'
"""Write a zip whose bytes depend only on its contents.

Python's zipfile stamps each entry with the file's mtime, and os.walk yields
directory entries in filesystem order. Both vary between machines and would
make two builds of identical inputs produce different archives. Sorting the
paths and pinning every timestamp removes both sources of variation.
"""
import os
import stat
import sys
import zipfile

stage, target = sys.argv[1], sys.argv[2]
FIXED_TIME = (2026, 1, 1, 0, 0, 0)

paths = []
for directory, _subdirs, files in os.walk(stage):
    for name in files:
        absolute = os.path.join(directory, name)
        paths.append((os.path.relpath(absolute, stage).replace(os.sep, "/"), absolute))
paths.sort()

with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for arcname, absolute in paths:
        info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        # Lambda executes nothing from the package directly, but the runtime
        # does require read permission on every file it imports.
        mode = os.stat(absolute).st_mode
        executable = bool(mode & stat.S_IXUSR)
        info.external_attr = (0o755 if executable else 0o644) << 16
        with open(absolute, "rb") as handle:
            archive.writestr(info, handle.read())

print(f"{len(paths)} entries")
PY
ok "wrote $(du -m "$ZIP" | cut -f1) MB zipped"

# The 50 MB ceiling applies to `--zip-file fileb://` only. deploy.sh uploads
# through S3 when the archive is larger, so this is a note, not a failure.
zipped_bytes=$(wc -c < "$ZIP")
if [[ "$zipped_bytes" -gt 52428800 ]]; then
  warn "over the 50 MB direct-upload limit — deploy.sh will stage through S3"
fi

say "Recording the manifest"
{
  echo "# AETHER Lambda package manifest"
  echo "# Generated by deploy/build_lambda.sh. Records what was actually packaged,"
  echo "# so a deployed function can be tied back to a set of resolved versions."
  echo
  echo "built_from_commit: $(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "working_tree_clean: $( [[ -z "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]] && echo true || echo false )"
  echo "target_runtime: python${PY_VERSION} (${ABI}, manylinux x86_64)"
  echo "unzipped_mb: ${after}"
  echo "zipped_bytes: ${zipped_bytes}"
  echo "sha256: $("$PYTHON" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$ZIP")"
  echo
  echo "resolved_versions:"
  find "$STAGE" -maxdepth 1 -name '*.dist-info' -exec basename {} .dist-info \; | sort | sed 's/^/  - /'
} > "$MANIFEST"
ok "manifest at ${MANIFEST}"

printf '\n\033[32m✓ %s\033[0m\n' "package ready: ${ZIP}"
echo "  next: bash deploy/deploy.sh backend"
