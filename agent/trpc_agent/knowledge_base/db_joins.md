# Database Joins

Joins change the result structure from flat objects to nested objects with table-specific properties. After joining tables, access data via nested properties: `result.payments.amount` and `result.subscriptions.name` instead of flat `result.amount`. This nested structure is essential for handling multiple tables with potentially conflicting column names.

Build joined queries carefully, as they affect both query construction and result processing. Use `.innerJoin(targetTable, eq(sourceTable.foreign_key, targetTable.id))` for required relationships and `.leftJoin()` when the related record might not exist. Apply where conditions to the appropriate table: conditions for the main table before the join, conditions for joined tables after the join.

Handle joined results with proper type awareness: when processing results, check whether joins were applied and access data accordingly. Use type assertions or conditional logic to handle different result shapes: `const paymentData = hasJoin ? result.payments : result`. Remember to apply numeric conversions to the correct nested properties and handle null values from outer joins appropriately.