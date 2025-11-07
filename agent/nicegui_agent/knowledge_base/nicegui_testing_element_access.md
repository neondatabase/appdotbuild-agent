# Element Access Patterns in Tests

For single element access, use `.elements.pop()` rather than indexing. Write `upload = user.find(ui.upload).elements.pop()` and `date_input = user.find(ui.date).elements.pop()`. Never use indexing like `elements[0]` as it causes "'set' object is not subscriptable" TypeError since `.elements` returns a set.

For multiple elements, convert the set to a list first: `buttons = list(user.find(ui.button).elements)` then check if the list has elements before accessing: `if buttons: buttons[0].click()`. This pattern safely handles cases where no elements are found.

Always wait after UI-changing actions with `await user.should_see()` before making assertions. Write `user.find('Add Item').click(); await user.should_see('New item added')` rather than immediate assertions that may fail due to async updates. The framework needs time to process UI changes.
