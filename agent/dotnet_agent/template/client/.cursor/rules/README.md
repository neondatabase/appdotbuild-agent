# Client-Side Cursor Rules

This directory contains cursor rules for client-side development with React, tRPC, Radix UI, and Tailwind CSS.

## Rule Files

### Component Development
- **`component-organization.mdc`** - React component structure and organization patterns
- **`form-handling.mdc`** - Form state management and nullable field handling
- **`react-hooks.mdc`** - useEffect, useCallback, and dependency array patterns

### API Integration
- **`trpc-integration.mdc`** - tRPC client usage and API communication patterns
- **`import-paths.mdc`** - Correct relative import paths from server schema files

### Type Safety and Syntax
- **`typescript-types.mdc`** - TypeScript patterns for React components and event handlers
- **`jsx-syntax.mdc`** - JSX best practices and common syntax errors

### UI and User Experience
- **`ui-styling.mdc`** - Radix UI components and Tailwind CSS usage patterns
- **`error-handling.mdc`** - Loading states, error boundaries, and user feedback
- **`data-transformation.mdc`** - API response handling and display formatting

## Template Files

### Reference Examples
- **`base-component.tsx`** - Complete React component with tRPC integration
- **`base-trpc-usage.tsx`** - Comprehensive tRPC client usage examples
- **`base-form-component.tsx`** - Form handling with validation and state management
- **`base-ui-component.tsx`** - Radix UI component examples and patterns

## Key Patterns

### State Management
- Proper TypeScript typing for all state and callbacks
- Nullable field handling between forms and API
- Optimistic updates with error rollback

### API Communication
- tRPC query and mutation patterns
- Loading and error state management
- Type-safe server communication

### Component Architecture
- Single responsibility principle
- Proper component composition
- Reusable UI patterns

### User Experience
- Consistent loading states and error handling
- Responsive design with Tailwind CSS
- Accessibility with Radix UI primitives

### Type Safety
- Correct relative imports from server schemas
- Explicit event handler typing
- Runtime type checking where needed

## Usage

These rules are automatically applied based on file patterns (globs). Each rule includes:
- Description of the pattern
- File patterns where it applies
- Reference to template files with `@filename`
- Best practices and common pitfalls to avoid

## Development Workflow

1. **Component Creation** - Follow organization patterns for new components
2. **Form Development** - Use form handling patterns for user input
3. **API Integration** - Apply tRPC patterns for server communication
4. **Styling** - Leverage Radix UI and Tailwind CSS patterns
5. **Error Handling** - Implement consistent error and loading states