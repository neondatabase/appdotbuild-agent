import 'dotenv/config';
import { drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import * as schema from './schema';

const pool = new Pool({
  connectionString: process.env['APP_DATABASE_URL']!,
});

// Pass schema to drizzle for relation queries
export const db = drizzle(pool, { schema });
