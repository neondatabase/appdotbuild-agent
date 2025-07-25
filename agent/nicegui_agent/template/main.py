import logging
import os
from app.startup import startup
from nicegui import app, ui

# configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "nicegui-app"}


# suppress sqlalchemy engine logs below warning level
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)

app.on_startup(startup)
ui.run(
    host="0.0.0.0",
    port=int(os.environ.get("NICEGUI_PORT", 8000)),
    reload=False,
    storage_secret=os.environ.get("NICEGUI_STORAGE_SECRET", "STORAGE_SECRET"),
    title="Created with ♥️ by app.build",
)
