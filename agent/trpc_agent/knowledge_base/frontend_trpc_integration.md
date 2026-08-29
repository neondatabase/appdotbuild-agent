# tRPC Frontend Integration

Use tRPC client for all backend communication with proper TypeScript inference from your server router types. Import the configured client and call queries with `await trpc.getProducts.query()` and mutations with `await trpc.createProduct.mutate(data)`. Store complete responses before accessing properties to ensure type safety and handle loading states appropriately.

Handle tRPC responses correctly by matching the actual return types from your handlers. Don't assume field names or nested structures - inspect the handler implementation to verify the exact response format. Transform data after fetching if your components need different structures, but keep state types aligned with API responses to avoid confusion.

Implement proper error handling for tRPC calls using try/catch blocks around queries and mutations. Display user-friendly error messages while logging detailed errors for debugging. Use loading states to provide feedback during async operations, and update component state immediately after successful mutations to keep the UI responsive and synchronized with the backend.