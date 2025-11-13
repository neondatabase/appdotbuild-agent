// Usage with zod schemas:
//
//   import { z } from 'zod';
//
//   const myTableSchema = z.object({
//     id: z.number(),
//     name: z.string(),
//     created_at: z.coerce.date(),
//   });
//
//   const client = new DatabricksClient();
//
//   // ✅ CORRECT - Pass Zod schema (not TypeScript type)
//   const result = await client.executeQuery("SELECT * FROM my_table", myTableSchema);
//   // result.rows is now validated and typed as z.infer<typeof myTableSchema>[]
//
//   // ❌ WRONG - Do NOT use generic type parameter alone
//   // const result = await client.executeQuery<MyType>("SELECT ...");
//   // This will cause runtime errors!

import { DBSQLClient } from "@databricks/sql";
import type { ConnectionOptions } from "@databricks/sql/dist/contracts/IDBSQLClient";
import { z } from "zod";

// Environment variables
const authMode: string = process.env["DATABRICKS_AUTH_MODE"] || "pat";
const serverHostname: string = (process.env["DATABRICKS_HOST"] || "")
  .replace(/^https?:\/\//, "") // strip http:// or https:// if present
  .replace(/\/$/, ""); // strip trailing slash if present
const warehouseId: string = process.env["DATABRICKS_WAREHOUSE_ID"] || "";
const token: string = process.env["DATABRICKS_TOKEN"] || "";
const clientId: string = process.env["DATABRICKS_CLIENT_ID"] || "";
const clientSecret: string = process.env["DATABRICKS_CLIENT_SECRET"] || "";
const httpPath = `/sql/1.0/warehouses/${warehouseId}`;

// Default schema for untyped queries - accepts any valid SQL value
export const sqlValueSchema = z.union([
  z.string(),
  z.number(),
  z.boolean(),
  z.date(),
  z.null(),
]);
export const defaultRowSchema = z.record(z.string(), sqlValueSchema);

export type SqlValue = z.infer<typeof sqlValueSchema>;
export type SqlRow = z.infer<typeof defaultRowSchema>;

export interface QueryResult<T = SqlRow> {
  rows: T[];
  rowCount: number;
}

export class DatabricksClient {
  private connectOptions: ConnectionOptions;

  constructor() {
    if (!serverHostname || !warehouseId) {
      console.error(`host: ${serverHostname}, warehouseId: ${warehouseId}`);
      throw new Error("Missing: DATABRICKS_HOST, DATABRICKS_WAREHOUSE_ID");
    }
    if (authMode === "pat") {
      if (!token) {
        throw new Error("Missing: DATABRICKS_TOKEN");
      }
      this.connectOptions = {
        host: serverHostname,
        path: httpPath,
        token: token,
      };
    } else if (authMode === "app") {
      this.connectOptions = {
        authType: "databricks-oauth" as const,
        host: serverHostname,
        path: httpPath,
        oauthClientId: clientId,
        oauthClientSecret: clientSecret,
      };
    } else {
      throw new Error(
        `Invalid DATABRICKS_AUTH_MODE: ${authMode}. Must be "pat" or "app"`,
      );
    }
  }

  /**
   * Execute a SQL query against Databricks and validate results with Zod schema.
   *
   * @param sql - SQL query string
   * @param schema - Zod schema for row validation (REQUIRED - pass the schema, not a TypeScript type)
   * @returns QueryResult with validated and typed rows
   *
   * @example
   * const schema = z.object({ id: z.number(), name: z.string() });
   * const result = await client.executeQuery("SELECT id, name FROM users", schema);
   * // result.rows is typed as { id: number; name: string }[]
   */
  async executeQuery<T extends z.ZodTypeAny>(
    sql: string,
    schema: T,
  ): Promise<QueryResult<z.infer<T>>> {
    try {
      const client = new DBSQLClient();
      const connection = await client.connect(this.connectOptions);
      const session = await connection.openSession();
      const operation = await session.executeStatement(sql, {
        runAsync: true,
        maxRows: 10000,
      });
      const result = await operation.fetchAll();
      await operation.close();
      await session.close();
      await connection.close();

      // Apply schema validation
      const rows = result.map((row) => schema.parse(row));
      return { rows: rows as z.infer<T>[], rowCount: rows.length };
    } catch (error) {
      console.error("Databricks SQL query error:", error);
      console.error("Error details:", {
        message: (error as any).message,
        code: (error as any).code,
        status: (error as any).status,
      });
      throw error;
    }
  }
}

/**
 * Helper utility to map and validate raw SQL rows using a Zod schema.
 * Useful when you have raw rows from nested queries or need manual mapping.
 *
 * @param rows - Array of raw SQL rows (Record<string, SqlValue>)
 * @param schema - Zod schema for validation
 * @returns Array of validated and typed objects
 *
 * @example
 * const rawRows = [{id: 1, name: "Alice"}, {id: 2, name: "Bob"}];
 * const schema = z.object({ id: z.number(), name: z.string() });
 * const users = mapRows(rawRows, schema);
 * // users is typed as { id: number; name: string }[]
 */
export function mapRows<T>(rows: SqlRow[], schema: z.ZodSchema<T>): T[] {
  return rows.map((row) => schema.parse(row));
}
