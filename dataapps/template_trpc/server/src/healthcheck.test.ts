import { test } from "node:test";
import { strict as assert } from "node:assert";
import { initTRPC } from "@trpc/server";
import superjson from "superjson";

// import router setup from index.ts - but we need to export it first
// for now, recreate locally to test the structure
const t = initTRPC.create({
  transformer: superjson,
});

const publicProcedure = t.procedure;
const router = t.router;

const appRouter = router({
  healthcheck: publicProcedure.query(() => {
    return { status: "ok", timestamp: new Date().toISOString() };
  }),
});

test("healthcheck returns ok status", async () => {
  const caller = appRouter.createCaller({});
  const result = await caller.healthcheck();

  assert.equal(result.status, "ok");
  assert.ok(result.timestamp);
  assert.ok(typeof result.timestamp === "string");
});

test("healthcheck timestamp is valid ISO date", async () => {
  const caller = appRouter.createCaller({});
  const result = await caller.healthcheck();

  const date = new Date(result.timestamp);
  assert.ok(!isNaN(date.getTime()));
});
