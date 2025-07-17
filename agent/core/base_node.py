from typing import Self
import uuid


class Node[T]:
    _id: str
    data: T
    parent: Self | None
    children: list[Self]

    def __init__(self, data: T, parent: Self | None = None, id: str | None = None):
        self._id = id if id else uuid.uuid4().hex
        self.data = data
        self.parent = parent
        self.children = []

    @property
    def is_leaf(self) -> bool:
        return not self.children
    
    @property
    def depth(self) -> int:
        return self.parent.depth + 1 if self.parent else 0
    
    def get_trajectory(self) -> list[Self]:
        stack = [self]
        while stack[-1].parent:
            stack.append(stack[-1].parent)
        return stack[::-1]
    
    def get_all_children(self) -> list[Self]:
        children, stack = [], [self]
        while stack:
            node = stack.pop()
            children.append(node)
            stack.extend(node.children)
        return children
