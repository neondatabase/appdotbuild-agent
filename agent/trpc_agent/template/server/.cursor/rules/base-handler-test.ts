import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { resetDB, createDB } from '../helpers';
import { db } from '../db';
import { entitiesTable } from '../db/schema';
import { eq, gte, between, and } from 'drizzle-orm';
import { type CreateEntityInput, type UpdateEntityInput, type SearchEntityInput } from '../schema';
import { createEntity, getEntity, searchEntities, updateEntity, deleteEntity } from '../handlers/create_entity';

// Test input data
const testInput: CreateEntityInput = {
  name: 'Test Entity',
  description: 'A test entity for testing',
  value: 19.99,
  quantity: 100
};

const testInputWithNullDescription: CreateEntityInput = {
  name: 'Test Entity Null Desc',
  description: null,
  value: 25.50,
  quantity: 50
};

describe('createEntity', () => {
  beforeEach(createDB);
  afterEach(resetDB);

  it('should create an entity with all fields', async () => {
    const result = await createEntity(testInput);

    // Basic field validation
    expect(result.name).toEqual('Test Entity');
    expect(result.description).toEqual(testInput.description);
    expect(result.value).toEqual(19.99);
    expect(result.quantity).toEqual(100);
    expect(result.id).toBeDefined();
    expect(result.created_at).toBeInstanceOf(Date);
    expect(typeof result.value).toBe('number'); // Verify numeric conversion
  });

  it('should create an entity with null description', async () => {
    const result = await createEntity(testInputWithNullDescription);

    expect(result.name).toEqual('Test Entity Null Desc');
    expect(result.description).toBeNull();
    expect(result.value).toEqual(25.50);
    expect(result.quantity).toEqual(50);
  });

  it('should save entity to database correctly', async () => {
    const result = await createEntity(testInput);

    // Query database directly to verify storage
    const entities = await db.select()
      .from(entitiesTable)
      .where(eq(entitiesTable.id, result.id))
      .execute();

    expect(entities).toHaveLength(1);
    expect(entities[0].name).toEqual('Test Entity');
    expect(entities[0].description).toEqual(testInput.description);
    expect(parseFloat(entities[0].value)).toEqual(19.99); // DB stores as string
    expect(entities[0].quantity).toEqual(100);
    expect(entities[0].created_at).toBeInstanceOf(Date);
  });
});

describe('getEntity', () => {
  beforeEach(createDB);
  afterEach(resetDB);

  it('should retrieve an existing entity', async () => {
    const created = await createEntity(testInput);
    const result = await getEntity(created.id);

    expect(result).not.toBeNull();
    expect(result!.id).toEqual(created.id);
    expect(result!.name).toEqual('Test Entity');
    expect(result!.value).toEqual(19.99);
    expect(typeof result!.value).toBe('number');
  });

  it('should return null for non-existent entity', async () => {
    const result = await getEntity(999);
    expect(result).toBeNull();
  });
});

describe('searchEntities', () => {
  beforeEach(createDB);
  afterEach(resetDB);

  it('should search entities with default parameters', async () => {
    await createEntity(testInput);
    await createEntity(testInputWithNullDescription);

    const searchInput: SearchEntityInput = {};
    const results = await searchEntities(searchInput);

    expect(results.length).toBeGreaterThan(0);
    results.forEach(entity => {
      expect(entity.id).toBeDefined();
      expect(typeof entity.value).toBe('number');
      expect(entity.created_at).toBeInstanceOf(Date);
    });
  });

  it('should apply pagination correctly', async () => {
    // Create multiple entities
    for (let i = 0; i < 5; i++) {
      await createEntity({
        ...testInput,
        name: `Entity ${i}`
      });
    }

    const searchInput: SearchEntityInput = {
      limit: 2,
      offset: 1
    };
    const results = await searchEntities(searchInput);

    expect(results).toHaveLength(2);
  });

  it('should handle date range queries correctly', async () => {
    await createEntity(testInput);

    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    // Test date filtering capability
    const entities = await db.select()
      .from(entitiesTable)
      .where(
        and(
          gte(entitiesTable.created_at, today),
          between(entitiesTable.created_at, today, tomorrow)
        )
      )
      .execute();

    expect(entities.length).toBeGreaterThan(0);
    entities.forEach(entity => {
      expect(entity.created_at).toBeInstanceOf(Date);
      expect(entity.created_at >= today).toBe(true);
      expect(entity.created_at <= tomorrow).toBe(true);
    });
  });
});

describe('updateEntity', () => {
  beforeEach(createDB);
  afterEach(resetDB);

  it('should update entity fields', async () => {
    const created = await createEntity(testInput);
    
    const updateInput: UpdateEntityInput = {
      id: created.id,
      name: 'Updated Entity',
      value: 29.99
    };

    const result = await updateEntity(updateInput);

    expect(result.id).toEqual(created.id);
    expect(result.name).toEqual('Updated Entity');
    expect(result.value).toEqual(29.99);
    expect(result.description).toEqual(testInput.description); // Unchanged
  });

  it('should handle partial updates', async () => {
    const created = await createEntity(testInput);
    
    const updateInput: UpdateEntityInput = {
      id: created.id,
      description: null
    };

    const result = await updateEntity(updateInput);

    expect(result.id).toEqual(created.id);
    expect(result.name).toEqual(testInput.name); // Unchanged
    expect(result.description).toBeNull(); // Updated
  });

  it('should throw error for non-existent entity', async () => {
    const updateInput: UpdateEntityInput = {
      id: 999,
      name: 'Non-existent'
    };

    await expect(updateEntity(updateInput)).rejects.toThrow(/not found/i);
  });
});

describe('deleteEntity', () => {
  beforeEach(createDB);
  afterEach(resetDB);

  it('should delete an entity', async () => {
    const created = await createEntity(testInput);
    
    await deleteEntity(created.id);

    const result = await getEntity(created.id);
    expect(result).toBeNull();
  });

  it('should not throw error when deleting non-existent entity', async () => {
    await expect(deleteEntity(999)).resolves.not.toThrow();
  });
});