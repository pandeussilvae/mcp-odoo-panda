#!/usr/bin/env python3
"""
Test script to verify the method not found error handling.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.mcp_server import OdooMCPServer
from odoo_mcp.error_handling.exceptions import OdooMethodNotFoundError

async def test_method_not_found_handling():
    """Test that method not found errors are handled correctly."""
    
    # Create a minimal config for testing
    config = {
        'protocol': 'xmlrpc',
        'connection_type': 'stdio',
        'odoo': {
            'url': 'http://localhost:8069',
            'database': 'test_db',
            'username': 'test_user',
            'password': 'test_password'
        }
    }
    
    # Create server instance
    server = OdooMCPServer(config)
    
    # Test data for method not found
    test_request = {
        "jsonrpc": "2.0",
        "method": "call_tool",
        "params": {
            "name": "odoo_execute_kw",
            "arguments": {
                "model": "res.partner",
                "method": "do_something",  # This method doesn't exist
                "args": [],
                "kwargs": {}
            }
        },
        "id": 1
    }
    
    try:
        # Process the request
        response = await server.process_request(test_request)
        
        # Check if we got an error response
        if "error" in response:
            error_message = response["error"]["message"]
            if "does not exist on the model" in error_message:
                print("✅ Test passed! Method not found error was handled correctly.")
                print(f"Error message: {error_message}")
                return True
            else:
                print(f"❌ Test failed! Unexpected error: {error_message}")
                return False
        else:
            print("❌ Test failed! Expected error but got success response.")
            return False
            
    except OdooMethodNotFoundError as e:
        print("✅ Test passed! OdooMethodNotFoundError was raised correctly.")
        print(f"Error: {e}")
        return True
    except Exception as e:
        print(f"❌ Test failed with unexpected error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_method_not_found_handling())
    sys.exit(0 if result else 1) 