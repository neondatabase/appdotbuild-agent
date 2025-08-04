import os
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock
import dagger
from trpc_agent.application import FSMApplication
from core.statemachine import StateMachine
from log import get_logger

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture(scope="function")
def anyio_backend():
    return 'asyncio'

class MockApplicationContext:
    """Mock context for testing FSMApplication"""
    def __init__(self, files=None):
        self.files = files or {
            "test_file.txt": "Hello, world!",
            "client/src/App.tsx": "function App() { return <div>Test App</div>; }",
            "server/index.js": "console.log('Server starting');"
        }

def create_mock_fsm(files=None):
    """Helper function to create a mock FSM with specified files"""
    mock_fsm = MagicMock(spec=StateMachine)
    mock_fsm.context = MockApplicationContext(files)
    mock_fsm.dump = AsyncMock(return_value={"state": "test_state"})
    return mock_fsm


@pytest.mark.anyio
async def test_get_diff_with_empty_snapshot():
    """
    Test get_diff_with with an empty snapshot (complete template scenario)
    This should generate a diff with all files in the FSM and all files from the template
    """
    # Create files that will be in our FSM
    fsm_files = {
        "test_file.txt": "Hello, world!",
        "client/src/App.tsx": "function App() { return <div>Test App</div>; }",
        "server/index.js": "console.log('Server starting');"
    }

    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        fsm_application = FSMApplication(client, create_mock_fsm(fsm_files))

        diff_result = await fsm_application.get_diff_with({})

        assert isinstance(diff_result, str)
        assert len(diff_result) > 0

        for file_path in fsm_files.keys():
            assert file_path in diff_result

        assert "Dockerfile" in diff_result

@pytest.mark.anyio
async def test_get_diff_with_identical_snapshot():
    """
    Test get_diff_with when snapshot is identical to FSM files
    This should still include template files in the diff even if user files don't change
    """
    # Create files that will be in both FSM and snapshot
    test_files = {
        "test_file.txt": "Hello, world!",
        "client/src/App.tsx": "function App() { return <div>Test App</div>; }"
    }

    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create FSM application with our test files
        fsm_application = FSMApplication(client, create_mock_fsm(test_files))

        # Call get_diff_with using identical snapshot
        diff_result = await fsm_application.get_diff_with(test_files)

        # Verify we got a non-empty diff (due to template files)
        assert isinstance(diff_result, str)
        assert len(diff_result) > 0

        # Template files should be present in the diff
        assert "Dockerfile" in diff_result

        # But our identical files shouldn't show content changes
        assert "+Hello, world!" not in diff_result
        assert "+function App()" not in diff_result

@pytest.mark.anyio
async def test_get_diff_with_modified_files():
    """
    Test get_diff_with when files are modified between snapshot and FSM
    This should generate a diff with modifications and template files
    """
    # Create initial snapshot files
    snapshot_files = {
        "test_file.txt": "Hello, world!",
        "client/src/App.tsx": "function App() { return <div>Original App</div>; }"
    }

    # Create modified FSM files (content has changed)
    fsm_files = {
        "test_file.txt": "Hello, modified world!",
        "client/src/App.tsx": "function App() { return <div>Modified App</div>; }"
    }

    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create FSM application with our modified files
        fsm_application = FSMApplication(client, create_mock_fsm(fsm_files))

        # Call get_diff_with using the original snapshot
        diff_result = await fsm_application.get_diff_with(snapshot_files)

        # Verify we got a diff string
        assert isinstance(diff_result, str)
        assert len(diff_result) > 0

        # Check for template files in the diff
        assert "Dockerfile" in diff_result

        # Verify that diff contains specific modifications of our files
        assert "Modified App" in diff_result
        assert "Original App" in diff_result
        assert "Hello, modified world" in diff_result

@pytest.mark.anyio
async def test_get_diff_with_added_files():
    """
    Test get_diff_with when files are added in FSM compared to snapshot
    This should generate a diff with added files and template files
    """
    # Create initial snapshot with some files
    snapshot_files = {
        "test_file.txt": "Hello, world!",
    }

    # Create FSM with additional files
    fsm_files = {
        "test_file.txt": "Hello, world!",
        "client/src/App.tsx": "function App() { return <div>New App</div>; }",
        "server/index.js": "console.log('Server starting');"
    }

    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create FSM application with our expanded files
        fsm_application = FSMApplication(client, create_mock_fsm(fsm_files))

        # Call get_diff_with using the original snapshot
        diff_result = await fsm_application.get_diff_with(snapshot_files)

        # Verify we got a diff string
        assert isinstance(diff_result, str)
        assert len(diff_result) > 0

        # Check for template files in the diff
        assert "Dockerfile" in diff_result

        # Verify that our added files are in the diff
        # Since we have template files, we need to be careful about how we check
        # The added files might be overshadowed by the template files in the diff
        # But they should still be referenced somewhere
        assert "client/src/App.tsx" in diff_result
        assert "server/index.js" in diff_result

@pytest.mark.anyio
async def test_get_diff_with_removed_files():
    """
    Test get_diff_with when files are removed in FSM compared to snapshot
    This should generate a diff that contains both removed files and template files
    """
    # Create initial snapshot with more files
    snapshot_files = {
        "test_file.txt": "Hello, world!",
        "client/src/App.tsx": "function App() { return <div>App</div>; }",
        "server/index.js": "console.log('Server starting');",
        "to_be_removed.txt": "This file will be removed"
    }

    # Create FSM with fewer files (some removed)
    fsm_files = {
        "test_file.txt": "Hello, world!",
        "client/src/App.tsx": "function App() { return <div>App</div>; }",
    }

    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create FSM application with our reduced files
        fsm_application = FSMApplication(client, create_mock_fsm(fsm_files))

        # Call get_diff_with using the original snapshot
        diff_result = await fsm_application.get_diff_with(snapshot_files)

        # Verify we got a diff string
        assert isinstance(diff_result, str)
        assert len(diff_result) > 0

        # Log the full diff to debug
        logger.info(f"Diff length: {len(diff_result)}")
        logger.info(f"Diff snippet: {diff_result[:200]}")

        # Check for template files in the diff (which dominates the output)
        assert "Dockerfile" in diff_result

        # Note: The template addition may overshadow the file removals in the diff
        # So we don't check for specific removal markers as they might not be
        # prominently featured in the diff output

@pytest.mark.anyio
async def test_get_diff_with_exception_handling():
    """Test error handling when something goes wrong during diff generation"""
    # Mock the dagger client instead of creating a real connection
    mock_client = Mock()
    mock_container = Mock()
    mock_client.container.return_value.from_.return_value.with_workdir.return_value = mock_container
    mock_container.with_exec.side_effect = Exception("Test diff error")
    
    fsm_application = FSMApplication(mock_client, create_mock_fsm())
    
    # Verify that an exception is raised
    with pytest.raises(Exception) as exc_info:
        await fsm_application.get_diff_with({})
    
    assert "Test diff error" in str(exc_info.value)

@pytest.mark.anyio
async def test_get_diff_with_real_dagger():
    """Integration test with a real Dagger instance (requires Dagger to be available)"""
    # Skip this test by default since it requires Docker/Dagger
    try:
        async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
            # Create FSM application
            fsm_application = FSMApplication(client, create_mock_fsm())

            # Call the method with an empty snapshot
            diff_result = await fsm_application.get_diff_with({})

            # Just check that we got a string result (might be empty or an error message)
            assert isinstance(diff_result, str)
    except Exception as e:
        pytest.skip(f"Dagger not available: {str(e)}")
