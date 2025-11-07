# Timers and Navigation Patterns

Use `ui.timer` for periodic tasks and auto-refreshing content. Create update functions that modify existing UI elements rather than creating new ones: `time_label.set_text(f'Current time: {datetime.now().strftime("%H:%M:%S")}')`. Call the update function once initially, then set up the timer: `ui.timer(1.0, update_time)`.

Implement navigation using `ui.link` for internal links and `ui.navigate.to()` for programmatic navigation. Use `ui.link('Go to Dashboard', '/dashboard')` for user-clickable navigation and `ui.navigate.to('/settings')` within event handlers for conditional or automated navigation.

For dialogs and user interactions, use async patterns with proper awaiting: `result = await ui.dialog('Are you sure?', ['Yes', 'No'])`. Handle the result appropriately and provide feedback through notifications. This pattern works well for confirmation dialogs and complex user input scenarios.
