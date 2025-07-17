import pytest
import dagger
from core.workspace import Workspace

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_diff_generation():
    import os
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        workspace = await Workspace.create(client, context=client.directory().with_new_file("__init__.py", ""))
        workspace.write_file('__init__.py', 'import requests\n')
        diff = await workspace.diff()
        edit_diff = [
            "diff --git a/__init__.py b/__init__.py",
            "index e69de29..20b1553 100644",
            "--- a/__init__.py",
            "+++ b/__init__.py",
            "@@ -0,0 +1 @@",
            "+import requests",
        ]
        assert diff == "\n".join(edit_diff + [""])
        workspace.write_file('test.txt', 'Hello, world!\n')
        diff = await workspace.diff()
        create_diff = [
            "diff --git a/test.txt b/test.txt",
            "new file mode 100644",
            "index 0000000..af5626b",
            "--- /dev/null",
            "+++ b/test.txt",
            "@@ -0,0 +1 @@",
            "+Hello, world!",
        ]
        assert diff == "\n".join(edit_diff + create_diff + [""])
