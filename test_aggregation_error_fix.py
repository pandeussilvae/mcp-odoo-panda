#!/usr/bin/env python3
"""
Test script to verify the aggregation error handling.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.mcp_server import OdooMCPServer
from odoo_mcp.error_handling.exceptions import OdooValidationError

async def test_aggregation_error_handling():
    """Test that aggregation errors are handled correctly."""
    
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
    
    # Test data for aggregation error (invalid aggregation function)
    test_request = {
        "jsonrpc": "2.0",
        "method": "call_tool",
        "params": {
            "name": "odoo_execute_kw",
            "arguments": {
                "model": "sale.order",
                "method": "read_group",
                "args": [
                    [["state", "=", "draft"]],  # domain
                    ["amount_total:month"],  # fields with invalid aggregation
                    ["partner_id"]  # groupby
                ],
                "kwargs": {
                    "limit": 10,
                    "offset": 0
                }
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
            if "Funzione di aggregazione" in error_message or "Aggregation Error" in error_message:
                print("✅ Test passed! Aggregation error was handled correctly.")
                print(f"Error message: {error_message}")
                return True
            else:
                print(f"❌ Test failed! Unexpected error: {error_message}")
                return False
        else:
            print("❌ Test failed! Expected error but got success response.")
            return False
            
    except OdooValidationError as e:
        if "Funzione di aggregazione" in str(e) or "Aggregation Error" in str(e):
            print("✅ Test passed! OdooValidationError was raised correctly for aggregation error.")
            print(f"Error: {e}")
            return True
        else:
            print(f"❌ Test failed! Unexpected validation error: {e}")
            return False
    except Exception as e:
        print(f"❌ Test failed with unexpected error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_aggregation_error_handling())
    sys.exit(0 if result else 1) 