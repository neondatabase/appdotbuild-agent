# Async vs Sync Page Functions

Use async page functions when you need to access `app.storage.tab` (requires `await ui.context.client.connected()`), show dialogs and wait for user response, or perform asynchronous operations like API calls and file I/O. The async pattern is necessary when your page needs to wait for external resources or user interactions.

Use sync page functions for simple UI rendering without async operations, basic event handlers, and state updates. Sync functions are more straightforward and perform better when you don't need to await anything. Most basic pages with forms, navigation, and timers can use sync functions.

Choose the right pattern based on your needs: async for tab storage, dialogs, file uploads with processing; sync for simple forms, navigation, timers, and basic UI updates. Don't make pages async unless you actually need to await something, as it adds unnecessary complexity.
