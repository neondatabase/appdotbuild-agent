import { db } from '../db';
import { entitiesTable } from '../db/schema';
import { eq, and, gte, desc, SQL } from 'drizzle-orm';
import { type CreateEntityInput, type Entity, type SearchEntityInput } from '../schema';

export const createEntity = async (input: CreateEntityInput): Promise<Entity> => {
  try {
    // Insert entity record
    const result = await db.insert(entitiesTable)
      .values({
        name: input.name,
        description: input.description,
        value: input.value.toString(), // Convert number to string for numeric column
        quantity: input.quantity // Integer column - no conversion needed
      })
      .returning()
      .execute();

    // Convert numeric fields back to numbers before returning
    const entity = result[0];
    return {
      ...entity,
      value: parseFloat(entity.value) // Convert string back to number
    };
  } catch (error) {
    console.error('Entity creation failed:', error);
    throw error;
  }
};

export const getEntity = async (id: number): Promise<Entity | null> => {
  try {
    const result = await db.select()
      .from(entitiesTable)
      .where(eq(entitiesTable.id, id))
      .execute();

    if (result.length === 0) {
      return null;
    }

    const entity = result[0];
    return {
      ...entity,
      value: parseFloat(entity.value) // Convert numeric field
    };
  } catch (error) {
    console.error('Entity retrieval failed:', error);
    throw error;
  }
};

export const searchEntities = async (input: SearchEntityInput): Promise<Entity[]> => {
  try {
    // Build query step by step
    let query = db.select().from(entitiesTable);

    // Build conditions array
    const conditions: SQL<unknown>[] = [];

    if (input.query) {
      conditions.push(gte(entitiesTable.name, input.query));
    }

    // Apply where clause if conditions exist
    if (conditions.length > 0) {
      query = query.where(conditions.length === 1 ? conditions[0] : and(...conditions)); // SPREAD the array
    }

    // Apply ordering
    if (input.sortBy === 'name') {
      query = query.orderBy(input.sortOrder === 'desc' ? desc(entitiesTable.name) : entitiesTable.name);
    } else if (input.sortBy === 'value') {
      query = query.orderBy(input.sortOrder === 'desc' ? desc(entitiesTable.value) : entitiesTable.value);
    } else {
      query = query.orderBy(input.sortOrder === 'desc' ? desc(entitiesTable.created_at) : entitiesTable.created_at);
    }

    // Apply pagination LAST
    query = query.limit(input.limit).offset(input.offset);

    const results = await query.execute();

    // Convert numeric fields back to numbers
    return results.map(entity => ({
      ...entity,
      value: parseFloat(entity.value)
    }));
  } catch (error) {
    console.error('Entity search failed:', error);
    throw error;
  }
};

export const updateEntity = async (input: UpdateEntityInput): Promise<Entity> => {
  try {
    // Build update object, converting numeric fields
    const updateData: any = {};
    
    if (input.name !== undefined) updateData.name = input.name;
    if (input.description !== undefined) updateData.description = input.description;
    if (input.value !== undefined) updateData.value = input.value.toString();
    if (input.quantity !== undefined) updateData.quantity = input.quantity;

    const result = await db.update(entitiesTable)
      .set(updateData)
      .where(eq(entitiesTable.id, input.id))
      .returning()
      .execute();

    if (result.length === 0) {
      throw new Error('Entity not found');
    }

    const entity = result[0];
    return {
      ...entity,
      value: parseFloat(entity.value)
    };
  } catch (error) {
    console.error('Entity update failed:', error);
    throw error;
  }
};

export const deleteEntity = async (id: number): Promise<void> => {
  try {
    await db.delete(entitiesTable)
      .where(eq(entitiesTable.id, id))
      .execute();
  } catch (error) {
    console.error('Entity deletion failed:', error);
    throw error;
  }
};