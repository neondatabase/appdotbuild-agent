# React Hooks Patterns

Follow React Hook rules strictly by including all dependencies in useEffect, useCallback, and useMemo dependency arrays. Wrap functions used in useEffect with useCallback if they reference state or props: `const loadData = useCallback(async () => { /* logic */ }, [dependency1, dependency2])`. Use empty dependency arrays `[]` only for mount-only effects that don't depend on any values.

Structure hook usage with clear patterns: declare state first, then memoized values and callbacks, then effects that depend on them. For data fetching, create a memoized callback that handles the async operation, then use it in useEffect: `useEffect(() => { loadData(); }, [loadData])`. This pattern prevents infinite re-renders and makes dependencies explicit.

Handle async operations properly by checking for cleanup in useEffect when dealing with component unmounting or dependency changes. Use loading states to provide user feedback during async operations, and handle errors gracefully by catching them in your async callbacks and updating error state appropriately. Never ignore the exhaustive-deps ESLint rule - missing dependencies cause bugs.