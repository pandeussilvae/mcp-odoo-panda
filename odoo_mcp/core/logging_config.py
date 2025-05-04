import logging
import sys
from typing import Dict, Any, Optional
import contextlib # Add contextlib import

# Import the masking utility
from odoo_mcp.security.utils import mask_sensitive_data

class SensitiveDataFilter(logging.Filter):
    """
    A logging filter that attempts to mask sensitive data within log records.

    It applies the `mask_sensitive_data` utility to the log message and its arguments.
    """
    def __init__(self, name: str = 'SensitiveDataFilter'):
        """Initialize the filter."""
        super().__init__(name)

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter the log record, masking sensitive data in msg and args.

        Args:
            record: The logging record to filter.

        Returns:
            True (always allows the record to pass after attempting masking).
        """
        # Mask the original message string
        if isinstance(record.msg, str):
            record.msg = mask_sensitive_data(record.msg)

        # Mask any arguments if they are interpolated into the message
        if record.args:
            # Important: This assumes standard %-style formatting.
            # If using f-strings directly in log messages (log.info(f"..."))
            # or str.format(), the arguments might not be in record.args
            # and the masking needs to happen *before* the logging call,
            # or the message itself (record.msg) needs more robust parsing/masking.
            # For simplicity, we primarily rely on masking record.msg.
            # We can also attempt to mask args individually.
            try:
                 # Create a new tuple with masked args to avoid modifying original
                 masked_args = []
                 for arg in record.args:
                      masked_args.append(mask_sensitive_data(arg))
                 record.args = tuple(masked_args)
            except Exception as e:
                 # Log a warning if masking args fails for some reason
                 # (e.g., unhashable types if mask_sensitive_data expects dicts/lists)
                 # Use the logger of this module to report masking errors
                 logger.warning(f"Could not mask log arguments for record: {e}", exc_info=False) # Avoid logging exception details for this warning

        return True # Always allow the record to pass after attempting masking


def setup_logging(level: str = 'INFO', protocol: str = 'stdio') -> None:
    """
    Configure logging for the Odoo MCP Server.
    
    Args:
        level: Logging level (default: 'INFO')
        protocol: Server protocol ('stdio' or 'streamable_http')
    """
    # Remove any existing handlers from the root logger
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Configure root logger
    root_logger.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and configure stderr handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root_logger.addHandler(stderr_handler)
    
    # If using stdio protocol, ensure no logs go to stdout
    if protocol == 'stdio':
        # Create a null handler for stdout to prevent any logs from going there
        class StdoutNullHandler(logging.Handler):
            def emit(self, record):
                pass
        
        stdout_handler = StdoutNullHandler()
        stdout_handler.setFormatter(formatter)
        root_logger.addHandler(stdout_handler)
        
        # Disable propagation to prevent double logging
        root_logger.propagate = False
        
        # Log the configuration
        root_logger.info(f"Logging configured for stdio protocol. All logs will be written to stderr.")
    else:
        root_logger.info(f"Logging configured for {protocol} protocol.")
    
    # Configure specific loggers
    loggers = [
        'odoo_mcp',
        'odoo_mcp.core',
        'odoo_mcp.resources',
        'odoo_mcp.tools',
        'odoo_mcp.prompts',
        'odoo_mcp.performance',
        'odoo_mcp.error_handling'
    ]
    
    for logger_name in loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        # Ensure the logger uses the root logger's handlers
        logger.propagate = True
        logger.handlers = []

    # Configure logging for libraries if needed (e.g., reduce verbosity)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("cachetools").setLevel(logging.INFO)

    logging.info("Logging setup complete.")

def setup_logging_from_config(logging_config: dict):
    """
    Set up logging configuration from a logging config dictionary (as in config.json).
    Supports multiple handlers (StreamHandler, FileHandler) and custom formats.
    """
    import logging
    root_logger = logging.getLogger()
    root_logger.setLevel(logging_config.get('level', 'INFO').upper())
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    for handler_cfg in logging_config.get('handlers', []):
        if handler_cfg['type'] == 'StreamHandler':
            handler = logging.StreamHandler()
        elif handler_cfg['type'] == 'FileHandler':
            handler = logging.FileHandler(handler_cfg['filename'])
        else:
            continue
        handler.setLevel(handler_cfg['level'].upper())
        formatter = logging.Formatter(logging_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

# Example usage:
if __name__ == "__main__":
    example_config_console = {
        "log_level": "DEBUG",
        "log_file": None,
        "log_format": "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s",
        "log_mask_sensitive": True
    } # Closing brace correctly indented
    print("--- Setting up Console Logging (DEBUG, Masked) ---", file=sys.stderr) # Print to stderr
    setup_logging(example_config_console['log_level'], 'stdio')

    # Test logging
    logger = logging.getLogger("MyTestApp")
    logger.debug("This is a debug message.")
    logger.info("Processing user login.")
    logger.warning("Password complexity low for user 'test'.")
    logger.error("Failed to connect to Odoo. API Key: secret123") # Should be masked
    try:
        x = 1 / 0
    except ZeroDivisionError:
        logger.exception("Caught an exception!") # Exception info is logged

    # Example with args
    user_data = {"username": "alice", "password": "alice_password", "email": "alice@example.com"}
    logger.info("User data received: %s", user_data) # %s formatting, args masking attempt

    print("\n--- Setting up File Logging (INFO, Unmasked) ---", file=sys.stderr) # Print to stderr
    example_config_file = {
        "log_level": "INFO",
        "log_file": "mcp_server.log",
        "log_format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        "log_mask_sensitive": False
    }
    setup_logging(example_config_file['log_level'], 'streamable_http')
    logger.info("This INFO message should go to the file.")
    logger.debug("This DEBUG message should NOT appear in the file.")
    logger.error("API Key: another_secret456") # Should NOT be masked

    print(f"\nCheck the file '{example_config_file['log_file']}' for logs.", file=sys.stderr) # Print to stderr
