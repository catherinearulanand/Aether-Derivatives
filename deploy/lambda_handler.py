"""AWS Lambda entry point.

The FastAPI application is unchanged: Mangum adapts the ASGI interface to the
Lambda Function URL event shape. No business logic lives here.

Layout inside /var/task mirrors the repository, because ``aether.config``
derives ``REPO_ROOT`` from ``__file__``'s grandparent and resolves ``fixtures/``
against it. Flattening the tree would silently break fixture loading.
"""

from __future__ import annotations

import sys
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent
BACKEND = TASK_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mangum import Mangum  # noqa: E402

from aether.api.main import app  # noqa: E402

handler = Mangum(app, lifespan="off")
