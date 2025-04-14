import logging
import sys
from typing import Dict, Any
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


def setup_logging(config: Dict[str, Any]):
    """
    Configure the Python root logger based on settings from the config dictionary.

    Sets the log level, format, output handler (console or file), and optionally
    adds a filter to mask sensitive data.

    Args:
        config: Configuration dictionary containing logging settings like:
                'log_level' (e.g., "DEBUG", "INFO"),
                'log_file' (path or null/None for console),
                'log_format' (format string),
                'log_mask_sensitive' (boolean).
    """
    log_level_str = config.get('log_level', 'INFO').upper()
    log_file = config.get('log_file', None)
    log_format = config.get('log_format', '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s')
    mask_sensitive = config.get('log_mask_sensitive', True)

    log_level = getattr(logging, log_level_str, logging.INFO)

    # Create formatter
    formatter = logging.Formatter(log_format)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates if called multiple times
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create handler (console or file)
    # Redirect print statements within this block to stderr
    with contextlib.redirect_stdout(sys.stderr):
        if log_file:
            handler = logging.FileHandler(log_file, encoding='utf-8')
            print(f"Logging configured to file: {log_file} at level {log_level_str}") # Print config info
        else:
            # Ensure console logs go to stderr to avoid interfering with stdio JSON communication
            handler = logging.StreamHandler(sys.stderr) # Handler itself goes to stderr
            print(f"Logging configured to console (stderr) at level {log_level_str}") # Print config info

    handler.setFormatter(formatter)

    # Add the masking filter if enabled
    # Redirect print statements within this block to stderr
    with contextlib.redirect_stdout(sys.stderr):
        if mask_sensitive:
            print("Sensitive data masking is ENABLED for logging.") # Print to stderr via redirect
            sensitive_filter = SensitiveDataFilter()
            handler.addFilter(sensitive_filter)
        else:
            print("Sensitive data masking is DISABLED for logging.") # Print to stderr via redirect


    # Add handler to the root logger
    root_logger.addHandler(handler)

    # Configure logging for libraries if needed (e.g., reduce verbosity)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("cachetools").setLevel(logging.INFO)

    logging.info("Logging setup complete.")

# Example usage:
if __name__ == "__main__":
    example_config_console = {
        "log_level": "DEBUG",
        "log_file": None,
        "log_format": "%(asctime)s - %(levelname)s - [%(name)s:%(lineno)d] - %(message)s",
        "log_mask_sensitive": True
    } # Closing brace correctly indented
    print("--- Setting up Console Logging (DEBUG, Masked) ---", file=sys.stderr) # Print to stderr
    setup_logging(example_config_console)

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
    setup_logging(example_config_file)
    logger.info("This INFO message should go to the file.")
    logger.debug("This DEBUG message should NOT appear in the file.")
    logger.error("API Key: another_secret456") # Should NOT be masked

    print(f"\nCheck the file '{example_config_file['log_file']}' for logs.", file=sys.stderr) # Print to stderr
