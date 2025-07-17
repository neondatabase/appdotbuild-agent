This app has been created with [app.build](https://app.build), an open-source platform for AI app development.

Core stack:
- TypeScript with [tRPC](https://trpc.io) for type-safe API communication;
- React 19 with [Vite](https://vitejs.dev) for the frontend;
- [Drizzle ORM](https://orm.drizzle.team) for database management;
- PostgreSQL as the database;
- [shadcn/ui](https://ui.shadcn.com) for UI components;
- [Bun](https://bun.sh) as the runtime and package manager.

The app can be run locally via docker compose:
```bash
docker compose up
```

## Project Structure

- `client/` - React frontend application (see [client/README.md](client/README.md) for Vite/React setup details)
- `server/` - tRPC backend server with Drizzle ORM
- `tests/` - Playwright test for end-to-end smoke testing;

For production-ready deployments, you can build an app image from the Dockerfile, and run it with the database configured as env variable APP_DATABASE_URL containing a connection string.
We recommend using a managed Postgres database service for simpler production deployments. Sign up for a free trial at [Neon](https://get.neon.com/ab5) to get started quickly with $5 credit.
