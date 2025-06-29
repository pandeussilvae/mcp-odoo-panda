#!/usr/bin/env python3
"""
Test script to verify JSON-RPC response format fixes.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.mcp_server import OdooMCPServer

async def test_jsonrpc_response_format():
    """Test that all tools return proper JSON-RPC 2.0 format."""
    
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
    
    # Test tools that should return proper JSON-RPC format
    test_tools = [
        "odoo_execute_kw",
        "odoo_search_read", 
        "odoo_read",
        "odoo_write",
        "odoo_unlink",
        "odoo_create"
    ]
    
    for tool_name in test_tools:
        print(f"\n🧪 Testing {tool_name}...")
        
        # Create test request
        test_request = {
            "jsonrpc": "2.0",
            "method": "call_tool",
            "params": {
                "name": tool_name,
                "arguments": {
                    "model": "res.partner",
                    "method": "search_read",
                    "args": [[], ["id", "name"]],
                    "kwargs": {}
                }
            },
            "id": 1
        }
        
        try:
            # Process the request
            response = await server.process_request(test_request)
            
            # Check if response has required JSON-RPC fields
            if "jsonrpc" not in response:
                print(f"❌ {tool_name}: Missing 'jsonrpc' field")
                print(f"   Response: {json.dumps(response, indent=2)}")
                continue
                
            if "id" not in response:
                print(f"❌ {tool_name}: Missing 'id' field")
                print(f"   Response: {json.dumps(response, indent=2)}")
                continue
                
            if "method" in response and response["method"] != "2.0":
                print(f"❌ {tool_name}: Invalid 'method' field in response")
                print(f"   Response: {json.dumps(response, indent=2)}")
                continue
                
            print(f"✅ {tool_name}: Proper JSON-RPC format")
            
        except Exception as e:
            print(f"❌ {tool_name}: Error - {e}")
    
    print("\n🎯 JSON-RPC format test completed!")

if __name__ == "__main__":
    asyncio.run(test_jsonrpc_response_format()) 