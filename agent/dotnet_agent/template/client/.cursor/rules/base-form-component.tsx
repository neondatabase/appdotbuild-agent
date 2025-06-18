import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { trpc } from '@/utils/trpc';
import { useState } from 'react';
import type { CreateEntityInput, Entity } from '../../../server/src/schema';

interface BaseFormComponentProps {
  onSuccess?: (entity: Entity) => void;
  onCancel?: () => void;
  initialData?: Partial<CreateEntityInput>;
  title?: string;
  submitText?: string;
  isEdit?: boolean;
}

export default function BaseFormComponent({
  onSuccess,
  onCancel,
  initialData,
  title = 'Create Entity',
  submitText = 'Create',
  isEdit = false
}: BaseFormComponentProps) {
  // Form state with proper typing for nullable fields
  const [formData, setFormData] = useState<CreateEntityInput>({
    name: initialData?.name || '',
    description: initialData?.description || null, // Explicitly null, not undefined
    value: initialData?.value || 0,
    quantity: initialData?.quantity || 0
  });

  // UI state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [generalError, setGeneralError] = useState<string | null>(null);

  // Validation function
  const validateForm = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Name is required';
    }

    if (formData.value < 0) {
      newErrors.value = 'Value must be positive';
    }

    if (formData.quantity < 0) {
      newErrors.quantity = 'Quantity must be non-negative';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!validateForm()) {
      return;
    }

    setIsSubmitting(true);
    setGeneralError(null);

    try {
      const result = await trpc.createEntity.mutate(formData);
      
      // Call success callback if provided
      onSuccess?.(result);
      
      // Reset form if not editing
      if (!isEdit) {
        setFormData({
          name: '',
          description: null,
          value: 0,
          quantity: 0
        });
      }
      
    } catch (err) {
      console.error('Failed to submit form:', err);
      setGeneralError(
        err instanceof Error 
          ? err.message 
          : 'Failed to submit form. Please try again.'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Handle input changes with proper typing
  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData((prev: CreateEntityInput) => ({
      ...prev,
      name: e.target.value
    }));
    
    // Clear error when user starts typing
    if (errors.name) {
      setErrors((prev: Record<string, string>) => ({
        ...prev,
        name: ''
      }));
    }
  };

  const handleDescriptionChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setFormData((prev: CreateEntityInput) => ({
      ...prev,
      description: e.target.value || null // Convert empty string to null
    }));
  };

  const handleValueChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseFloat(e.target.value) || 0;
    setFormData((prev: CreateEntityInput) => ({
      ...prev,
      value
    }));
    
    // Clear error when value becomes valid
    if (errors.value && value >= 0) {
      setErrors((prev: Record<string, string>) => ({
        ...prev,
        value: ''
      }));
    }
  };

  const handleQuantityChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const quantity = parseInt(e.target.value) || 0;
    setFormData((prev: CreateEntityInput) => ({
      ...prev,
      quantity
    }));
    
    // Clear error when quantity becomes valid
    if (errors.quantity && quantity >= 0) {
      setErrors((prev: Record<string, string>) => ({
        ...prev,
        quantity: ''
      }));
    }
  };

  // Handle form reset
  const handleReset = () => {
    setFormData({
      name: initialData?.name || '',
      description: initialData?.description || null,
      value: initialData?.value || 0,
      quantity: initialData?.quantity || 0
    });
    setErrors({});
    setGeneralError(null);
  };

  return (
    <Card className="w-full max-w-2xl mx-auto">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {/* General Error Display */}
        {generalError && (
          <Alert className="mb-4" variant="destructive">
            <AlertDescription>{generalError}</AlertDescription>
          </Alert>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name Field */}
          <div className="space-y-2">
            <Label htmlFor="name">Name *</Label>
            <Input
              id="name"
              type="text"
              placeholder="Enter entity name"
              value={formData.name}
              onChange={handleNameChange}
              required
              className={errors.name ? 'border-red-500' : ''}
            />
            {errors.name && (
              <p className="text-sm text-red-600">{errors.name}</p>
            )}
          </div>

          {/* Description Field */}
          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              placeholder="Enter description (optional)"
              // Handle nullable field with fallback to empty string for display
              value={formData.description || ''}
              onChange={handleDescriptionChange}
              rows={3}
            />
            <p className="text-xs text-gray-500">
              Leave empty if no description is needed
            </p>
          </div>

          {/* Value Field */}
          <div className="space-y-2">
            <Label htmlFor="value">Value *</Label>
            <Input
              id="value"
              type="number"
              placeholder="0.00"
              value={formData.value}
              onChange={handleValueChange}
              step="0.01"
              min="0"
              required
              className={errors.value ? 'border-red-500' : ''}
            />
            {errors.value && (
              <p className="text-sm text-red-600">{errors.value}</p>
            )}
          </div>

          {/* Quantity Field */}
          <div className="space-y-2">
            <Label htmlFor="quantity">Quantity *</Label>
            <Input
              id="quantity"
              type="number"
              placeholder="0"
              value={formData.quantity}
              onChange={handleQuantityChange}
              min="0"
              required
              className={errors.quantity ? 'border-red-500' : ''}
            />
            {errors.quantity && (
              <p className="text-sm text-red-600">{errors.quantity}</p>
            )}
          </div>

          {/* Form Actions */}
          <div className="flex flex-col sm:flex-row gap-2 pt-4">
            <Button
              type="submit"
              disabled={isSubmitting}
              className="flex-1"
            >
              {isSubmitting ? 'Submitting...' : submitText}
            </Button>
            
            <Button
              type="button"
              variant="outline"
              onClick={handleReset}
              disabled={isSubmitting}
            >
              Reset
            </Button>
            
            {onCancel && (
              <Button
                type="button"
                variant="secondary"
                onClick={onCancel}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
            )}
          </div>
        </form>

        {/* Form Debug Info (development only) */}
        {process.env.NODE_ENV === 'development' && (
          <details className="mt-4 text-xs">
            <summary className="cursor-pointer text-gray-500">
              Debug Form State
            </summary>
            <pre className="mt-2 p-2 bg-gray-100 rounded text-xs overflow-auto">
              {JSON.stringify({ formData, errors }, null, 2)}
            </pre>
          </details>
        )}
      </CardContent>
    </Card>
  );
}