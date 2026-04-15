"""AWS Lambda entrypoint (API Gateway HTTP API + Mangum)."""

from __future__ import annotations

from mangum import Mangum

from main import app

handler = Mangum(app, lifespan="on")
