import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useState, useEffect, useCallback } from 'react';
import { api, type Product, type CreateProductDto } from '@/utils/api';

function App() {
  // Explicit typing with Product interface
  const [products, setProducts] = useState<Product[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Form state with proper typing for nullable fields
  const [formData, setFormData] = useState<CreateProductDto>({
    name: '',
    description: '', // Empty string for input control
    price: 0,
    stockQuantity: 0
  });

  // useCallback to memoize function used in useEffect
  const loadProducts = useCallback(async () => {
    try {
      const result = await api.getProducts();
      setProducts(result);
    } catch (error) {
      console.error('Failed to load products:', error);
    }
  }, []); // Empty deps since api is stable

  // useEffect with proper dependencies
  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      const productData = {
        ...formData,
        description: formData.description || undefined // Convert empty string to undefined
      };
      const response = await api.createProduct(productData);
      // Update products list with explicit typing in setState callback
      setProducts((prev: Product[]) => [...prev, response]);
      // Reset form
      setFormData({
        name: '',
        description: '',
        price: 0,
        stockQuantity: 0
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
            setFormData((prev: CreateProductDto) => ({ ...prev, name: e.target.value }))
          }
          required
        />
        <Input
          placeholder="Description (optional)"
          value={formData.description || ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFormData((prev: CreateProductDto) => ({
              ...prev,
              description: e.target.value
            }))
          }
        />
        <Input
          type="number"
          placeholder="Price"
          value={formData.price}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFormData((prev: CreateProductDto) => ({ ...prev, price: parseFloat(e.target.value) || 0 }))
          }
          step="0.01"
          min="0"
          required
        />
        <Input
          type="number"
          placeholder="Stock quantity"
          value={formData.stockQuantity}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setFormData((prev: CreateProductDto) => ({ ...prev, stockQuantity: parseInt(e.target.value) || 0 }))
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
              {product.description && (
                <p className="text-gray-600">{product.description}</p>
              )}
              <div className="flex justify-between mt-2">
                <span>${product.price.toFixed(2)}</span>
                <span>In stock: {product.stockQuantity}</span>
              </div>
              <p className="text-xs text-gray-400 mt-2">
                Created: {new Date(product.createdAt).toLocaleDateString()}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default App;