# Lambda Functions with Nullable Values

When using lambda functions with nullable values, capture the values safely to prevent runtime errors. Instead of `on_click=lambda: delete_user(user.id)` where `user.id` might be None, use `on_click=lambda user_id=user.id: delete_user(user_id) if user_id else None`. This pattern captures the value at lambda creation time.

For event handlers that receive event arguments, extend the pattern: `on_click=lambda e, item_id=item.id: delete_item(item_id) if item_id else None`. The event parameter comes first, followed by your captured variables. This ensures the lambda has access to both the event and the safely captured nullable value.

Alternatively, you can use explicit None checks within the lambda: `on_click=lambda: delete_item(item.id) if item.id is not None else None`. Choose the pattern that makes your code most readable, but always guard against None values to prevent unexpected crashes.
