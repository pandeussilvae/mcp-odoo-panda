#!/usr/bin/env python3
"""
Script to update remaining ORM tools methods to use global authentication.
"""

def update_remaining_methods():
    """Update the remaining methods to use global authentication."""
    
    # Read the file
    with open('odoo_mcp/tools/orm_tools.py', 'r') as f:
        content = f.read()
    
    # Replace all remaining user_id references with global_uid
    replacements = [
        # search_read method
        ('async def search_read(\n        self,\n        user_id: int,\n        model: str',
         'async def search_read(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('# Add implicit domains for security\n            if self.security_config.implicit_domains:\n                compiled_domain = await self.implicit_domain_manager.get_implicit_domains(\n                    model, user_id, compiled_domain\n                )',
         '# Add implicit domains for security\n            if self.security_config.implicit_domains:\n                compiled_domain = await self.implicit_domain_manager.get_implicit_domains(\n                    model, global_uid, compiled_domain\n                )'),
        
        ('# Apply PII masking\n            if self.security_config.pii_masking:\n                fields_info = await self.schema_introspector.list_fields(user_id, model)',
         '# Apply PII masking\n            if self.security_config.pii_masking:\n                fields_info = await self.schema_introspector.list_fields(global_uid, model)'),
        
        ('self.audit_logger.log_operation(\n                operation="search_read",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="search_read",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="search_read",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="search_read",\n                user_id=global_uid,'),
        
        # name_search method
        ('async def name_search(\n        self,\n        user_id: int,\n        model: str',
         'async def name_search(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('self.audit_logger.log_operation(\n                operation="name_search",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="name_search",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="name_search",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="name_search",\n                user_id=global_uid,'),
        
        # read method
        ('async def read(\n        self,\n        user_id: int,\n        model: str',
         'async def read(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('# Apply PII masking\n            if self.security_config.pii_masking:\n                fields_info = await self.schema_introspector.list_fields(user_id, model)',
         '# Apply PII masking\n            if self.security_config.pii_masking:\n                fields_info = await self.schema_introspector.list_fields(global_uid, model)'),
        
        ('self.audit_logger.log_operation(\n                operation="read",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="read",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="read",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="read",\n                user_id=global_uid,'),
        
        # create method
        ('async def create(\n        self,\n        user_id: int,\n        model: str',
         'async def create(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('# Validate required fields\n            fields_info = await self.schema_introspector.list_fields(user_id, model)',
         '# Validate required fields\n            fields_info = await self.schema_introspector.list_fields(global_uid, model)'),
        
        ('self.audit_logger.log_operation(\n                operation="create",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="create",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="create",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="create",\n                user_id=global_uid,'),
        
        # write method
        ('async def write(\n        self,\n        user_id: int,\n        model: str',
         'async def write(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('self.audit_logger.log_operation(\n                operation="write",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="write",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="write",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="write",\n                user_id=global_uid,'),
        
        # actions_next_steps method
        ('async def actions_next_steps(\n        self,\n        user_id: int,\n        model: str',
         'async def actions_next_steps(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('result = await self.action_discoverer.get_next_steps(model, record_id, user_id)',
         'result = await self.action_discoverer.get_next_steps(model, record_id, global_uid)'),
        
        ('self.audit_logger.log_operation(\n                operation="actions_next_steps",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="actions_next_steps",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="actions_next_steps",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="actions_next_steps",\n                user_id=global_uid,'),
        
        # actions_call method
        ('async def actions_call(\n        self,\n        user_id: int,\n        model: str',
         'async def actions_call(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('result = await self.action_discoverer.call_action(\n                model, record_id, method, user_id, parameters, operation_id\n            )',
         'result = await self.action_discoverer.call_action(\n                model, record_id, method, global_uid, parameters, operation_id\n            )'),
        
        ('self.audit_logger.log_operation(\n                operation="actions_call",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="actions_call",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="actions_call",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="actions_call",\n                user_id=global_uid,'),
        
        # picklists method
        ('async def picklists(\n        self,\n        user_id: int,\n        model: str',
         'async def picklists(\n        self,\n        model: str'),
        
        ('# Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=user_id):',
         '# Get global UID from connection pool\n            global_uid = await self._get_global_uid()\n            \n            # Check rate limit\n            if not self.rate_limiter.check_rate_limit(user_id=global_uid):'),
        
        ('result = await self.picklist_provider.get_picklist_values(model, field, user_id, limit)',
         'result = await self.picklist_provider.get_picklist_values(model, field, global_uid, limit)'),
        
        ('self.audit_logger.log_operation(\n                operation="picklists",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="picklists",\n                user_id=global_uid,'),
        
        ('self.audit_logger.log_operation(\n                operation="picklists",\n                user_id=user_id,',
         'self.audit_logger.log_operation(\n                operation="picklists",\n                user_id=global_uid,'),
    ]
    
    for old, new in replacements:
        content = content.replace(old, new)
    
    # Write the updated content
    with open('odoo_mcp/tools/orm_tools.py', 'w') as f:
        f.write(content)
    
    print("Updated remaining ORM tools methods to use global authentication.")

if __name__ == "__main__":
    update_remaining_methods()
