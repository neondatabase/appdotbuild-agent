const API_BASE_URL = 'http://localhost:5000/api';

export interface Product {
  id: number;
  name: string;
  description?: string;
  price: number;
  stockQuantity: number;
  createdAt: string;
}

export interface CreateProductDto {
  name: string;
  description?: string;
  price: number;
  stockQuantity: number;
}

export interface UpdateProductDto {
  name?: string;
  description?: string;
  price?: number;
  stockQuantity?: number;
}

class ApiClient {
  private async fetch<T>(url: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE_URL}${url}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return response.json();
  }

  async getProducts(): Promise<Product[]> {
    return this.fetch<Product[]>('/products');
  }

  async getProduct(id: number): Promise<Product> {
    return this.fetch<Product>(`/products/${id}`);
  }

  async createProduct(product: CreateProductDto): Promise<Product> {
    return this.fetch<Product>('/products', {
      method: 'POST',
      body: JSON.stringify(product),
    });
  }

  async updateProduct(id: number, product: UpdateProductDto): Promise<void> {
    await this.fetch<void>(`/products/${id}`, {
      method: 'PUT',
      body: JSON.stringify(product),
    });
  }

  async deleteProduct(id: number): Promise<void> {
    await this.fetch<void>(`/products/${id}`, {
      method: 'DELETE',
    });
  }
}

export const api = new ApiClient();