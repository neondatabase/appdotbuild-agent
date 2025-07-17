import os
import pytest
import dagger
from tests.test_application_diff import create_mock_fsm
from trpc_agent.application import FSMApplication

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="function")
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_edit_cycle_diff():
    """Simulate an edit workflow: initial app generation then a subsequent edit.
    The second diff should reflect the change between the previous snapshot and the updated FSM files."""

    # Initial version of the file in the application
    initial_files = {
        "counter.txt": "0",
    }

    # Edited version of the file (simulating a user edit / apply_feedback cycle)
    edited_files = {
        "counter.txt": "1",
    }

    # First diff: compare initial FSM files against an empty snapshot
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        fsm_app_v1 = FSMApplication(client, create_mock_fsm(initial_files))
        diff_v1 = await fsm_app_v1.get_diff_with({})

        # Ensure file addition is captured
        assert "counter.txt" in diff_v1
        assert "+0" in diff_v1  # new line added in initial diff

        # Prepare snapshot representing the state after applying the first diff
        snapshot_after_v1 = initial_files.copy()

        # Second diff: edited FSM versus snapshot from v1
        fsm_app_v2 = FSMApplication(client, create_mock_fsm(edited_files))
        diff_v2 = await fsm_app_v2.get_diff_with(snapshot_after_v1)

        # The diff should now show modification from 0 -> 1, not a new file addition
        assert "counter.txt" in diff_v2
        assert "-0" in diff_v2  # old content removed
        assert "+1" in diff_v2  # new content added

        # Optional sanity: diff length should be > diff_v1 because it includes both add/remove markers
        assert len(diff_v2) >= len(diff_v1)
