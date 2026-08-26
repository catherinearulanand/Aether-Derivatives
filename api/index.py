"""Vercel serverless entry point.

The FastAPI application is unchanged. Vercel's Python runtime speaks ASGI
directly, so unlike the Lambda package there is no Mangum adapter here — the
module simply has to expose ``app``.

WHY ``app`` IS A TOP-LEVEL ASSIGNMENT

Vercel detects the entrypoint by statically scanning this file's top level for a
name ``app``; it does not execute the module to find one. An earlier revision
guarded the import with ``try``/``except`` and defined the fallback inside the
handler — which left no ``app`` node at the top level, so detection failed and
the build died in two seconds with "No FastAPI entrypoint found". The loading is
therefore done in a function and bound here, where a scan can see it.

WHY THE IMPORT IS GUARDED AT ALL

An exception raised while importing the application aborts the invocation before
any handler exists, and the platform answers with a bare
``FUNCTION_INVOCATION_FAILED`` — no module name, no traceback, no way to tell a
missing package from a missing file without dashboard access. The guard converts
that into a 500 whose body says what failed and what the bundle actually
contains. It cannot mask a working deployment: it is reachable only once the
import has already failed.

LAYOUT

``aether.config`` derives ``REPO_ROOT`` from ``__file__``'s grandparent and
resolves ``fixtures/`` against it, so the bundle must keep the repository shape:
``backend/aether/config.py`` two levels under the root, ``fixtures/`` beside
``backend/``. ``vercel.json`` pulls both in through ``includeFiles``, because the
application is reached by mutating ``sys.path`` at runtime and fixtures are data
— neither is visible to a static import tracer.

ROUTING

Every route on the app is declared under ``/api/v1``. The rewrite in
``vercel.json`` sends ``/api/*`` here while preserving the original request path,
so FastAPI matches on the URL the browser actually asked for.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# truststore exists for the TLS interception on the development machine and is
# not in requirements.txt. install_tls_trust already degrades to a no-op on
# ImportError; setting this false skips the attempt rather than relying on the
# rescue. setdefault, so a dashboard environment variable still wins.
os.environ.setdefault("AETHER_USE_TRUSTSTORE", "false")

# Replay is the Settings default; stating it here makes the deployed mode
# readable from the source rather than inferred from an absent variable.
os.environ.setdefault("AETHER_MODE", "replay")


def _listing(path: Path, limit: int = 60) -> object:
    try:
        return sorted(p.name for p in path.iterdir())[:limit]
    except OSError as exc:
        return f"unreadable: {exc}"


def _dependency_report() -> dict[str, str]:
    """Import each runtime dependency alone, so a missing one is named rather than guessed."""
    report: dict[str, str] = {}
    for name in ("fastapi", "pydantic", "pydantic_settings", "numpy", "scipy", "pypdf"):
        try:
            module = __import__(name)
        except BaseException as exc:  # noqa: BLE001
            report[name] = f"{type(exc).__name__}: {exc}"
        else:
            report[name] = str(getattr(module, "__version__", "present"))
    return report


def _bundle_report() -> dict[str, object]:
    """What the function can actually see on disk, for diagnosing an import failure."""
    return {
        "python": sys.version,
        "cwd": os.getcwd(),
        "entrypoint": str(Path(__file__).resolve()),
        "root": str(ROOT),
        "root_contents": _listing(ROOT),
        "backend_exists": BACKEND.is_dir(),
        "backend_contents": _listing(BACKEND) if BACKEND.is_dir() else None,
        "aether_package": (BACKEND / "aether" / "__init__.py").is_file(),
        "fixtures_exists": (ROOT / "fixtures").is_dir(),
        "fixtures_contents": _listing(ROOT / "fixtures") if (ROOT / "fixtures").is_dir() else None,
        "dependencies": _dependency_report(),
        "sys_path": sys.path[:12],
    }


def _diagnostic_app(failure: dict[str, object]):
    """A minimal ASGI app that reports why the real one could not be imported."""

    async def report(scope, receive, send):
        if scope["type"] != "http":
            return
        payload = json.dumps(failure, indent=2, default=str).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})

    return report


def _load_application():
    try:
        from aether.api.main import app as application
    except BaseException:  # noqa: BLE001 - the report must survive any import failure
        return _diagnostic_app(
            {
                "error": "AETHER failed to import inside the Vercel function.",
                "traceback": traceback.format_exc().splitlines(),
                "bundle": _bundle_report(),
            }
        )
    return application


app = _load_application()

__all__ = ["app"]
