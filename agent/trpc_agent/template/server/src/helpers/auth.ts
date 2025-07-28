import { StackServerApp } from "@stackframe/react";
import cors from "cors";
import type { CreateHTTPContextOptions } from '@trpc/server/adapters/standalone';

export async function createContext({ req, res }: CreateHTTPContextOptions) {
  const stackApp = new StackServerApp({
    projectId: process.env["VITE_STACK_PROJECT_ID"],
    publishableClientKey: process.env["VITE_STACK_PUBLISHABLE_CLIENT_KEY"],
    secretServerKey: process.env["STACK_SECRET_SERVER_KEY"],
    tokenStore: {
      // @ts-ignore
      headers: new Headers(req.headers),
    },
  });
  try {
    const user = await stackApp.getUser();
    return { req, res, user };
  } catch (error) {
    return { req, res, user: null };
  }
}

export type Context = Awaited<ReturnType<typeof createContext>>;

export function createMiddleware() {
  if (process.env.NODE_ENV === "production") {
    return undefined;
  }
  return cors({
    origin: "http://localhost:5173",
    credentials: true,
  });
}
