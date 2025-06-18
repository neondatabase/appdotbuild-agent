import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { trpc } from '@/utils/trpc';
import { useState, useEffect, useCallback } from 'react';
import type { Entity, CreateEntityInput } from '../../../server/src/schema';

interface BaseComponentProps {
  title?: string;
  onEntityCreated?: (entity: Entity) => void;
}

export default function BaseComponent({ title = 'Entity Management', onEntityCreated }: BaseComponentProps) {
  // State with explicit typing
  const [entities, setEntities] = useState<Entity[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state with proper typing for nullable fields
  const [formData, setFormData] = useState<CreateEntityInput>({
    name: '',
    description: null, // Explicitly null, not undefined
    value: 0,
    quantity: 0
  });

  // useCallback to memoize function used in useEffect
  const loadEntities = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const result = await trpc.searchEntities.query({});
      setEntities(result);
    } catch (err) {
      console.error('Failed to load entities:', err);
      setError('Failed to load entities. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, []); // Empty deps since trpc is stable

  // useEffect with proper dependencies
  useEffect(() => {
    loadEntities();
  }, [loadEntities]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    
    try {
      const response = await trpc.createEntity.mutate(formData);
      
      // Update entities list with explicit typing in setState callback
      setEntities((prev: Entity[]) => [...prev, response]);
      
      // Reset form to initial state
      setFormData({
        name: '',
        description: null,
        value: 0,
        quantity: 0
      });

      // Call callback if provided
      onEntityCreated?.(response);
      
    } catch (err) {
      console.error('Failed to create entity:', err);
      setError('Failed to create entity. Please check your input and try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await trpc.deleteEntity.mutate({ id });
      setEntities((prev: Entity[]) => prev.filter(entity => entity.id !== id));
    } catch (err) {
      console.error('Failed to delete entity:', err);
      setError('Failed to delete entity. Please try again.');
    }
  };

  return (
    <div className="container mx-auto p-4 space-y-6">
      <h1 className="text-3xl font-bold">{title}</h1>

      {/* Error Display */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
          {error}
        </div>
      )}

      {/* Create Form */}
      <Card>
        <CardHeader>
          <CardTitle>Create New Entity</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              placeholder="Entity name"
              value={formData.name}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setFormData((prev: CreateEntityInput) => ({ ...prev, name: e.target.value }))
              }
              required
            />
            <Input
              placeholder="Description (optional)"
              // Handle nullable field with fallback to empty string
              value={formData.description || ''}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setFormData((prev: CreateEntityInput) => ({
                  ...prev,
                  description: e.target.value || null // Convert empty string back to null
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
            <Button type="submit" disabled={isSubmitting} className="w-full">
              {isSubmitting ? 'Creating...' : 'Create Entity'}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Entities List */}
      <Card>
        <CardHeader>
          <CardTitle>Entities</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-4">
              <p className="text-gray-500">Loading entities...</p>
            </div>
          ) : entities.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-gray-500">No entities yet. Create one above!</p>
            </div>
          ) : (
            <div className="grid gap-4">
              {entities.map((entity: Entity) => (
                <div key={entity.id} className="border rounded-lg p-4 space-y-2">
                  <div className="flex justify-between items-start">
                    <h3 className="text-xl font-semibold">{entity.name}</h3>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => handleDelete(entity.id)}
                    >
                      Delete
                    </Button>
                  </div>
                  
                  {/* Handle nullable description */}
                  {entity.description && (
                    <p className="text-gray-600">{entity.description}</p>
                  )}
                  
                  <div className="flex justify-between items-center">
                    <span className="text-lg font-medium">
                      ${entity.value.toFixed(2)}
                    </span>
                    <span className="text-sm text-gray-500">
                      Quantity: {entity.quantity}
                    </span>
                  </div>
                  
                  <p className="text-xs text-gray-400">
                    Created: {entity.created_at.toLocaleDateString()}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}