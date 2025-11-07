# Form Handling Patterns

Handle nullable database fields carefully in controlled inputs by providing defined values: use `value={formData.description || ''}` to convert null to empty string for display, then convert back with `description: e.target.value || null` when updating state. This pattern ensures HTML inputs always receive string values while maintaining proper null handling for database operations.

Structure form state to match your schema types exactly, initializing nullable fields as null rather than undefined: `description: null, price: 0, stock_quantity: 0`. Use explicit TypeScript types for setState callbacks: `setFormData((prev: CreateProductInput) => ({ ...prev, field: value }))` to catch type mismatches early and ensure state consistency.

Implement proper form validation and submission handling with loading states and error feedback. Reset forms after successful submission by restoring initial state values. For numeric inputs, use proper conversion: `parseInt(e.target.value) || 0` for integers and `parseFloat(e.target.value) || 0` for decimals, with appropriate min/max constraints and step values for better user experience.