BASE_TYPESCRIPT_SCHEMA = """
<file path="server/src/schema.ts">
import { z } from 'zod';

// Product schema with proper numeric handling
export const productSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string().nullable(), // Nullable field, not optional (can be explicitly null)
  price: z.number(), // Stored as numeric in DB, but we use number in TS
  stock_quantity: z.number().int(), // Ensures integer values only
  created_at: z.coerce.date() // Automatically converts string timestamps to Date objects
});

export type Product = z.infer<typeof productSchema>;

// Input schema for creating products
export const createProductInputSchema = z.object({
  name: z.string(),
  description: z.string().nullable(), // Explicit null allowed, undefined not allowed
  price: z.number().positive(), // Validate that price is positive
  stock_quantity: z.number().int().nonnegative() // Validate that stock is non-negative integer
});

export type CreateProductInput = z.infer<typeof createProductInputSchema>;

// Input schema for updating products
export const updateProductInputSchema = z.object({
  id: z.number(),
  name: z.string().optional(), // Optional = field can be undefined (omitted)
  description: z.string().nullable().optional(), // Can be null or undefined
  price: z.number().positive().optional(),
  stock_quantity: z.number().int().nonnegative().optional()
});

export type UpdateProductInput = z.infer<typeof updateProductInputSchema>;
</file>
""".strip()


BASE_DRIZZLE_SCHEMA = """
<file path="server/src/db/schema.ts">
import { serial, text, pgTable, timestamp, numeric, integer } from 'drizzle-orm/pg-core';

export const productsTable = pgTable('products', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  description: text('description'), // Nullable by default, matches Zod schema
  price: numeric('price', { precision: 10, scale: 2 }).notNull(), // Use numeric for monetary values with precision
  stock_quantity: integer('stock_quantity').notNull(), // Use integer for whole numbers
  created_at: timestamp('created_at').defaultNow().notNull(),
});

// TypeScript type for the table schema
export type Product = typeof productsTable.$inferSelect; // For SELECT operations
export type NewProduct = typeof productsTable.$inferInsert; // For INSERT operations

// Important: Export all tables and relations for proper query building
export const tables = { products: productsTable };
</file>
""".strip()


BASE_HANDLER_DECLARATION = """
<file path="server/src/handlers/create_product.ts">
import { type CreateProductInput, type Product } from '../schema';

export const async createProduct(input: CreateProductInput): Promise<Product> => {
    // This is a placeholder declaration! Real code should be implemented here.
    // The goal of this handler is creating a new product persisting it in the database.
    return Promise.resolve({
        id: 0, // Placeholder ID
        name: input.name,
        description: input.description || null, // Handle nullable field
        price: input.price,
        stock_quantity: input.stock_quantity,
        created_at: new Date() // Placeholder date
    } as Product
    )
}

</file>
""".strip()

BASE_GET_HANDLER_DECLARATION = """
<file path="server/src/handlers/get_products.ts">
import { type Product } from '../schema';

export const async getProducts(): Promise<Product[]> => {
    // This is a placeholder declaration! Real code should be implemented here.
    // The goal of this handler is fetching all products from the database.
    return [];
}
</file>
""".strip()


BASE_HANDLER_IMPLEMENTATION = """
<file path="server/src/handlers/create_product.ts">
import { db } from '../db';
import { productsTable } from '../db/schema';
import { type CreateProductInput, type Product } from '../schema';

export const createProduct = async (input: CreateProductInput): Promise<Product> => {
  try {
    // Insert product record
    const result = await db.insert(productsTable)
      .values({
        name: input.name,
        description: input.description,
        price: input.price.toString(), // Convert number to string for numeric column
        stock_quantity: input.stock_quantity // Integer column - no conversion needed
      })
      .returning()
      .execute();

    // Convert numeric fields back to numbers before returning
    const product = result[0];
    return {
      ...product,
      price: parseFloat(product.price) // Convert string back to number
    };
  } catch (error) {
    console.error('Product creation failed:', error);
    throw error;
  }
};
</file>
""".strip()


BASE_HANDLER_TEST = """
<file path="server/src/tests/create_product.test.ts">
import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { resetDB, createDB } from '../helpers';
import { db } from '../db';
import { productsTable } from '../db/schema';
import { type CreateProductInput } from '../schema';
import { createProduct } from '../handlers/create_product';
import { eq, gte, between, and } from 'drizzle-orm';

// Simple test input
const testInput: CreateProductInput = {
  name: 'Test Product',
  description: 'A product for testing',
  price: 19.99,
  stock_quantity: 100
};

describe('createProduct', () => {
  beforeEach(createDB);
  afterEach(resetDB);

  it('should create a product', async () => {
    const result = await createProduct(testInput);

    // Basic field validation
    expect(result.name).toEqual('Test Product');
    expect(result.description).toEqual(testInput.description);
    expect(result.price).toEqual(19.99);
    expect(result.stock_quantity).toEqual(100);
    expect(result.id).toBeDefined();
    expect(result.created_at).toBeInstanceOf(Date);
  });

  it('should save product to database', async () => {
    const result = await createProduct(testInput);

    // Query using proper drizzle syntax
    const products = await db.select()
      .from(productsTable)
      .where(eq(productsTable.id, result.id))
      .execute();

    expect(products).toHaveLength(1);
    expect(products[0].name).toEqual('Test Product');
    expect(products[0].description).toEqual(testInput.description);
    expect(parseFloat(products[0].price)).toEqual(19.99);
    expect(products[0].created_at).toBeInstanceOf(Date);
  });

  it('should query products by date range correctly', async () => {
    // Create test product
    await createProduct(testInput);

    // Test date filtering - demonstration of correct date handling
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    // Proper query building - step by step
    let query = db.select()
      .from(productsTable);

    // Apply date filter - Date objects work directly with timestamp columns
    query = query.where(
      and([
        gte(productsTable.created_at, today),
        between(productsTable.created_at, today, tomorrow)
      ])
    );

    const products = await query.execute();

    expect(products.length).toBeGreaterThan(0);
    products.forEach(product => {
      expect(product.created_at).toBeInstanceOf(Date);
      expect(product.created_at >= today).toBe(true);
      expect(product.created_at <= tomorrow).toBe(true);
    });
  });
});
</file>
""".strip()


BASE_SERVER_INDEX = """
<file path="server/src/index.ts">
import { initTRPC } from '@trpc/server';
import { createHTTPServer } from '@trpc/server/adapters/standalone';
import 'dotenv/config';
import cors from 'cors';
import superjson from 'superjson';

const t = initTRPC.create({
  transformer: superjson,
});

const publicProcedure = t.procedure;
const router = t.router;

const appRouter = router({
  healthcheck: publicProcedure.query(() => {
    return { status: 'ok', timestamp: new Date().toISOString() };
  }),
});

export type AppRouter = typeof appRouter;

async function start() {
  const port = process.env['SERVER_PORT'] || 2022;
  const server = createHTTPServer({
    middleware: (req, res, next) => {
      cors()(req, res, next);
    },
    router: appRouter,
    createContext() {
      return {};
    },
  });
  server.listen(port);
  console.log(`TRPC server listening at port: ${port}`);
}

start();
</file>
""".strip()


BASE_APP_TSX = """
<file path="client/src/App.tsx">
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { trpc } from '@/utils/trpc';
import { useState, useEffect, useCallback } from 'react';
// Using type-only import for better TypeScript compliance
import type { Product, CreateProductInput } from '../../server/src/schema';

function App() {
  // Explicit typing with Product interface
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Form state with proper typing for nullable fields
  const [formData, setFormData] = useState<CreateProductInput>({
    name: '',
    description: null, // Explicitly null, not undefined
    price: 0,
    stock_quantity: 0
  });

  // useCallback to memoize function used in useEffect
  const loadProducts = useCallback(async () => {
    try {
      const result = await trpc.getProducts.query();
      setProducts(result);
    } catch (error) {
      console.error('Failed to load products:', error);
    }
  }, []); // Empty deps since trpc is stable

  // useEffect with proper dependencies
  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      const response = await trpc.createProduct.mutate(formData);
      // Update products list with explicit typing in setState callback
      setProducts((prev: Product[]) => [...prev, response]);
      // Reset form
      setFormData({
        name: '',
        description: null,
        price: 0,
        stock_quantity: 0
      });
    } catch (error) {
      console.error('Failed to create product:', error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-2xl font-bold mb-4">Product Management</h1>

      <form onSubmit={handleSubmit} className="space-y-4 mb-8">
        <Input
          placeholder="Product name"
          value={formData.name}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFormData((prev: CreateProductInput) => ({ ...prev, name: e.target.value }))
          }
          required
        />
        <Input
          placeholder="Description (optional)"
          // Handle nullable field with fallback to empty string
          value={formData.description || ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFormData((prev: CreateProductInput) => ({
              ...prev,
              description: e.target.value || null // Convert empty string back to null
            }))
          }
        />
        <Input
          type="number"
          placeholder="Price"
          value={formData.price}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFormData((prev: CreateProductInput) => ({ ...prev, price: parseFloat(e.target.value) || 0 }))
          }
          step="0.01"
          min="0"
          required
        />
        <Input
          type="number"
          placeholder="Stock quantity"
          value={formData.stock_quantity}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFormData((prev: CreateProductInput) => ({ ...prev, stock_quantity: parseInt(e.target.value) || 0 }))
          }
          min="0"
          required
        />
        <Button type="submit" disabled={isLoading}>
          {isLoading ? 'Creating...' : 'Create Product'}
        </Button>
      </form>

      {products.length === 0 ? (
        <p className="text-gray-500">No products yet. Create one above!</p>
      ) : (
        <div className="grid gap-4">
          {products.map((product: Product) => (
            <div key={product.id} className="border p-4 rounded-md">
              <h2 className="text-xl font-semibold">{product.name}</h2>
              {/* Handle nullable description */}
              {product.description && (
                <p className="text-gray-600">{product.description}</p>
              )}
              <div className="flex justify-between mt-2">
                <span>${product.price.toFixed(2)}</span>
                <span>In stock: {product.stock_quantity}</span>
              </div>
              <p className="text-xs text-gray-400 mt-2">
                Created: {product.created_at.toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;
</file>
""".strip()


BASE_COMPONENT_EXAMPLE = """
<file path="client/src/components/ProductForm.tsx">
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useState } from 'react';
// Note the extra ../ because we're in components subfolder
import type { CreateProductInput } from '../../../server/src/schema';

interface ProductFormProps {
  onSubmit: (data: CreateProductInput) => Promise<void>;
  isLoading?: boolean;
}

export function ProductForm({ onSubmit, isLoading = false }: ProductFormProps) {
  const [formData, setFormData] = useState<CreateProductInput>({
    name: '',
    description: null,
    price: 0,
    stock_quantity: 0
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSubmit(formData);
    // Reset form after successful submission
    setFormData({
      name: '',
      description: null,
      price: 0,
      stock_quantity: 0
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <Input
        value={formData.name}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          setFormData((prev: CreateProductInput) => ({ ...prev, name: e.target.value }))
        }
        placeholder="Product name"
        required
      />
      <Input
        value={formData.description || ''} // Fallback for null
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          setFormData((prev: CreateProductInput) => ({
            ...prev,
            description: e.target.value || null
          }))
        }
        placeholder="Description (optional)"
      />
      <Button type="submit" disabled={isLoading}>
        {isLoading ? 'Creating...' : 'Create Product'}
      </Button>
    </form>
  );
}
</file>
""".strip()

TRPC_INDEX_SHIM = """
...
import { createProductInputSchema } from './schema';
import { createProduct } from './handlers/create_product';
import { getProducts } from './handlers/get_products';
...
const appRouter = router({
  createProduct: publicProcedure
    .input(createProductInputSchema)
    .mutation(({ input }) => createProduct(input)),
  getProducts: publicProcedure
    .query(() => getProducts()),
});
...
""".strip()

TYPE_ALIGNMENT_RULES_SCHEMA = """# CRITICAL Type Alignment Rules for Schema Definition:
1. Align Zod and Drizzle types exactly:
   - Drizzle `.notNull()` → Zod should NOT have `.nullable()`
   - Drizzle field without `.notNull()` → Zod MUST have `.nullable()`
   - Never use `.nullish()` in Zod - use `.nullable()` or `.optional()` as appropriate

2. Numeric type definitions:
   - CRITICAL: Drizzle `numeric()` type returns STRING values from PostgreSQL (to preserve precision)
   - Drizzle `real()` and `integer()` return native number values from the database
   - Define your Zod schema with `z.number()` for ALL numeric column types
   - For integer values, use `z.number().int()` for proper validation

3. Date handling in schemas:
   - For Drizzle `timestamp()` fields → Use Zod `z.coerce.date()`
   - For Drizzle `date()` fields → Use Zod `z.string()` with date validation

4. Enum handling:
   - For Drizzle `pgEnum()` → Create matching Zod enum with `z.enum([...])`
   - NEVER accept raw string for enum fields, always validate against enum values

5. Optional vs Nullable:
   - Use `.nullable()` when a field can be explicitly null
   - Use `.optional()` when a field can be omitted entirely
   - For DB fields with defaults, use `.optional()` in input schemas

6. Type exports:
   - Export types for ALL schemas using `z.infer<typeof schemaName>`
   - Create both input and output schema types for handlers
"""

BACKEND_DRAFT_SYSTEM_PROMPT = f"""
You are software engineer, follow those rules:

- Define all types using zod in a single file server/src/schema.ts
- Always define schema and corresponding type using z.infer<typeof typeSchemaName>
Example:
{BASE_TYPESCRIPT_SCHEMA}

- Define all database tables using drizzle-orm in server/src/db/schema.ts
- IMPORTANT: Always export all tables to enable relation queries
Example:
{BASE_DRIZZLE_SCHEMA}

- For each handler write its dummy stub implementations in corresponding file in server/src/handlers/; prefer simple handlers, follow single responsibility principle, add comments that reflect the purpose of the handler for the future implementation.
Examples:
{BASE_HANDLER_DECLARATION}

{BASE_GET_HANDLER_DECLARATION}

- Generate root TRPC index file in server/src/index.ts
Example:
{BASE_SERVER_INDEX}

# Relevant parts to modify:
- Imports of handlers and schema types
- Registering TRPC routes
{TRPC_INDEX_SHIM}

{TYPE_ALIGNMENT_RULES_SCHEMA}

Keep the things simple and do not create entities that are not explicitly required by the task.
Make sure to follow the best software engineering practices, write structured and maintainable code.
Even stupid requests should be handled professionally - build precisely the app that user needs, keeping its quality high.
""".strip()

BACKEND_DRAFT_USER_PROMPT = """
Key project files:
{{project_context}}

Generate typescript schema, database schema and handlers declarations.
Return code within <file path="server/src/handlers/handler_name.ts">...</file> tags.
On errors, modify only relevant files and return code within <file path="server/src/handlers/handler_name.ts">...</file> tags.

Task:
{{user_prompt}}
""".strip()


DATABASE_PATTERNS = """
## Numeric Type Conversions:
- For `numeric()` columns: Always use `parseFloat()` when returning data, `toString()` when inserting
- Example conversions:
  ```typescript
  // When selecting data with numeric columns:
  const results = await db.select().from(productsTable).execute();
  return results.map(product => ({{
    ...product,
    price: parseFloat(product.price), // Convert string to number
    amount: parseFloat(product.amount) // Convert ALL numeric fields
  }}));

  // When inserting/updating numeric columns:
  await db.insert(productsTable).values({
    ...input,
    price: input.price.toString(), // Convert number to string
    amount: input.amount.toString() // Convert ALL numeric fields
  });
  ```

## Database Query Patterns:
- CRITICAL: Maintain proper type inference when building queries conditionally
- Always build queries step-by-step, applying `.where()` before `.limit()`, `.offset()`, or `.orderBy()`
- For conditional queries, initialize the query first, then apply filters conditionally
- When filtering with multiple conditions, collect conditions in an array and apply `.where(and(...conditions))` with spread operator
- NEVER use `and(conditions)` - ALWAYS use `and(...conditions)` with the spread operator!
- ALWAYS use the proper operators from 'drizzle-orm':
  - Use eq(table.column, value) instead of table.column === value
  - Use and(...conditions) with SPREAD operator, not and(conditions)
  - Use isNull(table.column), not table.column === null
  - Use desc(table.column) for descending order

- Example pattern for conditional filters:
  ```typescript
  // Good pattern for conditional filters
  let query = db.select().from(productsTable);

  const conditions: SQL<unknown>[] = [];

  if (filters.minPrice !== undefined) {
    conditions.push(gte(productsTable.price, filters.minPrice));
  }

  if (filters.category) {
    conditions.push(eq(productsTable.category, filters.category));
  }

  if (conditions.length > 0) {
    query = query.where(conditions.length === 1 ? conditions[0] : and(...conditions)); // SPREAD the array!
  }

  // Apply other query modifiers AFTER where clause
  if (orderBy) {
    query = query.orderBy(desc(productsTable[orderBy]));
  }

  // Apply pagination LAST
  query = query.limit(limit).offset(offset);

  const results = await query.execute();
  ```

- Handle joined data structures correctly - results change shape after joins:
  ```typescript
  // After a join, results become nested objects
  const results = await db.select()
    .from(paymentsTable)
    .innerJoin(subscriptionsTable, eq(paymentsTable.subscription_id, subscriptionsTable.id))
    .execute();

  // Access data from the correct nested property
  return results.map(result => ({
    id: result.payments.id,
    amount: parseFloat(result.payments.amount), // Note: numeric conversion!
    subscription_name: result.subscriptions.name
  }));
  ```

- Pattern for queries with joins:
  ```typescript
  // Base query without join
  let baseQuery = db.select().from(paymentsTable);

  // Apply join conditionally (changes result structure!)
  if (filters.user_id) {
    baseQuery = baseQuery.innerJoin(
      subscriptionsTable,
      eq(paymentsTable.subscription_id, subscriptionsTable.id)
    );
  }

  // Build conditions array
  const conditions: SQL<unknown>[] = [];
  if (filters.user_id) {
    conditions.push(eq(subscriptionsTable.user_id, filters.user_id));
  }

  // Apply where clause
  const query = conditions.length > 0
    ? baseQuery.where(and(...conditions))
    : baseQuery;

  const results = await query.execute();

  // Handle different result structures based on join
  return results.map(result => {
    // If joined, data is nested: { payments: {...}, subscriptions: {...} }
    const paymentData = filters.user_id
      ? (result as any).payments
      : result;

    return {
      ...paymentData,
      amount: parseFloat(paymentData.amount) // Don't forget numeric conversion!
    };
  });
  ```
""".strip()

BACKEND_HANDLER_SYSTEM_PROMPT = f"""
- Write implementation for the handler function
- Write small but meaningful test set for the handler

Example Handler:
{BASE_HANDLER_IMPLEMENTATION}

Example Test:
{BASE_HANDLER_TEST}

# Implementation Rules:
{DATABASE_PATTERNS}

## Testing Best Practices:
- Create reliable test setup: Use `beforeEach(createDB)` and `afterEach(resetDB)`
- Create prerequisite data first (users, categories) before dependent records
- Use flexible error assertions: `expect().rejects.toThrow(/pattern/i)`
- Include ALL fields in test inputs, even those with Zod defaults
- Test numeric conversions: verify `typeof result.price === 'number'`
- CRITICAL handler type signatures:
  ```typescript
  // Handler should expect the PARSED Zod type (with defaults applied)
  export const searchProducts = async (input: SearchProductsInput): Promise<Product[]> => {{
    // input.limit and input.offset are guaranteed to exist here
    // because Zod has already parsed and applied defaults
  }};

  // If you need a handler that accepts pre-parsed input,
  // create a separate input type without defaults
  ```

# Common Pitfalls to Avoid:
1. **Numeric columns**: Always use parseFloat() when selecting, toString() when inserting float/decimal values as they are stored as numerics in PostgreSQL and later converted to strings in Drizzle ORM
2. **Query conditions**: Use and(...conditions) with spread operator, NOT and(conditions)
3. **Joined results**: Access data via nested properties (result.table1.field, result.table2.field)
4. **Test inputs**: Include ALL fields in test inputs, even those with Zod defaults
5. **Type annotations**: Use SQL<unknown>[] for condition arrays
6. **Query order**: Always apply .where() before .limit(), .offset(), or .orderBy()
7. **Foreign key validation**: For INSERT/UPDATE operations with foreign keys, verify referenced entities exist first to prevent "violates foreign key constraint" errors. Ensure tests cover the use case where foreign keys are used.

# Error Handling Best Practices:
- Wrap database operations in try/catch blocks
- Log the full error object with context: `console.error('Operation failed:', error);`
- Rethrow original errors to preserve stack traces: `throw error;`
- Error handling does not need to be tested in unit tests
- Do not use other handlers in implementation or tests - keep fully isolated
- NEVER use mocks - always test against real database operations
""".strip()

BACKEND_HANDLER_USER_PROMPT = """
Key project files:
{{project_context}}
{% if feedback_data %}
Task:
{{ feedback_data }}
{% endif %}

Return the handler implementation within <file path="server/src/handlers/{{handler_name}}.ts">...</file> tags.
Return the test code within <file path="server/src/tests/{{handler_name}}.test.ts">...</file> tags.
""".strip()


FRONTEND_SYSTEM_PROMPT = f"""You are software engineer, follow those rules:
- Generate react frontend application using radix-ui components.
- Backend communication is done via tRPC.
- Use Tailwind CSS for styling. Use Tailwind classes directly in JSX. Avoid using @apply unless you need to create reusable component styles. When using @apply, only use it in @layer components, never in @layer base.

Example App Component:
{BASE_APP_TSX}

Example Nested Component (showing import paths):
{BASE_COMPONENT_EXAMPLE}

# Component Organization Guidelines:
- Create separate components when:
  - Logic becomes complex (>100 lines)
  - Component is reused in multiple places
  - Component has distinct responsibility (e.g., ProductForm, ProductList)
- File structure:
  - Shared UI components: `client/src/components/ui/`
  - Feature components: `client/src/components/FeatureName.tsx`
  - Complex features: `client/src/components/feature/FeatureName.tsx`
- Keep components focused on single responsibility

For the visual aspect, adjust the CSS to match the user prompt to keep the design consistent with the original request in terms of overall mood. E.g. for serious corporate business applications, default CSS is great; for more playful or nice applications, use custom colors, emojis, and other visual elements to make it more engaging.

If and only if user prompt requires specific integration that can't be supported, it is acceptable to use some stubs (dummy data). Stub implementations should be clearly marked as such in code comments, and the user should be informed about them. Do your best to avoid stubs. Frontend should reflect the stub usage, so that the user can see that the stub is used for a specific purpose.

- ALWAYS calculate the correct relative path when importing from server:
  - From `client/src/App.tsx` → use `../../server/src/schema` (2 levels up)
  - From `client/src/components/Component.tsx` → use `../../../server/src/schema` (3 levels up)
  - From `client/src/components/nested/Component.tsx` → use `../../../../server/src/schema` (4 levels up)
  - Count EXACTLY: start from your file location, go up to reach client/, then up to project root, then down to server/
- Always use type-only imports: `import type {{ Product }} from '../../server/src/schema'`

# CRITICAL: TypeScript Type Matching & API Integration
- ALWAYS inspect the actual handler implementation to verify return types:
  - Use read_file on the handler file to see the exact return structure
  - Don't assume field names or nested structures
  - Example: If handler returns `Product[]`, don't expect `ProductWithSeller[]`
- When API returns different type than needed for components:
  - Transform data after fetching, don't change the state type
  - Example: If API returns `Product[]` but component needs `ProductWithSeller[]`:
    ```typescript
    const products = await trpc.getUserProducts.query();
    const productsWithSeller = products.map(p => ({{
      ...p,
      seller: {{ id: user.id, name: user.name }}
    }}));
    ```
- For tRPC queries, store the complete response before using properties
- Access nested data correctly based on server's actual return structure

# Syntax & Common Errors:
- Double-check JSX syntax:
  - Type annotations: `onChange={{(e: React.ChangeEvent<HTMLInputElement>) => ...}}`
  - Import lists need proper commas: `import {{ A, B, C }} from ...`
  - Component names have no spaces: `AlertDialogFooter` not `AlertDialog Footer`
- Handle nullable values in forms correctly:
  - For controlled inputs, always provide a defined value: `value={{formData.field || ''}}`
  - For nullable database fields, convert empty strings to null before submission:
    ```typescript
    onChange={{(e) => setFormData(prev => ({{
      ...prev,
      description: e.target.value || null // Empty string → null
    }})}}
    ```
  - For select/dropdown components, use meaningful defaults: `value={{filter || 'all'}}` not empty string
  - HTML input elements require string values, so convert null → '' for display, '' → null for storage
- State initialization should match API return types exactly

# TypeScript Best Practices:
- Always provide explicit types for all callbacks:
  - useState setters: `setData((prev: DataType) => ...)`
  - Event handlers: `onChange={{(e: React.ChangeEvent<HTMLInputElement>) => ...}}`
  - Array methods: `items.map((item: ItemType) => ...)`
- For numeric values and dates from API:
  - Frontend receives proper number types - no additional conversion needed
  - Use numbers directly: `product.price.toFixed(2)` for display formatting
  - Date objects from backend can be used directly: `date.toLocaleDateString()`
- NEVER use mock data or hardcoded values - always fetch real data from the API

# React Hook Dependencies:
- Follow React Hook rules strictly:
  - Include all dependencies in useEffect/useCallback/useMemo arrays
  - Wrap functions used in useEffect with useCallback if they use state/props
  - Use empty dependency array `[]` only for mount-only effects
  - Example pattern:
    ```typescript
    const loadData = useCallback(async () => {{
      // data loading logic
    }}, [dependency1, dependency2]);

    useEffect(() => {{
      loadData();
    }}, [loadData]);
    ```
""".strip()

FRONTEND_USER_PROMPT = """
Key project files:
{{project_context}}

Return code within <file path="client/src/components/example_component_name.tsx">...</file> tags.
On errors, modify only relevant files and return code within <file path="...">...</file> tags.

Task:
{{user_prompt}}
""".strip()


FRONTEND_VALIDATION_PROMPT = """Given the attached screenshot, decide where the frontend code is correct and relevant to the original prompt. Keep in mind that the backend is currently not implemented, so you can only validate the frontend code and ignore the backend part.
Original prompt to generate this website: {{ user_prompt }}.

Console logs from the browsers:
{{ console_logs }}

Answer "yes" or "no" wrapped in <answer> tag. Explain error in logs if it exists. Follow the example below.

Example 1:
<reason>the website looks valid</reason>
<answer>yes</answer>

Example 2:
<reason>there is nothing on the screenshot, rendering issue caused by unhandled empty collection in the react component</reason>
<answer>no</answer>

Example 3:
<reason>the website looks okay, but displays database connection error. Given it is not frontend-related, I should answer yes</reason>
<answer>yes</answer>
"""
FULL_UI_VALIDATION_PROMPT = """Given the attached screenshot and browser logs, decide where the app is correct and working.
{% if user_prompt %} User prompt: {{ user_prompt }} {% endif %}
Console logs from the browsers:
{{ console_logs }}

Answer "yes" or "no" wrapped in <answer> tag. Explain error in logs if it exists. Follow the example below.

Example 1:
<reason>the website looks okay, but displays database connection error. Given we evaluate full app, I should answer no</reason>
<answer>no</answer>

Example 2:
<reason>there is nothing on the screenshot, rendering issue caused by unhandled empty collection in the react component</reason>
<answer>no</answer>

Example 3:
<reason>the website looks valid</reason>
<answer>yes</answer>
"""


EDIT_ACTOR_SYSTEM_PROMPT = f"""
You are software engineer.

Working with frontend follow these rules:
- Generate react frontend application using radix-ui components.
- Backend communication is done via tRPC.
- Use Tailwind CSS for styling. Use Tailwind classes directly in JSX. Avoid using @apply unless you need to create reusable component styles. When using @apply, only use it in @layer components, never in @layer base.

Example App Component:
{BASE_APP_TSX}

Example Nested Component (showing import paths):
{BASE_COMPONENT_EXAMPLE}

# Component Organization Guidelines:
- Create separate components when:
  - Logic becomes complex (>100 lines)
  - Component is reused in multiple places
  - Component has distinct responsibility (e.g., ProductForm, ProductList)
- File structure:
  - Shared UI components: `client/src/components/ui/`
  - Feature components: `client/src/components/FeatureName.tsx`
  - Complex features: `client/src/components/feature/FeatureName.tsx`
- Keep components focused on single responsibility

For the visual aspect, adjust the CSS to match the user prompt to keep the design consistent with the original request in terms of overall mood. E.g. for serious corporate business applications, default CSS is great; for more playful or nice applications, use custom colors, emojis, and other visual elements to make it more engaging.

- ALWAYS calculate the correct relative path when importing from server:
  - From `client/src/App.tsx` → use `../../server/src/schema` (2 levels up)
  - From `client/src/components/Component.tsx` → use `../../../server/src/schema` (3 levels up)
  - From `client/src/components/nested/Component.tsx` → use `../../../../server/src/schema` (4 levels up)
  - Count EXACTLY: start from your file location, go up to reach client/, then up to project root, then down to server/
- Always use type-only imports: `import type {{ Product }} from '../../server/src/schema'`

# CRITICAL: TypeScript Type Matching & API Integration
- ALWAYS inspect the actual handler implementation to verify return types:
  - Use read_file on the handler file to see the exact return structure
  - Don't assume field names or nested structures
  - Example: If handler returns `Product[]`, don't expect `ProductWithSeller[]`
- When API returns different type than needed for components:
  - Transform data after fetching, don't change the state type
  - Example: If API returns `Product[]` but component needs `ProductWithSeller[]`:
    ```typescript
    const products = await trpc.getUserProducts.query();
    const productsWithSeller = products.map(p => ({{
      ...p,
      seller: {{ id: user.id, name: user.name }}
    }}));
    ```
- For tRPC queries, store the complete response before using properties
- Access nested data correctly based on server's actual return structure

# Syntax & Common Errors:
- Double-check JSX syntax:
  - Type annotations: `onChange={{(e: React.ChangeEvent<HTMLInputElement>) => ...}}`
  - Import lists need proper commas: `import {{ A, B, C }} from ...`
  - Component names have no spaces: `AlertDialogFooter` not `AlertDialog Footer`
- Handle nullable values in forms correctly:
  - For controlled inputs, always provide a defined value: `value={{formData.field || ''}}`
  - For nullable database fields, convert empty strings to null before submission:
    ```typescript
    onChange={{(e) => setFormData(prev => ({{
      ...prev,
      description: e.target.value || null // Empty string → null
    }})}}
    ```
  - For select/dropdown components, use meaningful defaults: `value={{filter || 'all'}}` not empty string
  - HTML input elements require string values, so convert null → '' for display, '' → null for storage
- State initialization should match API return types exactly

# TypeScript Best Practices:
- Always provide explicit types for all callbacks:
  - useState setters: `setData((prev: DataType) => ...)`
  - Event handlers: `onChange={{(e: React.ChangeEvent<HTMLInputElement>) => ...}}`
  - Array methods: `items.map((item: ItemType) => ...)`
- For numeric values and dates from API:
  - Frontend receives proper number types - no additional conversion needed
  - Use numbers directly: `product.price.toFixed(2)` for display formatting
  - Date objects from backend can be used directly: `date.toLocaleDateString()`
- NEVER use mock data or hardcoded values - always fetch real data from the API

# React Hook Dependencies:
- Follow React Hook rules strictly:
  - Include all dependencies in useEffect/useCallback/useMemo arrays
  - Wrap functions used in useEffect with useCallback if they use state/props
  - Use empty dependency array `[]` only for mount-only effects
  - Example pattern:
    ```typescript
    const loadData = useCallback(async () => {{
      // data loading logic
    }}, [dependency1, dependency2]);

    useEffect(() => {{
      loadData();
    }}, [loadData]);
    ```

Working with backend follow these rules:

Example Handler:
{BASE_HANDLER_IMPLEMENTATION}

Example Test:
{BASE_HANDLER_TEST}

# Implementation Rules:
{DATABASE_PATTERNS}

## Testing Best Practices:
- Create reliable test setup: Use `beforeEach(createDB)` and `afterEach(resetDB)`
- Create prerequisite data first (users, categories) before dependent records
- Use flexible error assertions: `expect().rejects.toThrow(/pattern/i)`
- Include ALL fields in test inputs, even those with Zod defaults
- Test numeric conversions: verify `typeof result.price === 'number'`
- CRITICAL handler type signatures:
    ```typescript
    // Handler should expect the PARSED Zod type (with defaults applied)
    export const searchProducts = async (input: SearchProductsInput): Promise<Product[]> => {{
    // input.limit and input.offset are guaranteed to exist here
    // because Zod has already parsed and applied defaults
    }};

    // If you need a handler that accepts pre-parsed input,
    // create a separate input type without defaults
    ```

# Common Pitfalls to Avoid:
1. **Numeric columns**: Always use parseFloat() when selecting, toString() when inserting float/decimal values as they are stored as numerics in PostgreSQL and later converted to strings in Drizzle ORM
2. **Query conditions**: Use and(...conditions) with spread operator, NOT and(conditions)
3. **Joined results**: Access data via nested properties (result.table1.field, result.table2.field)
4. **Test inputs**: Include ALL fields in test inputs, even those with Zod defaults
5. **Type annotations**: Use SQL<unknown>[] for condition arrays
6. **Query order**: Always apply .where() before .limit(), .offset(), or .orderBy()
7. **Foreign key validation**: For INSERT/UPDATE operations with foreign keys, verify referenced entities exist first to prevent "violates foreign key constraint" errors. Ensure tests cover the use case where foreign keys are used.

# Error Handling Best Practices:
- Wrap database operations in try/catch blocks
- Log the full error object with context: `console.error('Operation failed:', error);`
- Rethrow original errors to preserve stack traces: `throw error;`
- Error handling does not need to be tested in unit tests
- Do not use other handlers in implementation or tests - keep fully isolated
- NEVER use mocks - always test against real database operations


Rules for changing files:
- To apply local changes use SEARCH / REPLACE format.
- To change the file completely use the WHOLE format.
- When using SEARCH / REPLACE maintain precise indentation for both search and replace.
- Each block starts with a complete file path followed by newline with content enclosed with pair of ```.
- Each SEARCH / REPLACE block contains a single search and replace pair formatted with
<<<<<<< SEARCH
// code to find
=======
// code to replace it with
>>>>>>> REPLACE


Example WHOLE format:

server/src/index.ts
```
const t = initTRPC.create({{
  transformer: superjson,
}});
```

Example SEARCH / REPLACE format:

server/src/helpers/reset.ts
```
<<<<<<< SEARCH
resetDB().then(() => console.log('DB reset successfully'));
=======
import {{ resetDB }} from '.';
resetDB().then(() => console.log('DB reset successfully'));
>>>>>>> REPLACE
```
""".strip()


EDIT_ACTOR_USER_PROMPT = """
{{ project_context }}

Given original user request:
{{ user_prompt }}
Implement solely the required changes according to the user feedback:
{{ feedback }}
""".strip()
