"""Sample Python module for transpilation example."""


def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def greet(name: str, greeting: str = "Hello") -> str:
    """Greet someone with a custom greeting."""
    return f"{greeting}, {name}!"


def process_list(items: list[int]) -> list[int]:
    """Double all items in a list."""
    return [x * 2 for x in items]
