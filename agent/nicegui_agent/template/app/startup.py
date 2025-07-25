from app.database import create_tables
from nicegui import ui


def startup() -> None:
    # this function is called before the first request
    create_tables()

    @ui.page("/")
    def index():
        ui.label("🚧 Work in progress 🚧").style("font-size: 2rem; text-align: center; margin-top: 2rem")
