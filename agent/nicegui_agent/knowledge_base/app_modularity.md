# Application Modularity

Break your application into focused modules that narrow their scope and separate core logic from view components. Each module should be defined in a separate file and expose a `create()` function that assembles the module's UI. This pattern promotes code organization and reusability across your application.

Define modules with clear boundaries: create functions like `word_counter.create()` that set up routes and UI components for specific features. Keep the module's logic self-contained and avoid cross-module dependencies where possible. Each module should handle its own UI setup and event handlers.

Build your root application in `app/startup.py` by importing and calling each module's create function. Always call `create_tables()` first to ensure database schema exists, then initialize each module: `word_counter.create()`. This centralized startup pattern makes it easy to manage your application's initialization sequence.
