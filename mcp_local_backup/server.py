"""
MCP (Model Context Protocol) server entry point.
This module provides the main entry point for running MCP servers.
"""

import asyncio
import logging
from typing import Dict, Any

from mcp_local_backup.config import load_config
from mcp_local_backup.log_config import setup_logging
from odoo_mcp.core.mcp_server import OdooMCPServer

logger = logging.getLogger(__name__)

async def main():
    """
    Main entry point for the MCP server.
    """
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='MCP Server')
    parser.add_argument('--config', required=True, help='Path to configuration file')
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Set up logging
    setup_logging(config.logging)
    
    # Create server instance
    server = OdooMCPServer(config.__dict__)
    
    try:
        # Run the server
        await server.run()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        await server.stop()
    except Exception as e:
        logger.error(f"Server error: {e}")
        await server.stop()
        raise

if __name__ == '__main__':
    asyncio.run(main()) 