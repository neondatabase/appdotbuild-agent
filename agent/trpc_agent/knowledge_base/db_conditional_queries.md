# Conditional Query Building

Build dynamic queries by collecting conditions in an array and applying them conditionally. Start with `const conditions: SQL<unknown>[] = []`, then push conditions based on filter parameters: `conditions.push(eq(table.field, value))`. Apply the conditions using `query.where(conditions.length === 1 ? conditions[0] : and(...conditions))` with proper spread operator usage.

Maintain proper query order when building conditionally: initialize base query, add joins if needed, collect and apply where conditions, then add ordering and pagination. This sequence preserves TypeScript inference and prevents runtime errors. For complex filters, build conditions incrementally: check each filter parameter and add the appropriate condition to your array.

Handle edge cases properly: when no conditions are present, omit the where clause entirely; when only one condition exists, pass it directly instead of wrapping in `and()`; for multiple conditions, always use the spread operator `and(...conditions)`. This approach keeps queries clean and efficient while supporting arbitrary combinations of filters without complex conditional logic.