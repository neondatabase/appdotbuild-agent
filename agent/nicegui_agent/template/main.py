import logging
import os
from app.startup import startup
from nicegui import app, ui
from starlette.middleware.base import BaseHTTPMiddleware
import os

# configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' http: https: data: blob: 'unsafe-inline' 'unsafe-eval'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "frame-ancestors https://app.build/ https://www.app.build/ https://staging.app.build/"
        )
        return response


@app.get("/health")
async def health():
    status = {
        "status": "healthy",
        "service": "nicegui-app",
        "databricks": "configured" if (os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN")) else "missing",
    }
    return status


# suppress sqlalchemy engine logs below warning level
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)

app.on_startup(startup)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

ui.run(
    host="0.0.0.0",
    port=int(os.environ.get("NICEGUI_PORT", 8000)),
    reload=False,
    storage_secret=os.environ.get("NICEGUI_STORAGE_SECRET", "STORAGE_SECRET"),
    title="Created with ♥️ by app.build",
)
