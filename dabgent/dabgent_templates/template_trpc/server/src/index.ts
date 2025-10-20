import { initTRPC } from "@trpc/server";
import { createExpressMiddleware } from "@trpc/server/adapters/express";
import express from "express";
import "dotenv/config";
import superjson from "superjson";
import path from "node:path";
import { z } from "zod";
import { DatabricksClient } from "./databricks";

const STATIC_DIR = path.join(__dirname, "..", "public");

const t = initTRPC.create({
  transformer: superjson,
});

const publicProcedure = t.procedure;
const router = t.router;

const appRouter = router({
  healthcheck: publicProcedure.query(() => {
    return { status: "ok", timestamp: new Date().toISOString() };
  }),
  // Add specific data endpoints here
  // Example:
  // getUsers: publicProcedure.query(async () => {
  //   const client = new DatabricksClient();
  //   return await client.executeQuery("SELECT * FROM users LIMIT 100");
  // }),
});

export type AppRouter = typeof appRouter;

export const app = express();

// Serve static files
app.use(express.static(STATIC_DIR));

app.use(
  "/api",
  createExpressMiddleware({
    router: appRouter,
    createContext() {
      return {};
    },
  }),
);

app.get("/{*zzz}", (req, res) => {
  res.sendFile(path.join(STATIC_DIR, "index.html"));
});

export function startServer(port: number = Number(process.env["PORT"]) || 8000) {
  return app.listen(port, () => {
    console.log(`Server listening at port: ${port}`);
    console.log(`tRPC endpoint: http://localhost:${port}/api`);
    console.log(`Frontend: http://localhost:${port}/`);
  });
}

// start server if this file is run directly
if (require.main === module) {
  startServer();
}
