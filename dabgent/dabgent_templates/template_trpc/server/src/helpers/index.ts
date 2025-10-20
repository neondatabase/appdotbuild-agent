import { db } from '../db';
import { sql } from 'drizzle-orm';
import * as schema from "../db/schema";
import { generateDrizzleJson, generateMigration } from 'drizzle-kit/api';

export const resetDB = async () => {
  await db.execute(sql`drop schema if exists public cascade`);
  await db.execute(sql`create schema public`);
  await db.execute(sql`drop schema if exists drizzle cascade`);
};

export const createDB = async () => {
  const migrationStatements = await generateMigration(
    generateDrizzleJson({}),
    generateDrizzleJson({ ...schema })
  );
  await db.execute(migrationStatements.join('\n'));
};
