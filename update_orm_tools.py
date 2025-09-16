#!/usr/bin/env python3
"""
Script to update ORM tools methods to use global authentication.
This script will replace all user_id parameters with global UID retrieval.
"""

import re

def update_method_signatures():
    """Update method signatures to remove user_id parameter."""
    
    # Read the file
    with open('odoo_mcp/tools/orm_tools.py', 'r') as f:
        content = f.read()
    
    # Update method signatures
    patterns = [
        # domain_validate
        (r'async def domain_validate\(\s*self,\s*user_id:\s*int,\s*model:\s*str,\s*domain_json:\s*Dict\[str,\s*Any\]\s*\)',
         'async def domain_validate(\n        self,\n        model: str,\n        domain_json: Dict[str, Any]\n    )'),
        
        # search_read
        (r'async def search_read\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def search_read(\n        self,\n        model: str'),
        
        # name_search
        (r'async def name_search\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def name_search(\n        self,\n        model: str'),
        
        # read
        (r'async def read\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def read(\n        self,\n        model: str'),
        
        # create
        (r'async def create\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def create(\n        self,\n        model: str'),
        
        # write
        (r'async def write\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def write(\n        self,\n        model: str'),
        
        # actions_next_steps
        (r'async def actions_next_steps\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def actions_next_steps(\n        self,\n        model: str'),
        
        # actions_call
        (r'async def actions_call\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def actions_call(\n        self,\n        model: str'),
        
        # picklists
        (r'async def picklists\(\s*self,\s*user_id:\s*int,\s*model:\s*str',
         'async def picklists(\n        self,\n        model: str'),
    ]
    
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    # Update docstrings
    docstring_patterns = [
        (r'Get the current schema version for a user\.', 'Get the current schema version using global authentication.'),
        (r'Get accessible models for a user\.', 'Get accessible models using global authentication.'),
        (r'Get fields for a specific model\.', 'Get fields for a specific model using global authentication.'),
        (r'Validate and compile a domain expression\.', 'Validate and compile a domain expression using global authentication.'),
        (r'Search and read records with security enhancements\.', 'Search and read records with security enhancements using global authentication.'),
        (r'Search records by name with security\.', 'Search records by name with security using global authentication.'),
        (r'Read records with security\.', 'Read records with security using global authentication.'),
        (r'Create a record with validation and security\.', 'Create a record with validation and security using global authentication.'),
        (r'Write to records with validation and security\.', 'Write to records with validation and security using global authentication.'),
        (r'Get next steps suggestions for a record\.', 'Get next steps suggestions for a record using global authentication.'),
        (r'Call an action method on a record\.', 'Call an action method on a record using global authentication.'),
        (r'Get picklist values for a field\.', 'Get picklist values for a field using global authentication.'),
    ]
    
    for pattern, replacement in docstring_patterns:
        content = re.sub(pattern, replacement, content)
    
    # Update Args sections
    args_patterns = [
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*with_access:\s*Whether to filter by access rights', 
         'Args:\n            with_access: Whether to filter by access rights'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name', 
         'Args:\n            model: Model name'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*domain_json:\s*Domain expression in JSON format', 
         'Args:\n            model: Model name\n            domain_json: Domain expression in JSON format'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*domain_json:\s*Search domain in JSON format\s*\n\s*fields:\s*Fields to retrieve\s*\n\s*limit:\s*Maximum number of records\s*\n\s*offset:\s*Number of records to skip\s*\n\s*order:\s*Order specification', 
         'Args:\n            model: Model name\n            domain_json: Search domain in JSON format\n            fields: Fields to retrieve\n            limit: Maximum number of records\n            offset: Number of records to skip\n            order: Order specification'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*name:\s*Name to search for\s*\n\s*operator:\s*Search operator\s*\n\s*limit:\s*Maximum number of results', 
         'Args:\n            model: Model name\n            name: Name to search for\n            operator: Search operator\n            limit: Maximum number of results'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*record_ids:\s*List of record IDs\s*\n\s*fields:\s*Fields to retrieve', 
         'Args:\n            model: Model name\n            record_ids: List of record IDs\n            fields: Fields to retrieve'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*values:\s*Record values\s*\n\s*operation_id:\s*Operation ID for idempotency', 
         'Args:\n            model: Model name\n            values: Record values\n            operation_id: Operation ID for idempotency'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*record_ids:\s*List of record IDs\s*\n\s*values:\s*Values to write\s*\n\s*operation_id:\s*Operation ID for idempotency', 
         'Args:\n            model: Model name\n            record_ids: List of record IDs\n            values: Values to write\n            operation_id: Operation ID for idempotency'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*record_id:\s*Record ID', 
         'Args:\n            model: Model name\n            record_id: Record ID'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*record_id:\s*Record ID\s*\n\s*method:\s*Method name to call\s*\n\s*parameters:\s*Method parameters\s*\n\s*operation_id:\s*Operation ID for idempotency', 
         'Args:\n            model: Model name\n            record_id: Record ID\n            method: Method name to call\n            parameters: Method parameters\n            operation_id: Operation ID for idempotency'),
        (r'Args:\s*\n\s*user_id:\s*Odoo user ID\s*\n\s*model:\s*Model name\s*\n\s*field:\s*Field name\s*\n\s*limit:\s*Maximum number of values', 
         'Args:\n            model: Model name\n            field: Field name\n            limit: Maximum number of values'),
    ]
    
    for pattern, replacement in args_patterns:
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    
    # Write the updated content
    with open('odoo_mcp/tools/orm_tools.py', 'w') as f:
        f.write(content)
    
    print("Updated ORM tools method signatures and docstrings.")

if __name__ == "__main__":
    update_method_signatures()
