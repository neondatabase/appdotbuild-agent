import os
import pytest
import dagger
from core.base_node import Node
from core.actors import BaseActor, BaseData
from llm.common import Message, TextRaw
from core.workspace import Workspace

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


class SimpleActor(BaseActor):
    root: Node[BaseData] | None = None

    def __init__(self, workspace: Workspace, root: Node[BaseData] | None = None):
        self.workspace = workspace
        self.root = root

    async def execute(self, *args, **kwargs):
        pass

    async def dump(self) -> object:
        if self.root is None:
            return []
        return await self.dump_node(self.root)

    async def load(self, data: object):
        if not isinstance(data, list):
            raise ValueError(f"Expected list got {type(data)}")
        if not data:
            return
        self.root = await self.load_node(data)


async def test_actor_recovery():
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        workspace = await Workspace.create(client)
        root = Node[BaseData](BaseData(
            workspace=workspace.clone(),
            messages=[Message(role="user", content=[TextRaw("test")])],
        ))
        workspace_child = workspace.clone()
        workspace_child.write_file("test.txt", "test")
        child = Node[BaseData](BaseData(
            workspace=workspace_child,
            messages=[Message(role="assistant", content=[TextRaw("test child")])],
            files={"test.txt": "test"},
        ), parent=root)
        root.children.append(child)
        actor = SimpleActor(workspace, root)
        dumped = await actor.dump()

        loaded = SimpleActor(await Workspace.create(client))
        await loaded.load(dumped)

        assert loaded.root is not None
        assert loaded.root.data.files == root.data.files
        assert loaded.root.data.messages == root.data.messages

        loaded_child = loaded.root.children[0]
        assert loaded_child.data.files == child.data.files
        assert loaded_child.data.messages == child.data.messages
        assert await loaded_child.data.workspace.read_file("test.txt") == "test"
