import { serial, text, pgTable, timestamp, numeric, integer } from 'drizzle-orm/pg-core';

export const entitiesTable = pgTable('entities', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  description: text('description'), // Nullable by default, matches Zod schema
  value: numeric('value', { precision: 10, scale: 2 }).notNull(), // Use numeric for monetary values
  quantity: integer('quantity').notNull(), // Use integer for whole numbers
  created_at: timestamp('created_at').defaultNow().notNull(),
});

// Example of a related table with foreign key
export const entityItemsTable = pgTable('entity_items', {
  id: serial('id').primaryKey(),
  entity_id: integer('entity_id').notNull().references(() => entitiesTable.id),
  item_name: text('item_name').notNull(),
  item_value: numeric('item_value', { precision: 8, scale: 2 }).notNull(),
  created_at: timestamp('created_at').defaultNow().notNull(),
});

// TypeScript types for the table schemas
export type Entity = typeof entitiesTable.$inferSelect; // For SELECT operations
export type NewEntity = typeof entitiesTable.$inferInsert; // For INSERT operations

export type EntityItem = typeof entityItemsTable.$inferSelect;
export type NewEntityItem = typeof entityItemsTable.$inferInsert;

// Important: Export all tables and relations for proper query building
export const tables = { 
  entities: entitiesTable,
  entityItems: entityItemsTable
};