"""
MCP (Model Context Protocol) configuration module.
This module provides configuration management for MCP servers.
"""

import os
import yaml
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

@dataclass
class MCPConfig:
    """Configuration for MCP server."""
    odoo_url: str
    database: str
    uid: str
    password: str
    protocol: str
    connection_type: str
    requests_per_minute: int
    rate_limit_max_wait_seconds: int
    pool_size: int
    timeout: int
    session_timeout_minutes: int
    sse_queue_maxsize: Optional[int] = None
    allowed_origins: Optional[List[str]] = None
    logging: Optional[Dict[str, Any]] = None

def load_config(config_path: str) -> MCPConfig:
    """
    Load configuration from a YAML file.
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        MCPConfig object with loaded configuration
        
    Raises:
        FileNotFoundError: If the configuration file doesn't exist
        yaml.YAMLError: If the configuration file is invalid
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
    with open(config_path, 'r') as f:
        config_data = yaml.safe_load(f)
        
    return MCPConfig(
        odoo_url=config_data['odoo_url'],
        database=config_data['database'],
        uid=config_data['uid'],
        password=config_data['password'],
        protocol=config_data['protocol'],
        connection_type=config_data['connection_type'],
        requests_per_minute=config_data['requests_per_minute'],
        rate_limit_max_wait_seconds=config_data['rate_limit_max_wait_seconds'],
        pool_size=config_data['pool_size'],
        timeout=config_data['timeout'],
        session_timeout_minutes=config_data['session_timeout_minutes'],
        sse_queue_maxsize=config_data.get('sse_queue_maxsize'),
        allowed_origins=config_data.get('allowed_origins'),
        logging=config_data.get('logging')
    ) 