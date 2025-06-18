import { trpc } from '@/utils/trpc';
import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { Entity, CreateEntityInput, SearchEntityInput } from '../../../server/src/schema';

export default function BaseTRPCUsage() {
  // State management with proper typing
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Search filters
  const [searchFilters, setSearchFilters] = useState<SearchEntityInput>({
    limit: 10,
    offset: 0,
    sortBy: 'created_at',
    sortOrder: 'desc'
  });

  // Form data
  const [formData, setFormData] = useState<CreateEntityInput>({
    name: '',
    description: null,
    value: 0,
    quantity: 0
  });

  // Load entities using tRPC query
  const loadEntities = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      
      // Using tRPC query for read operations
      const result = await trpc.searchEntities.query(searchFilters);
      setEntities(result);
      
    } catch (err) {
      console.error('Failed to load entities:', err);
      setError(err instanceof Error ? err.message : 'Failed to load entities');
    } finally {
      setIsLoading(false);
    }
  }, [searchFilters]);

  // Load single entity
  const loadEntity = useCallback(async (id: number) => {
    try {
      setError(null);
      
      // Using tRPC query with parameters
      const entity = await trpc.getEntity.query({ id });
      setSelectedEntity(entity);
      
    } catch (err) {
      console.error('Failed to load entity:', err);
      setError(err instanceof Error ? err.message : 'Failed to load entity');
    }
  }, []);

  // Create entity using tRPC mutation
  const createEntity = async (e: React.FormEvent) => {
    e.preventDefault();
    
    try {
      setIsCreating(true);
      setError(null);
      
      // Using tRPC mutation for write operations
      const newEntity = await trpc.createEntity.mutate(formData);
      
      // Update local state optimistically
      setEntities((prev: Entity[]) => [newEntity, ...prev]);
      
      // Reset form
      setFormData({
        name: '',
        description: null,
        value: 0,
        quantity: 0
      });
      
    } catch (err) {
      console.error('Failed to create entity:', err);
      setError(err instanceof Error ? err.message : 'Failed to create entity');
    } finally {
      setIsCreating(false);
    }
  };

  // Update entity
  const updateEntity = async (id: number, updates: Partial<CreateEntityInput>) => {
    try {
      setError(null);
      
      // Using tRPC mutation for updates
      const updatedEntity = await trpc.updateEntity.mutate({
        id,
        ...updates
      });
      
      // Update local state
      setEntities((prev: Entity[]) =>
        prev.map((entity: Entity) =>
          entity.id === id ? updatedEntity : entity
        )
      );
      
      // Update selected entity if it's the one being updated
      if (selectedEntity?.id === id) {
        setSelectedEntity(updatedEntity);
      }
      
    } catch (err) {
      console.error('Failed to update entity:', err);
      setError(err instanceof Error ? err.message : 'Failed to update entity');
    }
  };

  // Delete entity
  const deleteEntity = async (id: number) => {
    try {
      setError(null);
      
      // Using tRPC mutation for deletion
      await trpc.deleteEntity.mutate({ id });
      
      // Update local state
      setEntities((prev: Entity[]) =>
        prev.filter((entity: Entity) => entity.id !== id)
      );
      
      // Clear selected entity if it was deleted
      if (selectedEntity?.id === id) {
        setSelectedEntity(null);
      }
      
    } catch (err) {
      console.error('Failed to delete entity:', err);
      setError(err instanceof Error ? err.message : 'Failed to delete entity');
    }
  };

  // Health check example
  const checkHealth = async () => {
    try {
      const result = await trpc.healthcheck.query();
      console.log('Server health:', result);
    } catch (err) {
      console.error('Health check failed:', err);
    }
  };

  // Load data on component mount
  useEffect(() => {
    loadEntities();
  }, [loadEntities]);

  // Update search results when filters change
  useEffect(() => {
    loadEntities();
  }, [searchFilters, loadEntities]);

  return (
    <div className="container mx-auto p-4 space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold">tRPC Usage Example</h1>
        <Button onClick={checkHealth} variant="outline">
          Check Server Health
        </Button>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          <p>{error}</p>
        </div>
      )}

      {/* Search Filters */}
      <div className="bg-gray-50 p-4 rounded-lg space-y-4">
        <h2 className="text-lg font-semibold">Search Filters</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Input
            placeholder="Search query"
            value={searchFilters.query || ''}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setSearchFilters((prev: SearchEntityInput) => ({
                ...prev,
                query: e.target.value || undefined
              }))
            }
          />
          <select
            className="px-3 py-2 border rounded-md"
            value={searchFilters.sortBy}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
              setSearchFilters((prev: SearchEntityInput) => ({
                ...prev,
                sortBy: e.target.value as 'name' | 'created_at' | 'value'
              }))
            }
          >
            <option value="created_at">Created Date</option>
            <option value="name">Name</option>
            <option value="value">Value</option>
          </select>
          <select
            className="px-3 py-2 border rounded-md"
            value={searchFilters.sortOrder}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
              setSearchFilters((prev: SearchEntityInput) => ({
                ...prev,
                sortOrder: e.target.value as 'asc' | 'desc'
              }))
            }
          >
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
          <Input
            type="number"
            placeholder="Limit"
            value={searchFilters.limit}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setSearchFilters((prev: SearchEntityInput) => ({
                ...prev,
                limit: parseInt(e.target.value) || 10
              }))
            }
            min="1"
            max="100"
          />
        </div>
      </div>

      {/* Create Form */}
      <form onSubmit={createEntity} className="bg-white p-4 border rounded-lg space-y-4">
        <h2 className="text-lg font-semibold">Create New Entity</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input
            placeholder="Name"
            value={formData.name}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setFormData((prev: CreateEntityInput) => ({
                ...prev,
                name: e.target.value
              }))
            }
            required
          />
          <Input
            placeholder="Description (optional)"
            value={formData.description || ''}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setFormData((prev: CreateEntityInput) => ({
                ...prev,
                description: e.target.value || null
              }))
            }
          />
          <Input
            type="number"
            placeholder="Value"
            value={formData.value}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setFormData((prev: CreateEntityInput) => ({
                ...prev,
                value: parseFloat(e.target.value) || 0
              }))
            }
            step="0.01"
            min="0"
            required
          />
          <Input
            type="number"
            placeholder="Quantity"
            value={formData.quantity}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
              setFormData((prev: CreateEntityInput) => ({
                ...prev,
                quantity: parseInt(e.target.value) || 0
              }))
            }
            min="0"
            required
          />
        </div>
        <Button type="submit" disabled={isCreating}>
          {isCreating ? 'Creating...' : 'Create Entity'}
        </Button>
      </form>

      {/* Entities List */}
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold">Entities</h2>
          <Button onClick={loadEntities} variant="outline" disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>
        </div>

        {isLoading ? (
          <div className="text-center py-8">
            <p className="text-gray-500">Loading entities...</p>
          </div>
        ) : entities.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-gray-500">No entities found.</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {entities.map((entity: Entity) => (
              <div
                key={entity.id}
                className="border rounded-lg p-4 space-y-2 hover:bg-gray-50 cursor-pointer"
                onClick={() => loadEntity(entity.id)}
              >
                <div className="flex justify-between items-start">
                  <h3 className="text-lg font-semibold">{entity.name}</h3>
                  <div className="space-x-2">
                    <Button
                      size="sm"
                      onClick={(e: React.MouseEvent) => {
                        e.stopPropagation();
                        updateEntity(entity.id, { value: entity.value + 1 });
                      }}
                    >
                      +1 Value
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={(e: React.MouseEvent) => {
                        e.stopPropagation();
                        deleteEntity(entity.id);
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {entity.description && (
                  <p className="text-gray-600">{entity.description}</p>
                )}

                <div className="flex justify-between items-center text-sm">
                  <span className="font-medium">${entity.value.toFixed(2)}</span>
                  <span className="text-gray-500">Qty: {entity.quantity}</span>
                  <span className="text-gray-400">
                    {entity.created_at.toLocaleDateString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Selected Entity Details */}
      {selectedEntity && (
        <div className="bg-blue-50 border border-blue-200 p-4 rounded-lg">
          <h2 className="text-lg font-semibold mb-2">Selected Entity Details</h2>
          <div className="space-y-1">
            <p><strong>ID:</strong> {selectedEntity.id}</p>
            <p><strong>Name:</strong> {selectedEntity.name}</p>
            <p><strong>Description:</strong> {selectedEntity.description || 'None'}</p>
            <p><strong>Value:</strong> ${selectedEntity.value.toFixed(2)}</p>
            <p><strong>Quantity:</strong> {selectedEntity.quantity}</p>
            <p><strong>Created:</strong> {selectedEntity.created_at.toISOString()}</p>
          </div>
          <Button
            className="mt-2"
            variant="outline"
            onClick={() => setSelectedEntity(null)}
          >
            Clear Selection
          </Button>
        </div>
      )}
    </div>
  );
}