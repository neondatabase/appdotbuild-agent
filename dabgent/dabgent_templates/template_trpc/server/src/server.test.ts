import { test } from "node:test";
import { strict as assert } from "node:assert";
import type { Server } from "node:http";

// set dummy env vars before importing index (only if not already set)
process.env["DATABRICKS_HOST"] =
  process.env["DATABRICKS_HOST"] || "https://dummy.databricks.com";
process.env["DATABRICKS_TOKEN"] = process.env["DATABRICKS_TOKEN"] || "dummy_token";

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

    const data = await response.json();
    assert.equal(data.result.data.json.status, "ok");
    assert.ok(data.result.data.json.timestamp);
  } finally {
    // always close server
    if (server) {
      await new Promise<void>((resolve) => server!.close(() => resolve()));
    }
  }
});
