// Databricks SQL execution client using REST API
// Based on Databricks SQL Statement Execution API v2.0
//
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

import { z } from "zod";

const SQL_WAREHOUSES_ENDPOINT = "/api/2.0/sql/warehouses";
const SQL_STATEMENTS_ENDPOINT = "/api/2.0/sql/statements";
const DEFAULT_WAIT_TIMEOUT = "30s";
const MAX_POLL_ATTEMPTS = 30;
const POLL_INTERVAL_MS = 2000;

interface Warehouse {
  id: string;
  name?: string;
  state: string;
}

interface WarehouseListResponse {
  warehouses: Warehouse[];
}

interface SqlStatementRequest {
  statement: string;
  warehouse_id: string;
  catalog?: string;
  schema?: string;
  row_limit?: number;
  disposition: string;
  format: string;
  wait_timeout?: string;
  on_wait_timeout?: string;
}

interface StatementError {
  message?: string;
}

interface StatementStatus {
  state: string;
  error?: StatementError;
}

interface Column {
  name: string;
}

interface Schema {
  columns: Column[];
}

interface ResultManifest {
  schema?: Schema;
}

interface StatementResult {
  data_array?: (string | null)[][];
}

interface SqlStatementResponse {
  statement_id: string;
  status?: StatementStatus;
  manifest?: ResultManifest;
  result?: StatementResult;
}

// Default schema for untyped queries - accepts any valid SQL value
export const sqlValueSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);
export const defaultRowSchema = z.record(z.string(), sqlValueSchema);

export type SqlValue = z.infer<typeof sqlValueSchema>;
export type SqlRow = z.infer<typeof defaultRowSchema>;

export interface QueryResult<T = SqlRow> {
  rows: T[];
  rowCount: number;
}

export class DatabricksClient {
  private host: string;
  private token: string = "";

  constructor() {
    const host = process.env["DATABRICKS_HOST"];
    const token = process.env["DATABRICKS_TOKEN"];

    if (!host) {
      throw new Error(
        "DATABRICKS_HOST and DATABRICKS_TOKEN environment variables must be set"
      );
    }
    // Token is not strictly required as Databricks Apps runtime may provide other auth methods
    this.host = host.startsWith("http") ? host : `https://${host}`;
    if (token) {
      this.token = token;
    }
  }

  private async apiRequest<T>(
    method: string,
    url: string,
    body?: any
  ): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.token}`,
      "Content-Type": "application/json",
    };

    const options: RequestInit = {
      method,
      headers,
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);
    const responseText = await response.text();

    if (!response.ok) {
      throw new Error(
        `Databricks API request failed with status ${response.status}: ${responseText}`
      );
    }

    return JSON.parse(responseText) as T;
  }

  private async getAvailableWarehouse(): Promise<string> {
    const url = `${this.host}${SQL_WAREHOUSES_ENDPOINT}`;
    const response = await this.apiRequest<WarehouseListResponse>(
      "GET",
      url
    );

    const runningWarehouse = response.warehouses.find(
      (w) => w.state === "RUNNING"
    );

    if (!runningWarehouse) {
      throw new Error("No running SQL warehouse found");
    }

    console.log(
      `Using warehouse: ${runningWarehouse.name || "Unknown"} (ID: ${runningWarehouse.id})`
    );

    return runningWarehouse.id;
  }

  private async pollForResults(
    statementId: string
  ): Promise<SqlRow[]> {
    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt++) {
      console.log(`Polling attempt ${attempt + 1} for statement ${statementId}`);

      const url = `${this.host}${SQL_STATEMENTS_ENDPOINT}/${statementId}`;
      const response = await this.apiRequest<SqlStatementResponse>("GET", url);

      if (response.status) {
        switch (response.status.state) {
          case "SUCCEEDED":
            return this.processStatementResult(response);
          case "FAILED":
            const errorMsg =
              response.status.error?.message || "Unknown error";
            throw new Error(`SQL execution failed: ${errorMsg}`);
          case "PENDING":
          case "RUNNING":
            await new Promise((resolve) =>
              setTimeout(resolve, POLL_INTERVAL_MS)
            );
            continue;
          default:
            throw new Error(
              `Unexpected statement state: ${response.status.state}`
            );
        }
      }
    }

    throw new Error(`Polling timeout exceeded for statement ${statementId}`);
  }

  private processStatementResult(
    response: SqlStatementResponse
  ): SqlRow[] {
    const schema = response.manifest?.schema;

    if (!schema) {
      throw new Error("No schema in response");
    }

    if (!response.result?.data_array) {
      // empty result set
      return [];
    }

    const results: SqlRow[] = [];

    for (const row of response.result.data_array) {
      const rowMap: SqlRow = {};

      for (let i = 0; i < schema.columns.length; i++) {
        const column = schema.columns[i];
        const value = row[i];

        if (value === null) {
          rowMap[column.name] = null;
        } else {
          // try to parse as number, fallback to string
          const numValue = Number(value);
          rowMap[column.name] = isNaN(numValue) ? value : numValue;
        }
      }

      results.push(rowMap);
    }

    return results;
  }

  async executeQuery<T extends z.ZodTypeAny = typeof defaultRowSchema>(
    sql: string,
    schema?: T
  ): Promise<QueryResult<z.infer<T>>> {
    console.log(`Executing SQL: ${sql.replace(/\n/g, " ")}`);

    const warehouseId = await this.getAvailableWarehouse();

    const request: SqlStatementRequest = {
      statement: sql,
      warehouse_id: warehouseId,
      row_limit: 10000,
      disposition: "INLINE",
      format: "JSON_ARRAY",
      wait_timeout: DEFAULT_WAIT_TIMEOUT,
      on_wait_timeout: "CONTINUE",
    };

    const url = `${this.host}${SQL_STATEMENTS_ENDPOINT}`;
    const response = await this.apiRequest<SqlStatementResponse>(
      "POST",
      url,
      request
    );

    // check if we need to poll for results
    if (response.status) {
      if (
        response.status.state === "PENDING" ||
        response.status.state === "RUNNING"
      ) {
        const rawRows = await this.pollForResults(response.statement_id);
        const rows = schema
          ? rawRows.map((row) => schema.parse(row))
          : rawRows;
        return { rows: rows as z.infer<T>[], rowCount: rows.length };
      } else if (response.status.state === "FAILED") {
        const errorMsg = response.status.error?.message || "Unknown error";
        throw new Error(`SQL execution failed: ${errorMsg}`);
      }
    }

    const rawRows = this.processStatementResult(response);
    const rows = schema
      ? rawRows.map((row) => schema.parse(row))
      : rawRows;
    return { rows: rows as z.infer<T>[], rowCount: rows.length };
  }
}
