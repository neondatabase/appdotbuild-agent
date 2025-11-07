# Data Binding Properties

NiceGUI supports two-way data binding between UI elements and models through `bind_*` methods. Use `bind_value` for two-way binding of input values, allowing automatic synchronization between UI components and underlying data. This is particularly useful for forms and user input scenarios.

Implement one-way bindings for UI state control: `bind_visibility_from` to control element visibility based on another element's state, and `bind_text_from` to update text content reactively. These patterns create dynamic interfaces that respond to user interactions without manual event handling.

Bind values directly to storage systems for persistent state: `ui.textarea('Note').bind_value(app.storage.user, 'note')` creates automatic persistence across browser sessions. This pattern works with any storage mechanism and eliminates the need for manual save/load operations.
