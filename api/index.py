"""Vercel serverless entry point.

The FastAPI application is unchanged. Vercel's Python runtime speaks ASGI
directly, so unlike the Lambda package there is no Mangum adapter here — the
module simply has to expose ``app``.

Layout matters. ``aether.config`` derives ``REPO_ROOT`` from ``__file__``'s
grandparent and resolves ``fixtures/`` against it, so the deployed bundle must
keep the repository shape: ``backend/aether/config.py`` two levels under the
root, with ``fixtures/`` beside ``backend/``. ``vercel.json`` pulls the fixtures
in through ``includeFiles`` because nothing imports them — they are data, and
the dependency tracer cannot see them.

Routing. Every route on the app is declared under ``/api/v1``. The rewrite in
``vercel.json`` sends ``/api/*`` here while preserving the original request
path, so FastAPI matches on the URL the browser actually asked for.
"""

from __future__ import annotations

import os
import sys
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

from aether.api.main import app  # noqa: E402

__all__ = ["app"]
