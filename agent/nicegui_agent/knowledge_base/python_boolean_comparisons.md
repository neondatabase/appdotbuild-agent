# Boolean Comparison Rules

Avoid explicit boolean comparisons like `== True` or `== False` in your code. Use truthiness instead: write `if value:` rather than `if value == True:`. This is more Pythonic and handles various falsy values (None, 0, empty strings, empty lists) consistently.

For negative assertions, use the `not` operator directly: `if not validate_func():` instead of `if validate_func() == False:`. This approach is cleaner and more readable, making your intent clearer to other developers.

In tests, follow the same pattern for assertions. Use `assert not validate_func()` rather than `assert validate_func() == False`. This maintains consistency across your codebase and follows Python best practices for boolean evaluation.
