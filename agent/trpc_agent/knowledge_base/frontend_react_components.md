# React Component Organization

Create separate components when logic exceeds 100 lines, when components are reused in multiple places, or when they have distinct responsibilities like ProductForm or ProductList. Organize files logically: shared UI components in `client/src/components/ui/`, feature-specific components as `client/src/components/FeatureName.tsx`, and complex features in subdirectories like `client/src/components/feature/`.

Keep components focused on single responsibility and avoid mixing concerns. A ProductForm should handle form state and validation, while a ProductList should handle display and user interactions. Use composition over inheritance: build complex UIs by combining focused components rather than creating monolithic components with multiple responsibilities.

Follow consistent patterns for component structure: props interface definition, state management, event handlers, then JSX return. Use explicit TypeScript types for all props, state, and event handlers. Import types separately from runtime imports using `import type` syntax to keep bundles clean and improve build performance.