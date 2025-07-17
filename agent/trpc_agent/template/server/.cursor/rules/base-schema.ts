import { z } from 'zod';

// Entity schema with proper type handling
export const entitySchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string().nullable(), // Nullable field (can be explicitly null)
  value: z.number(), // Numeric field
  quantity: z.number().int(), // Integer validation
  created_at: z.coerce.date() // Auto-converts string timestamps to Date
});

export type Entity = z.infer<typeof entitySchema>;

// Input schema for creating entities
export const createEntityInputSchema = z.object({
  name: z.string(),
  description: z.string().nullable(), // Explicit null allowed
  value: z.number().positive(), // Validate positive numbers
  quantity: z.number().int().nonnegative() // Non-negative integers
});

export type CreateEntityInput = z.infer<typeof createEntityInputSchema>;

// Input schema for updating entities
export const updateEntityInputSchema = z.object({
  id: z.number(),
  name: z.string().optional(), // Optional = can be omitted
  description: z.string().nullable().optional(), // Can be null or undefined
  value: z.number().positive().optional(),
  quantity: z.number().int().nonnegative().optional()
});

export type UpdateEntityInput = z.infer<typeof updateEntityInputSchema>;

// Search/filter input schema with defaults
export const searchEntityInputSchema = z.object({
  query: z.string().optional(),
  limit: z.number().int().positive().default(10),
  offset: z.number().int().nonnegative().default(0),
  sortBy: z.enum(['name', 'created_at', 'value']).default('created_at'),
  sortOrder: z.enum(['asc', 'desc']).default('desc')
});

export type SearchEntityInput = z.infer<typeof searchEntityInputSchema>;