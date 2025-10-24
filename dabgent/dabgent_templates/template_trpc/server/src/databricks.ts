// Usage with zod schemas:
//
//   import { z } from 'zod';
//
//   const myTableSchema = z.object({
//     id: z.number(),
//     name: z.string(),
//     created_at: z.string(),
//   });
//
//   const client = new DatabricksClient();
//   const result = await client.executeQuery("SELECT * FROM my_table", myTableSchema);
//   // result.rows is now validated and typed as MyTable[]

import { DBSQLClient } from "@databricks/sql";
import { z } from "zod";

// Environment variables
const authMode: string = process.env["DATABRICKS_AUTH_MODE"] || "pat";
const serverHostname: string = process.env["DATABRICKS_HOST"] || "";
const warehouseId: string = process.env["DATABRICKS_WAREHOUSE_ID"] || "";
const token: string = process.env["DATABRICKS_TOKEN"] || "";
const clientId: string = process.env["DATABRICKS_CLIENT_ID"] || "";
const clientSecret: string = process.env["DATABRICKS_CLIENT_SECRET"] || "";
const httpPath = `/sql/1.0/warehouses/${warehouseId}`;

// Validate required environment variables based on auth mode
if (!serverHostname || !warehouseId) {
  console.error(`host: ${serverHostname}, warehouseId: ${warehouseId}`);
  throw new Error("Missing: DATABRICKS_HOST, DATABRICKS_WAREHOUSE_ID");
}

if (authMode === "pat") {
  if (!token) {
    throw new Error("Missing: DATABRICKS_TOKEN");
  }
} else if (authMode === "app") {
  if (!clientId || !clientSecret) {
    throw new Error(
      "Missing DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET",
    );
  }
} else {
  throw new Error(
    `Invalid DATABRICKS_AUTH_MODE: ${authMode}. Must be "pat" or "app"`,
  );
}

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
  async executeQuery<T extends z.ZodTypeAny = typeof defaultRowSchema>(
    sql: string,
    schema?: T,
  ): Promise<QueryResult<z.infer<T>>> {
    try {
      const client = new DBSQLClient();
      const connectOptions =
        authMode === "pat"
          ? {
              host: serverHostname,
              path: httpPath,
              token: token,
            }
          : {
              authType: "databricks-oauth" as const,
              host: serverHostname,
              path: httpPath,
              oauthClientId: clientId,
              oauthClientSecret: clientSecret,
            };

      const connection = await client.connect(connectOptions);
      const session = await connection.openSession();
      const operation = await session.executeStatement(sql, {
        runAsync: true,
        maxRows: 10000,
      });
      const result = await operation.fetchAll();
      await operation.close();
      await session.close();
      await connection.close();

      // Apply schema validation if provided
      const rows = schema ? result.map((row) => schema.parse(row)) : result;
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
