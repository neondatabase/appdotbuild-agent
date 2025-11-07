# TypeScript Import Patterns

Calculate relative paths carefully when importing server types: from `client/src/App.tsx` use `../../server/src/schema`, from `client/src/components/Component.tsx` use `../../../server/src/schema`, and from nested components add additional `../` segments. Count exactly: start from your file location, navigate up to client directory, then up to project root, then down to server directory.

Always use type-only imports for server types: `import type { Product, CreateProductInput } from '../../server/src/schema'`. This prevents runtime imports of server code in your client bundle and clearly separates type definitions from runtime dependencies. Use regular imports only for client-specific code like components, utilities, and tRPC client configuration.

Organize imports consistently: external dependencies first, then internal imports grouped by type (components, utilities, types), and finally relative imports from closest to furthest. Use trailing commas in import lists for better git diffs: `import { A, B, C, } from 'module'`. This pattern makes imports easy to scan and maintain as your project grows.