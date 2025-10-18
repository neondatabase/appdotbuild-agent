TypeScript full-stack template with tRPC for type-safe API communication between React frontend and Node.js backend. Use this when building type-safe TypeScript applications with the following structure:
- server/: Node.js backend with tRPC API
- client/: React frontend with tRPC client

## Workflow:
- Projects MUST end with validate_project to verify build + tests pass
- Bias towards backend code when the task allows implementation in multiple places
- Always add tests for what you're implementing, put them next to the code (e.g. src/*.test.ts)
- When working with Databricks or other services, use real API calls in tests (no mocks) to verify end-to-end functionality, unless explicitly instructed otherwise. It can be done on subset of data if applicable.
- Do NOT create summary files, reports, or README unless explicitly requested

## Frontend Styling Guidelines:

### Component Structure Pattern:
- Use container with proper spacing: `<div className="container mx-auto p-4">`
- Page titles: `<h1 className="text-2xl font-bold mb-4">Title</h1>`
- Forms: Use `space-y-4` for vertical spacing between inputs
- Cards: Use shadcn Card components or `border p-4 rounded-md` for item display
- Grids: Use `grid gap-4` for list layouts

### Example App Structure:
```tsx
<div className="container mx-auto p-4">
  <h1 className="text-2xl font-bold mb-4">Page Title</h1>
  <form className="space-y-4 mb-8">{/* form inputs */}</form>
  <div className="grid gap-4">{/* list items */}</div>
</div>
```

### Tailwind Usage:
- Use Tailwind classes directly in JSX
- Avoid @apply unless creating reusable component styles
- When using @apply, only in @layer components (never @layer base)
- Template has CSS variables defined - use via Tailwind (bg-background, text-foreground, etc.)

### Typography & Spacing:
- Headings: text-2xl font-bold with mb-4
- Secondary text: text-foreground/70
- Card titles: text-xl font-semibold
- Form spacing: space-y-4 between inputs, mb-8 after forms
- Grid/list spacing: gap-4 for consistent item spacing

### Component Organization:
Create separate components when:
- Logic exceeds ~100 lines
- Component is reused in multiple places
- Component has distinct responsibility (e.g., ProductForm, ProductList)
File structure:
- Shared UI: client/src/components/ui/
- Feature components: client/src/components/FeatureName.tsx

### Visual Design:
- Adjust visual mood to match user prompt, prefer clean and modern visually appealing aesthetics, but avoid overly flashy designs - keep it professional and user-friendly;
- Use shadcn/radix components (Button, Input, Card, etc.) for consistent UI
- Forms should have loading states: `disabled={isLoading}`
- Show empty states with helpful text when no data exists

### Best Practices:
- Always fetch real data from tRPC (never use mock/hardcoded data)
- Handle nullable fields: `value={field || ''}` for inputs
- Type all callbacks explicitly: `onChange={(e: React.ChangeEvent<HTMLInputElement>) => ...}`
- Use proper relative imports for server types: `import type { Product } from '../../server/src/schema'`

## Data Visualization with Recharts

The template includes Recharts for data visualization. Use Databricks brand colors for chart elements: `['#40d1f5', '#4462c9', '#EB1600', '#0B2026', '#4A4A4A', '#353a4a']` (apply via `stroke` or `fill` props).

### Basic Chart Pattern:
```tsx
import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from './components/ui/card';
import { trpc } from './utils/trpc';

function MyDashboard() {
  const [data, setData] = useState<{ name: string; value: number }[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // fetch from Databricks via tRPC
    trpc.getMetrics.query()
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>My Metrics</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="name" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="value" stroke="hsl(var(--primary))" />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
```
