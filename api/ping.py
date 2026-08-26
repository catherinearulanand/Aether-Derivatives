"""A dependency-free probe of the Vercel Python runtime.

WHY THIS EXISTS

The API function fails with a bare ``FUNCTION_INVOCATION_FAILED``, which carries
no module name and no traceback. Several fixes have been made against that
silence and none could be verified from outside. This function imports nothing
beyond the standard library, so it isolates the question:

    working here, failing on /api/v1/*  ->  the runtime is fine and AETHER's
                                            import is the problem, and the
                                            dependency report below names it
    failing here too                    ->  the problem is the Python runtime or
                                            the build configuration, not AETHER

It reports the same environment facts the API entrypoint would, so a diagnosis is
possible even when the application cannot be imported at all.

``app`` is a top-level assignment because Vercel detects the entrypoint by
statically scanning this file's top level for that name — it does not execute
the module to find one.

This is a diagnostic and is expected to be removed once the deployment is
healthy. It serves no product function and reads no fixture.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _listing(path: Path, limit: int = 60) -> object:
    try:
        return sorted(p.name for p in path.iterdir())[:limit]
    except OSError as exc:
        return f"unreadable: {exc}"


def _dependencies() -> dict[str, str]:
    """Import each runtime dependency alone, so a missing one is named rather than guessed."""
    report: dict[str, str] = {}
    for name in ("fastapi", "pydantic", "pydantic_settings", "numpy", "scipy", "pypdf"):
        try:
            module = __import__(name)
        except BaseException as exc:
            report[name] = f"{type(exc).__name__}: {exc}"
        else:
            report[name] = str(getattr(module, "__version__", "present"))
    return report


def _import_aether() -> object:
    """Attempt the import the API entrypoint makes, and report the outcome."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("AETHER_USE_TRUSTSTORE", "false")
    os.environ.setdefault("AETHER_MODE", "replay")
    try:
        from aether.api.main import app as application  # noqa: PLC0415
    except BaseException:
        return {"ok": False, "traceback": traceback.format_exc().splitlines()}
    return {"ok": True, "routes": len(getattr(application, "routes", []))}


def _report() -> dict[str, object]:
    return {
        "probe": "AETHER Vercel runtime probe",
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "cwd": os.getcwd(),
        "entrypoint": str(Path(__file__).resolve()),
        "root": str(ROOT),
        "root_contents": _listing(ROOT),
        "backend_exists": BACKEND.is_dir(),
        "backend_contents": _listing(BACKEND) if BACKEND.is_dir() else None,
        "aether_package": (BACKEND / "aether" / "__init__.py").is_file(),
        "fixtures_exists": (ROOT / "fixtures").is_dir(),
        "fixtures_contents": _listing(ROOT / "fixtures") if (ROOT / "fixtures").is_dir() else None,
        "dependencies": _dependencies(),
        "aether_import": _import_aether(),
        "sys_path": sys.path[:12],
    }


async def _probe(scope, receive, send):
    if scope["type"] != "http":
        return
    try:
        payload = json.dumps(_report(), indent=2, default=str).encode()
    except BaseException:
        payload = json.dumps({"report_failed": traceback.format_exc().splitlines()}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


app = _probe

__all__ = ["app"]
