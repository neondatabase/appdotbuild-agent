---
name: webapp-creation
description: Build TypeScript web applications from user prompts. Uses Vite for bundling.
---

You build web apps from prompts using TypeScript and Vite.

## Workflow

1. Read template files from this skill's `template/` directory
2. Copy ALL template files to the output directory (including package.json, Dockerfile, etc.)
3. Implement the user's requirements by modifying `app.ts`
4. Update `index.html` title and structure as needed
5. Run validation: execute `scripts/validate` with the app path
6. Fix any type errors before completing

## Template Files

The template directory contains:
- `index.html` - HTML shell with app container
- `styles.css` - Base styles
- `app.ts` - TypeScript starter with type-safe patterns
- `package.json` - Dependencies (Vite, TypeScript)
- `tsconfig.json` - TypeScript configuration
- `vite.config.ts` - Vite build configuration
- `Dockerfile` - Production build with nginx

## Validation

After writing code, run the validate script:
```bash
.claude/skills/webapp-creation/scripts/validate /path/to/app
```

This installs dependencies, type-checks, and builds the app.

## Patterns

Read `reference/patterns.md` for TypeScript patterns to follow.

## Constraints

- TypeScript only (no plain JS)
- Single-page app structure
- Use Vite for bundling (already configured)
- Must pass type validation
- Use interfaces for all data structures
- Use strict null checks
- Keep all app logic in `app.ts`
