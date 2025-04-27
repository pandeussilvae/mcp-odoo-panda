"""
MCP (Model Context Protocol) logging configuration module.
This module provides logging configuration for MCP servers.
"""

import logging
from typing import Dict, Any, List, Optional

def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """
    Set up logging configuration.
    
    Args:
        config: Optional logging configuration dictionary
    """
    if config is None:
        config = {
            'level': 'INFO',
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            'handlers': [
                {
                    'type': 'StreamHandler',
                    'level': 'INFO'
                }
            ]
        }

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config['level'].upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add configured handlers
    for handler_config in config['handlers']:
        handler_type = handler_config['type']
        handler_level = getattr(logging, handler_config['level'].upper())

        if handler_type == 'StreamHandler':
            handler = logging.StreamHandler()
        elif handler_type == 'FileHandler':
            handler = logging.FileHandler(handler_config['filename'])
        else:
            raise ValueError(f"Unsupported handler type: {handler_type}")

        handler.setLevel(handler_level)
        formatter = logging.Formatter(config['format'])
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    # Set up MCP logger
    mcp_logger = logging.getLogger('mcp')
    mcp_logger.setLevel(getattr(logging, config['level'].upper())) 