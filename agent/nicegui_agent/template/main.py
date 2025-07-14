import os
from app.startup import startup
from nicegui import app, ui

# add health endpoint using fastapi route
@app.get('/health')
async def health():
    return {"status": "healthy", "service": "nicegui-app"}

app.on_startup(startup)
ui.run(
    host="0.0.0.0",
    port=int(os.environ.get('NICEGUI_PORT', 8000)),
    reload=False,
    storage_secret=os.environ.get('NICEGUI_STORAGE_SECRET', 'STORAGE_SECRET'),
    title="Created with ♥️ by app.build"
)
