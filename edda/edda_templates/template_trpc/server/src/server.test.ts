import { test } from "node:test";
import { strict as assert } from "node:assert";
import type { Server } from "node:http";
import superjson from "superjson";

// set dummy env vars before importing index (only if not already set)
process.env["DATABRICKS_HOST"] =
  process.env["DATABRICKS_HOST"] || "https://dummy.databricks.com";
process.env["DATABRICKS_TOKEN"] = process.env["DATABRICKS_TOKEN"] || "dummy_token";
process.env["DATABRICKS_WAREHOUSE_ID"] =
  process.env["DATABRICKS_WAREHOUSE_ID"] || "dummy_warehouse_id";

test("server starts and responds to healthcheck", async () => {
  // dynamic import to ensure env vars are set first
  const { startServer } = await import("./index");

  const port = 8001; // use different port to avoid conflicts
  let server: Server | null = null;

  try {
    server = startServer(port);

    // wait for server to be ready
    await new Promise((resolve) => setTimeout(resolve, 500));

    // make request to healthcheck endpoint
    const response = await fetch(`http://localhost:${port}/api/healthcheck`);
    assert.equal(response.status, 200);

    const data: any = await response.json();
    assert.equal(data.result.data.json.status, "ok");
    assert.ok(data.result.data.json.timestamp);
  } finally {
    // always close server
    if (server) {
      await new Promise<void>((resolve) => server!.close(() => resolve()));
    }
  }
});

// Example: Testing tRPC procedures directly without HTTP server
// This is faster and simpler for most tests
//
// test("getUsers returns array of users", async () => {
//   const { appRouter } = await import("./index");
//   const { initTRPC } = await import("@trpc/server");
//
//   // create tRPC caller - no HTTP server needed
//   const t = initTRPC.create({ transformer: superjson });
//   const caller = t.createCallerFactory(appRouter)({});
//
//   const result = await caller.getUsers();
//
//   // validate structure
//   assert.ok(Array.isArray(result));
//   if (result.length > 0) {
//     assert.ok(result[0].id);
//     assert.ok(result[0].name);
//   }
// });
//
// test("getMetrics with input parameter", async () => {
//   const { appRouter } = await import("./index");
//   const { initTRPC } = await import("@trpc/server");
//
//   const t = initTRPC.create({ transformer: superjson });
//   const caller = t.createCallerFactory(appRouter)({});
//
//   const result = await caller.getMetrics({ category: "sales" });
//
//   assert.ok(Array.isArray(result));
//   // add assertions for your expected data structure
// });
