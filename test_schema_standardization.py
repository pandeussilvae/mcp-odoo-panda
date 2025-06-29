#!/usr/bin/env python3
"""
Test script to verify the tool schema standardization.
"""

import asyncio
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from odoo_mcp.core.capabilities_manager import CapabilitiesManager

def test_schema_standardization():
    """Test that all tool schemas are standardized with the 'arguments' wrapper."""
    
    # Create a minimal config
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
    
    # Create capabilities manager
    capabilities_manager = CapabilitiesManager(config)
    
    # Get all tools
    tools = capabilities_manager.list_tools()
    
    print(f"Found {len(tools)} tools")
    
    # Check that all tools have the standardized schema
    for tool in tools:
        tool_name = tool['name']
        input_schema = tool.get('inputSchema', {})
        
        print(f"\nChecking tool: {tool_name}")
        print(f"Input schema: {json.dumps(input_schema, indent=2)}")
        
        # Check if the schema has the 'arguments' wrapper
        properties = input_schema.get('properties', {})
        if 'arguments' not in properties:
            print(f"❌ Tool {tool_name} does not have the 'arguments' wrapper!")
            return False
        
        # Check if 'arguments' is required
        required = input_schema.get('required', [])
        if 'arguments' not in required:
            print(f"❌ Tool {tool_name} does not require 'arguments'!")
            return False
        
        # Check if the arguments object has properties
        arguments_properties = properties['arguments'].get('properties', {})
        if not arguments_properties:
            print(f"❌ Tool {tool_name} has empty arguments properties!")
            return False
        
        print(f"✅ Tool {tool_name} has standardized schema")
    
    print("\n🎉 All tools have standardized schemas!")
    return True

def test_schema_validation():
    """Test that the schemas are valid for LangChain."""
    
    # Create a minimal config
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
    
    # Create capabilities manager
    capabilities_manager = CapabilitiesManager(config)
    
    # Get all tools
    tools = capabilities_manager.list_tools()
    
    # Test valid input for each tool
    test_cases = [
        {
            "name": "odoo_execute_kw",
            "arguments": {
                "model": "res.partner",
                "method": "search_read",
                "args": [[], ["id", "name"]],
                "kwargs": {"limit": 10}
            }
        },
        {
            "name": "odoo_call_method",
            "arguments": {
                "model": "res.partner",
                "method": "search_read",
                "args": [[], ["id", "name"]],
                "kwargs": {"limit": 10}
            }
        },
        {
            "name": "odoo_search_read",
            "arguments": {
                "model": "res.partner",
                "domain": [["is_company", "=", True]],
                "fields": ["id", "name"],
                "limit": 10,
                "offset": 0
            }
        },
        {
            "name": "odoo_read",
            "arguments": {
                "model": "res.partner",
                "ids": [1, 2, 3],
                "fields": ["id", "name"]
            }
        },
        {
            "name": "odoo_create",
            "arguments": {
                "model": "res.partner",
                "values": {"name": "Test Partner"}
            }
        },
        {
            "name": "odoo_write",
            "arguments": {
                "model": "res.partner",
                "ids": [1],
                "values": {"name": "Updated Partner"}
            }
        },
        {
            "name": "odoo_unlink",
            "arguments": {
                "model": "res.partner",
                "ids": [1]
            }
        },
        {
            "name": "data_export",
            "arguments": {
                "model": "res.partner",
                "ids": [1, 2, 3],
                "fields": ["id", "name"],
                "format": "csv"
            }
        },
        {
            "name": "data_import",
            "arguments": {
                "model": "res.partner",
                "data": "id,name\n1,Test Partner",
                "format": "csv"
            }
        },
        {
            "name": "report_generator",
            "arguments": {
                "report_name": "partner_report",
                "ids": [1, 2, 3],
                "format": "pdf"
            }
        }
    ]
    
    for test_case in test_cases:
        tool_name = test_case["name"]
        arguments = test_case["arguments"]
        
        # Find the tool
        tool = next((t for t in tools if t['name'] == tool_name), None)
        if not tool:
            print(f"❌ Tool {tool_name} not found!")
            return False
        
        input_schema = tool.get('inputSchema', {})
        
        # Validate the input against the schema
        try:
            # This is a simplified validation - in a real scenario, you'd use a JSON schema validator
            required = input_schema.get('required', [])
            if 'arguments' not in required:
                print(f"❌ Tool {tool_name} does not require 'arguments'!")
                return False
            
            arguments_properties = input_schema.get('properties', {}).get('arguments', {}).get('properties', {})
            arguments_required = input_schema.get('properties', {}).get('arguments', {}).get('required', [])
            
            # Check required fields
            for field in arguments_required:
                if field not in arguments:
                    print(f"❌ Tool {tool_name} missing required field: {field}")
                    return False
            
            print(f"✅ Tool {tool_name} validation passed")
            
        except Exception as e:
            print(f"❌ Tool {tool_name} validation failed: {e}")
            return False
    
    print("\n🎉 All tool validations passed!")
    return True

if __name__ == "__main__":
    print("Testing schema standardization...")
    schema_ok = test_schema_standardization()
    
    print("\nTesting schema validation...")
    validation_ok = test_schema_validation()
    
    if schema_ok and validation_ok:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1) 