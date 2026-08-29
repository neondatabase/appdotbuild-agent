# NiceGUI Slot Stack Management

Understand that NiceGUI wraps Vue.js/Quasar components, and slots come from Vue.js architecture. The slot stack tracks which Vue slot is currently active for placing new elements. The error "slot stack empty" occurs when you try to create UI elements outside the proper context (no active Vue slot).

Use the container pattern for async functions: pass containers explicitly and use them with context managers. Instead of `async def update(): ui.label('data')`, write `async def update(container): with container: container.clear(); ui.label('data')`. This ensures UI elements are created within the proper slot context.

For async updates, prefer the refreshable pattern using `@ui.refreshable` decorator. Create a refreshable function that contains your UI: `@ui.refreshable def show_data(): ui.label(data)`, then call `show_data.refresh()` from async functions instead of creating UI elements directly. Never create UI elements in background tasks - always use containers or refreshable patterns.
