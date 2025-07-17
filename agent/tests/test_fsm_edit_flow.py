import pytest
import os
import dagger
from trpc_agent.application import FSMApplication, FSMState
from log import get_logger

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture(scope="function")
def anyio_backend():
    return 'asyncio'


@pytest.mark.skip(reason="Skipping test as long running")
@pytest.mark.anyio
async def test_fsm_edit_and_diff_generation():
    """
    Test the full FSM flow including an edit operation and verify diff generation.
    1. Start FSM with an initial prompt.
    2. Run FSM to completion (generating initial app).
    3. Capture the generated files as a snapshot.
    4. Provide feedback to trigger an edit.
    5. Run FSM again for the edit to be applied.
    6. Generate a diff between the pre-edit snapshot and the post-edit FSM state.
    7. Verify the diff reflects the changes from the edit.
    """
    initial_prompt = "Create a simple counter app with a button that increments a number."
    edit_feedback = "Change the button text to 'Increment Me!'"

    # Using None for default settings, enable above for potentially faster local runs if LLM calls are slow
    # current_settings = test_settings
    current_settings = None


    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        logger.info(f"Starting FSM with prompt: '{initial_prompt}'")
        fsm_app = await FSMApplication.start_fsm(client, user_prompt=initial_prompt, settings=current_settings)

        # Run FSM to initial completion
        logger.info("Running FSM to initial completion...")
        iteration_count = 0
        max_iterations = 10 # Safety break
        while fsm_app.current_state not in (FSMState.COMPLETE, FSMState.FAILURE) and iteration_count < max_iterations:
            logger.info(f"FSM state: {fsm_app.current_state}, sending CONFIRM event.")
            await fsm_app.confirm_state()
            iteration_count += 1
            if fsm_app.maybe_error():
                logger.error(f"FSM entered FAILURE state with error: {fsm_app.maybe_error()}")
                break

        assert fsm_app.current_state == FSMState.COMPLETE, f"FSM did not reach COMPLETE state. Final state: {fsm_app.current_state}, Error: {fsm_app.maybe_error()}"
        logger.info("Initial FSM run completed.")

        # Capture files after initial generation (snapshot before edit)
        snapshot_before_edit = fsm_app.fsm.context.files.copy()
        assert snapshot_before_edit, "No files generated in the initial FSM run."
        logger.info(f"Captured snapshot of {len(snapshot_before_edit)} files before edit.")

        # Find a frontend file to check for the button text (example)
        # This relies on a common file structure, adjust if necessary
        frontend_file_path = "client/src/App.tsx" # A likely place for button text

        original_button_text_present = False
        if frontend_file_path in snapshot_before_edit:
            if "Increment" in snapshot_before_edit[frontend_file_path] and "Increment Me!" not in snapshot_before_edit[frontend_file_path]:
                 original_button_text_present = True
            logger.info(f"Content of {frontend_file_path} before edit (first 200 chars):\n{snapshot_before_edit[frontend_file_path][:200]}")
        else:
            logger.warning(f"{frontend_file_path} not found in initial files. Cannot verify original button text directly.")


        # Simulate providing feedback for an edit
        logger.info(f"Providing feedback for edit: '{edit_feedback}'")
        # The FSM should be in COMPLETE, so providing feedback will transition to APPLY_FEEDBACK
        await fsm_app.apply_changes(feedback=edit_feedback)

        # The provide_feedback call should transition the FSM.
        # The next confirm_state will execute the EditActor.
        assert fsm_app.current_state == FSMState.COMPLETE, f"FSM did not transition to COMPLETE fate after applying feedback. Current state: {fsm_app.current_state}"

        logger.info("Running FSM to apply feedback...")
        await fsm_app.confirm_state() # This should execute the EditActor

        iteration_count = 0 # Reset for post-edit completion
        while fsm_app.current_state not in (FSMState.COMPLETE, FSMState.FAILURE) and iteration_count < max_iterations:
            logger.info(f"FSM state after edit step: {fsm_app.current_state}, sending CONFIRM event.")
            await fsm_app.confirm_state()
            iteration_count += 1
            if fsm_app.maybe_error():
                logger.error(f"FSM entered FAILURE state during edit with error: {fsm_app.maybe_error()}")
                break

        assert fsm_app.current_state == FSMState.COMPLETE, f"FSM did not reach COMPLETE state after edit. Final state: {fsm_app.current_state}, Error: {fsm_app.maybe_error()}"
        logger.info("FSM run to apply feedback completed.")

        # Generate diff between snapshot (before edit) and current FSM state (after edit)
        logger.info("Generating diff between pre-edit snapshot and post-edit state...")
        diff_after_edit = await fsm_app.get_diff_with(snapshot_before_edit)

        assert diff_after_edit, "Diff after edit is empty."
        logger.info(f"Generated diff after edit (length: {len(diff_after_edit)}). First 500 chars:\n{diff_after_edit[:500]}")

        # Verify the diff reflects the edit
        # Check if the new button text is added and old one (if verifiable) is removed
        assert "Increment Me!" in diff_after_edit, "Edited button text 'Increment Me!' not found as an addition in the diff."

        if original_button_text_present:
            # This assertion is tricky because the original button text might be generic like "Increment" or "Click"
            # and might appear elsewhere. A more robust check would be to ensure the specific line changed.
            # For now, we check if the *exact phrase* from the edit request appears as an addition.
            # And if we confirmed original text, that it's somehow marked as removed.
            # A simple heuristic:
            assert "Increment" in diff_after_edit # The word "Increment" should appear, possibly as removed or part of context
            # A more specific check might be needed if the initial button text isn't just "Increment"
            # For example, if it was "Click to Increment", we'd look for `+Increment Me!` and `-Click to Increment`.

        logger.info("Test test_fsm_edit_and_diff_generation completed successfully.")
