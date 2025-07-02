from app.database import create_tables


def startup() -> None:
    # this function is called before the first request
    create_tables()
