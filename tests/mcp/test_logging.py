import pytest
import logging
from mcp_local_backup.logging import setup_logging, get_logger

def test_setup_logging():
    setup_logging()
    logger = logging.getLogger("mcp")
    assert logger.level == logging.INFO
    assert len(logger.handlers) > 0

def test_get_logger():
    logger = get_logger("test_module")
    assert logger.name == "mcp.test_module"
    assert logger.level == logging.INFO
    assert len(logger.handlers) > 0

def test_logger_output(caplog):
    logger = get_logger("test_output")
    logger.info("Test message")
    assert "Test message" in caplog.text
    assert "test_output" in caplog.text

def test_logger_levels(caplog):
    logger = get_logger("test_levels")
    
    logger.debug("Debug message")
    assert "Debug message" not in caplog.text
    
    logger.info("Info message")
    assert "Info message" in caplog.text
    
    logger.warning("Warning message")
    assert "Warning message" in caplog.text
    
    logger.error("Error message")
    assert "Error message" in caplog.text 