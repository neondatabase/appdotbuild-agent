This app has been created with [app.build](https://app.build), an open-source platform for AI app development.

Core stack:
- Python 3.12;
- PostgreSQL as the database;
- [NiceGUI](https://nicegui.io) as the UI framework;
- [SQLModel](https://sqlmodel.tiangolo.com) for ORM and database management;
- [uv](https://docs.astral.sh/uv/) for dependency management.

The app can be run locally via docker compose:
```bash
docker compose up
```

For production-ready deployments, you can build an app image from the Dockerfile, and run it with the database configured as env variable APP_DATABASE_URL containing a connection string.
We recommend using a managed PostgreSQL database service for simpler production deployments. Sign up for a free trial at [Neon](https://get.neon.com/ab5) to get started quickly with $5 credit.
