import pytest
from nicegui.testing import User
from nicegui import ui
from collections import deque
from typing import Set, List, Dict
from logging import getLogger

logger = getLogger(__name__)

pytest_plugins = ["nicegui.testing.user_plugin"]


def extract_navigation_paths(element) -> List[str]:
    paths = []

    # Check for direct 'to' property (ui.link)
    if hasattr(element, "_props"):
        to_prop = element._props.get("to", "")
        if to_prop and to_prop.startswith("/"):
            paths.append(to_prop)

    return paths


def find_navigable_elements(user: User) -> Dict[str, List[str]]:
    """Find all potentially navigable elements and their target paths"""
    navigable = {"links": [], "buttons": [], "menu_items": []}

    # Find ui.link elements
    try:
        link_elements = user.find(ui.link).elements
        for link in link_elements:
            paths = extract_navigation_paths(link)
            navigable["links"].extend(paths)
    except AssertionError:
        logger.debug("No links found")

    # Find ui.button elements that might navigate
    try:
        button_elements = user.find(ui.button).elements
        for button in button_elements:
            # Check if button has navigation-related text
            button_text = getattr(button, "text", "").lower()
            nav_keywords = ["go to", "navigate", "open", "view", "show"]
            if any(keyword in button_text for keyword in nav_keywords):
                # This button might navigate, but we can't easily determine where
                # In a real test, we might need to click it and see what happens
                pass
    except AssertionError:
        logger.debug("No buttons found that might navigate")

    # Find ui.menu_item elements
    try:
        menu_elements = user.find(ui.menu_item).elements
        for menu_item in menu_elements:
            paths = extract_navigation_paths(menu_item)
            navigable["menu_items"].extend(paths)
    except AssertionError:
        logger.debug("No menu items found")

    return navigable


@pytest.mark.asyncio
async def test_all_pages_smoke_fast(user: User):
    """Fast smoke test using user fixture - checks all reachable pages"""
    visited: Set[str] = set()
    queue = deque(["/"])
    errors = []
    all_navigable_elements = []

    while queue:
        path = queue.popleft()
        if path in visited:
            continue

        visited.add(path)

        try:
            # Visit the page
            await user.open(path)

            # Find all navigable elements
            navigable = find_navigable_elements(user)

            # Collect all paths from different element types
            all_paths = []
            for element_type, paths in navigable.items():
                all_paths.extend(paths)
                if paths:
                    all_navigable_elements.append(
                        {"page": path, "type": element_type, "count": len(paths), "paths": paths}
                    )

            # Add new paths to queue
            for new_path in all_paths:
                if new_path and new_path not in visited:
                    queue.append(new_path)

        except Exception as e:
            logger.debug("Got error")
            errors.append({"path": path, "error": str(e)})

    # Verify results
    assert len(visited) > 0, "No pages were visited"
    assert not errors, f"Encountered {len(errors)} errors during navigation: {errors}"
