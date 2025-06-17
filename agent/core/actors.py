from typing import Protocol
import dataclasses
import anyio
from anyio.streams.memory import MemoryObjectSendStream
from core import statemachine
from core.base_node import Node
from llm.common import AsyncLLM, Message
from llm.utils import loop_completion
from core.workspace import Workspace
import hashlib


@dataclasses.dataclass
class BaseData:
    workspace: Workspace
    messages: list[Message]
    files: dict[str, str | None] = dataclasses.field(default_factory=dict)

    def head(self) -> Message:
        if (num_messages := len(self.messages)) != 1:
            raise ValueError(f"Expected 1 got {num_messages} messages: {self.messages}")
        if self.messages[0].role != "assistant":
            raise ValueError(f"Expected assistant role in message: {self.messages}")
        return self.messages[0]

    @property
    def file_cache_key(self) -> str:
        s = ""
        for file, content in sorted(self.files.items(), key=lambda x: x[0]):
            s += f"{file}:{content}"
        return hashlib.md5(s.encode()).hexdigest()


class BaseActor(statemachine.Actor):
    workspace: Workspace

    async def dump_data(self, data: BaseData) -> object:
        return {
            "messages": [msg.to_dict() for msg in data.messages],
            "files": data.files,
        }

    async def load_data(self, data: dict, workspace: Workspace) -> BaseData:
        for file, content in data["files"].items():
            if content is not None:
                workspace.write_file(file, content)
            else:
                workspace.rm(file)
        messages = [Message.from_dict(msg) for msg in data["messages"]]
        return BaseData(workspace, messages, data["files"])

    async def dump_node(self, node: Node[BaseData]) -> list[dict]:
        stack, result = [node], []
        while stack:
            node = stack.pop()
            result.append({
                "id": node._id,
                "parent": node.parent._id if node.parent else None,
                "data": await self.dump_data(node.data),
            })
            stack.extend(node.children)
        return result

    async def load_node(self, data: list[dict]) -> Node[BaseData]:
        root = None
        id_to_node: dict[str, Node[BaseData]] = {}
        for item in data:
            parent = id_to_node[item["parent"]] if item["parent"] else None
            workspace = parent.data.workspace if parent else self.workspace
            node_data = await self.load_data(item["data"], workspace.clone())
            node = Node(node_data, parent, item["id"])
            if parent:
                parent.children.append(node)
            else:
                root = node
            id_to_node[item["id"]] = node
        if root is None:
            raise ValueError("Root node not found")
        return root

    async def dump(self) -> object:
        ...

    async def load(self, data: object):
        ...


class LLMActor(Protocol):
    llm: AsyncLLM

    async def run_llm(self, nodes: list[Node[BaseData]], system_prompt: str | None = None, **kwargs) -> list[Node[BaseData]]:
        async def node_fn(node: Node[BaseData], tx: MemoryObjectSendStream[Node[BaseData]]):
            history = [m for n in node.get_trajectory() for m in n.data.messages]
            new_node = Node[BaseData](
                data=BaseData(
                    workspace=node.data.workspace.clone(),
                    messages=[await loop_completion(self.llm, history, system_prompt=system_prompt, **kwargs)],
                ),
                parent=node
            )
            async with tx:
                await tx.send(new_node)
        result = []
        tx, rx = anyio.create_memory_object_stream[Node[BaseData]]()
        async with anyio.create_task_group() as tg:
            for node in nodes:
                tg.start_soon(node_fn, node, tx.clone())
            tx.close()
            async with rx:
                async for new_node in rx:
                    new_node.parent.children.append(new_node) # pyright: ignore[reportOptionalMemberAccess]
                    result.append(new_node)
        return result
