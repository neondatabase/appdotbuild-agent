# Common NiceGUI Component Pitfalls

Avoid passing both positional and keyword arguments for the same parameter. For `ui.date()`, never write `ui.date('Date', value=date.today())` as this causes "multiple values for argument 'value'". Instead use `ui.date(value=date.today())`. For date values, use `.isoformat()` when setting: `date_input.set_value(date.today().isoformat())`.

Don't use non-existent parameters like `size` for `ui.button()`. Instead of `ui.button('Click', size='sm')`, use CSS classes: `ui.button('Click').classes('text-sm')`. Similarly, use proper dialog creation patterns: `with ui.dialog() as dialog, ui.card():` rather than trying to use async context managers.

Capture nullable values safely in lambda functions: use `on_click=lambda user_id=user.id: delete_user(user_id) if user_id else None` instead of `on_click=lambda: delete_user(user.id)` where `user.id` might be None. Always register modules properly in startup.py by importing and calling their `create()` functions.
