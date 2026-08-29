# Error Handling and User Feedback

Use try/except blocks for operations that might fail and provide immediate user feedback through `ui.notify()`. Always log errors with appropriate detail for debugging while showing user-friendly messages. Use `ui.notify('File processed successfully!', type='positive')` for success and `ui.notify(f'Error: {str(e)}', type='negative')` for failures.

Never use quiet failures or generic exception handling that hides important errors. Always log the specific error context: `logger.info(f'Error processing file: {filename}')` before showing user notifications. This dual approach ensures both user experience and debugging capability.

Provide contextual feedback for different operation types: `type='positive'` for successful operations, `type='negative'` for errors, `type='warning'` for cautionary messages. Keep error messages concise but informative, avoiding technical jargon that users won't understand while maintaining enough detail for troubleshooting.
