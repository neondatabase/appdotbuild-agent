# UI Test Interaction Patterns

Handle different input types correctly in tests. For text inputs use `user.find('Item Name').type('Apple')`. For button clicks, use `user.find('Save').click()` as the framework handles event arguments automatically. For date inputs, access the element directly and use `.set_value()` with ISO format: `date_element.set_value(date.today().isoformat())`.

UI tests run in isolated context where slot errors are common. Use `ui.run_sync()` wrapper if you need to create UI outside page context. However, prefer testing the service layer logic directly over complex UI interactions, as this is more reliable and faster to execute.

When UI tests repeatedly fail with slot errors, pivot to testing the underlying service logic instead. Focus your UI tests on critical user flows only, keeping them as smoke tests rather than comprehensive test coverage. The majority of your testing should target business logic without UI dependencies.
