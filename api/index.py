"""Vercel serverless entry point.

The FastAPI application is unchanged. Vercel's Python runtime speaks ASGI
directly, so unlike the Lambda package there is no Mangum adapter here — the
module simply has to expose ``app``.

Layout matters. ``aether.config`` derives ``REPO_ROOT`` from ``__file__``'s
grandparent and resolves ``fixtures/`` against it, so the deployed bundle must
keep the repository shape: ``backend/aether/config.py`` two levels under the
root, with ``fixtures/`` beside ``backend/``. ``vercel.json`` pulls both in
through ``includeFiles``, because the application is reached by mutating
``sys.path`` at runtime and fixtures are data — neither is visible to a static
import tracer.

Routing. Every route on the app is declared under ``/api/v1``. The rewrite in
``vercel.json`` sends ``/api/*`` here while preserving the original request
path, so FastAPI matches on the URL the browser actually asked for.

WHY THE IMPORT IS GUARDED

An exception raised while importing the application aborts the invocation
before any handler exists, and the platform answers with a bare
``FUNCTION_INVOCATION_FAILED`` — no module name, no traceback, no way to tell a
missing package from a missing file without dashboard access. The guard below
converts that into a 500 whose body says what failed and what the bundle
actually contains. It cannot mask a working deployment: it is reachable only
when the import has already failed.
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


def _bundle_report() -> dict[str, object]:
    """What the function can actually see on disk, for diagnosing an import failure."""

    def listing(path: Path, limit: int = 40) -> object:
        try:
            return sorted(p.name for p in path.iterdir())[:limit]
        except OSError as exc:
            return f"unreadable: {exc}"

    return {
        "python": sys.version,
        "cwd": os.getcwd(),
        "entrypoint": str(Path(__file__).resolve()),
        "root": str(ROOT),
        "root_contents": listing(ROOT),
        "backend_exists": BACKEND.is_dir(),
        "backend_contents": listing(BACKEND) if BACKEND.is_dir() else None,
        "aether_package_exists": (BACKEND / "aether" / "__init__.py").is_file(),
        "fixtures_exists": (ROOT / "fixtures").is_dir(),
        "fixtures_contents": listing(ROOT / "fixtures") if (ROOT / "fixtures").is_dir() else None,
        "sys_path": sys.path[:12],
    }


try:
    from aether.api.main import app
except BaseException:  # noqa: BLE001 - the report must survive any import failure
    _FAILURE = {
        "error": "AETHER failed to import inside the Vercel function.",
        "traceback": traceback.format_exc().splitlines(),
        "bundle": _bundle_report(),
    }

    async def app(scope, receive, send):  # type: ignore[misc]
        """Minimal ASGI app that reports why the real one could not be imported."""
        if scope["type"] != "http":
            return
        body = json.dumps(_FAILURE, indent=2, default=str).encode()
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
        await send({"type": "http.response.body", "body": body})


__all__ = ["app"]
