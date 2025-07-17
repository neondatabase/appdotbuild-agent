from log import get_logger, clear_trace_id, set_trace_id, get_trace_id


logger = get_logger(__name__)

def test_log(caplog):
    set_trace_id("test_id")
    logger.info(f"Test log message: {get_trace_id()}")

    rec = caplog.records[-1]
    assert rec.message == "Test log message: test_id"
    assert rec.trace_id == "test_id"

    clear_trace_id()
    logger.info(f"Test log message: {get_trace_id()}")
    rec = caplog.records[-1]
    assert rec.message == "Test log message: None"
    assert rec.trace_id == "unk"

    set_trace_id("other_id")
    logger.info(f"Test log message: {get_trace_id()}")
    rec = caplog.records[-1]
    assert rec.message == "Test log message: other_id"
    assert rec.trace_id == "other_id"
