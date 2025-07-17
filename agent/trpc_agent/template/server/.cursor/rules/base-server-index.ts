import { initTRPC } from '@trpc/server';
import { createHTTPServer } from '@trpc/server/adapters/standalone';
import 'dotenv/config';
import cors from 'cors';
import superjson from 'superjson';

// Import handlers and schemas
import { createEntityInputSchema, searchEntityInputSchema, updateEntityInputSchema } from './schema';
import { createEntity, getEntity, searchEntities, updateEntity, deleteEntity } from './handlers/entity';

const t = initTRPC.create({
  transformer: superjson, // Enable Date/BigInt serialization
});

const publicProcedure = t.procedure;
const router = t.router;

const appRouter = router({
  // Health check endpoint
  healthcheck: publicProcedure.query(() => {
    return { status: 'ok', timestamp: new Date().toISOString() };
  }),

  // CRUD operations for entities
  createEntity: publicProcedure
    .input(createEntityInputSchema)
    .mutation(({ input }) => createEntity(input)),

  getEntity: publicProcedure
    .input(z.object({ id: z.number() }))
    .query(({ input }) => getEntity(input.id)),

  searchEntities: publicProcedure
    .input(searchEntityInputSchema)
    .query(({ input }) => searchEntities(input)),

  updateEntity: publicProcedure
    .input(updateEntityInputSchema)
    .mutation(({ input }) => updateEntity(input)),

  deleteEntity: publicProcedure
    .input(z.object({ id: z.number() }))
    .mutation(({ input }) => deleteEntity(input.id)),
});

export type AppRouter = typeof appRouter;

async function start() {
  const port = process.env['SERVER_PORT'] || 2022;
  
  const server = createHTTPServer({
    middleware: (req, res, next) => {
      cors({
        origin: process.env['CLIENT_URL'] || 'http://localhost:3000',
        credentials: true
      })(req, res, next);
    },
    router: appRouter,
    createContext() {
      return {};
    },
  });
  
  server.listen(port);
  console.log(`TRPC server listening at port: ${port}`);
}

start().catch(console.error);