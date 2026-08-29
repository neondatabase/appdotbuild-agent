# NiceGUI Storage Mechanisms

Use `app.storage.tab` for data unique to each browser tab session, stored server-side in memory. This data is lost when the server restarts and is only available within page builder functions after establishing connection with `await ui.context.client.connected()`. Perfect for tab-specific counters, temporary form state, or tab-specific preferences.

Use `app.storage.user` for data associated with a unique identifier in the browser session cookie, persisting across all browser tabs and page reloads. This is ideal for user preferences, authentication state, and persistent user-specific data that should survive page navigation and browser tab changes.

Choose the right storage type: `app.storage.client` for single page session data (discarded on reload), `app.storage.general` for application-wide shared data, and `app.storage.browser` for browser session cookies (limited size). Generally prefer `app.storage.user` over `app.storage.browser` for better security and larger storage capacity.
