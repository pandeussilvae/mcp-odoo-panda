"""
Odoo ORM Tools for MCP Server.
This module provides the main integration point for all ORM-related functionality
including schema introspection, domain validation, CRUD operations, and actions.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from odoo_mcp.actions import (
    ActionCallRequest, ActionCallResponse, ActionDiscoverer, ActionsRegistry,
    NextStepsResponse, PicklistProvider
)
from odoo_mcp.domain_dsl import DomainValidationRequest, DomainValidationResponse, DomainValidator
from odoo_mcp.schema import SchemaIntrospector
from odoo_mcp.security.orm_security import (
    AuditLogger, ImplicitDomainManager, PIIMasker, RateLimiter, SecurityConfig
)

logger = logging.getLogger(__name__)


class ORMTools:
    """Main ORM tools integration class for MCP server."""

    def __init__(self, connection_pool, config: Dict[str, Any]):
        """
        Initialize ORM tools.
        
        Args:
            connection_pool: Odoo connection pool
            config: Server configuration
        """
        self.pool = connection_pool
        self.config = config
        
        # Initialize security configuration
        self.security_config = SecurityConfig(
            pii_masking=config.get("pii_masking", True),
            rate_limit_per_minute=config.get("rate_limit_per_minute", 60),
            rate_limit_burst=config.get("rate_limit_burst", 100),
            audit_logging=config.get("audit_logging", True),
            implicit_domains=config.get("implicit_domains", True),
            max_payload_size=config.get("max_payload_size", 1024 * 1024),
            max_fields_limit=config.get("max_fields_limit", 100),
            max_records_limit=config.get("max_records_limit", 200)
        )
        
        # Initialize components
        self.schema_introspector = SchemaIntrospector(connection_pool, config)
        self.domain_validator = DomainValidator(self.schema_introspector)
        self.actions_registry = ActionsRegistry(config)
        self.action_discoverer = ActionDiscoverer(connection_pool, self.actions_registry)
        self.picklist_provider = PicklistProvider(connection_pool)
        
        # Initialize security components
        self.implicit_domain_manager = ImplicitDomainManager(self.schema_introspector)
        self.pii_masker = PIIMasker(self.security_config)
        self.rate_limiter = RateLimiter(self.security_config)
        self.audit_logger = AuditLogger(self.security_config)

    async def _get_global_uid(self) -> int:
        """
        Get the global UID from the connection pool.
        
        Returns:
            int: Global UID for authentication
        """
        try:
            # Get a connection from the pool to access the global UID
            async with self.pool.get_connection() as connection:
                if hasattr(connection, 'global_uid'):
                    # XMLRPC handler
                    return connection.global_uid
                elif hasattr(connection, 'uid'):
                    # JSONRPC handler
                    return connection.uid
                else:
                    raise Exception("No global UID found in connection")
        except Exception as e:
            logger.error(f"Error getting global UID: {e}")
            raise

    async def schema_version(self) -> Dict[str, str]:
        """
        Get schema version using global authentication.
        
        Returns:
            Dict with version information
        """
        start_time = time.time()
        
        try:
            # Get global UID from connection pool
            global_uid = await self._get_global_uid()
            version_info = await self.schema_introspector.get_schema_version(global_uid)
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="schema_version",
                user_id=global_uid,
                model="ir.model",
                result={"version": version_info.version},
                latency_ms=latency_ms
            )
            
            return {"version": version_info.version}
            
        except Exception as e:
            logger.error(f"Error getting schema version: {e}")
            self.audit_logger.log_operation(
                operation="schema_version",
                user_id=None,
                model="ir.model",
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def schema_models(self, with_access: bool = True) -> Dict[str, List[str]]:
        """
        Get accessible models using global authentication.
        
        Args:
            with_access: Whether to filter by access rights
            
        Returns:
            Dict with list of accessible models
        """
        start_time = time.time()
        
        try:
            # Get global UID from connection pool
            global_uid = await self._get_global_uid()
            models = await self.schema_introspector.list_models(global_uid, with_access=with_access)
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="schema_models",
                user_id=global_uid,
                model="ir.model",
                result={"models": models},
                latency_ms=latency_ms
            )
            
            return {"models": models}
            
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            self.audit_logger.log_operation(
                operation="schema_models",
                user_id=None,
                model="ir.model",
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def schema_fields(self, model: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get fields for a specific model using global authentication.
        
        Args:
            model: Model name
            
        Returns:
            Dict with field information
        """
        start_time = time.time()
        
        try:
            # Get global UID from connection pool
            global_uid = await self._get_global_uid()
            fields = await self.schema_introspector.list_fields(global_uid, model)
            
            # Convert to list format for response
            fields_list = []
            for field_name, field_info in fields.items():
                fields_list.append({
                    "name": field_info.name,
                    "ttype": field_info.ttype,
                    "required": field_info.required,
                    "readonly": field_info.readonly,
                    "relation": field_info.relation,
                    "selection": field_info.selection,
                    "domain": field_info.domain,
                    "store": field_info.store,
                    "compute": field_info.compute,
                    "writeable": field_info.writeable
                })
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="schema_fields",
                user_id=global_uid,
                model=model,
                result={"fields_count": len(fields_list)},
                latency_ms=latency_ms
            )
            
            return {"fields": fields_list}
            
        except Exception as e:
            logger.error(f"Error listing fields for model {model}: {e}")
            self.audit_logger.log_operation(
                operation="schema_fields",
                user_id=None,
                model=model,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def domain_validate(
        self, 
        model: str, 
        domain_json: Dict[str, Any]
    ) -> DomainValidationResponse:
        """
        Validate and compile a domain expression using global authentication.
        
        Args:
            model: Model name
            domain_json: Domain expression in JSON format
            
        Returns:
            DomainValidationResponse: Validation result
        """
        start_time = time.time()
        
        try:
            # Get global UID from connection pool
            global_uid = await self._get_global_uid()
            
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=global_uid):
                return DomainValidationResponse(
                    ok=False,
                    errors=["Rate limit exceeded"]
                )
            
            # Validate domain
            result = await self.domain_validator.validate_domain(model, domain_json, global_uid)
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="domain_validate",
                user_id=global_uid,
                model=model,
                domain=domain_json,
                result={"ok": result.ok, "compiled": result.compiled},
                error=result.errors[0] if result.errors else None,
                latency_ms=latency_ms
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error validating domain for model {model}: {e}")
            self.audit_logger.log_operation(
                operation="domain_validate",
                user_id=None,
                model=model,
                domain=domain_json,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def search_read(
        self,
        user_id: int,
        model: str,
        domain_json: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
        order: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search and read records with security enhancements.
        
        Args:
            user_id: User ID
            model: Model name
            domain_json: Search domain in JSON format
            fields: Fields to retrieve
            limit: Maximum number of records
            offset: Number of records to skip
            order: Order specification
            
        Returns:
            Dict with search results
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            # Apply hard caps
            limit = min(limit, self.security_config.max_records_limit)
            if fields:
                fields = fields[:self.security_config.max_fields_limit]
            
            # Compile domain if provided
            compiled_domain = []
            if domain_json:
                domain_result = await self.domain_validator.validate_domain(model, domain_json, user_id)
                if not domain_result.ok:
                    raise Exception(f"Invalid domain: {domain_result.errors}")
                compiled_domain = domain_result.compiled
            
            # Add implicit domains for security
            if self.security_config.implicit_domains:
                compiled_domain = await self.implicit_domain_manager.get_implicit_domains(
                    model, user_id, compiled_domain
                )
            
            # Execute search_read
            result = await self.pool.execute_kw(
                model=model,
                method="search_read",
                args=[compiled_domain],
                kwargs={
                    "fields": fields or ["id", "name"],
                    "limit": limit,
                    "offset": offset,
                    "order": order
                }
            )
            
            # Apply PII masking
            if self.security_config.pii_masking:
                fields_info = await self.schema_introspector.list_fields(user_id, model)
                masked_result = []
                for record in result:
                    masked_record = self.pii_masker.mask_record_data(record, model, fields_info)
                    masked_result.append(masked_record)
                result = masked_result
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="search_read",
                user_id=user_id,
                model=model,
                domain=compiled_domain,
                result={"count": len(result)},
                latency_ms=latency_ms
            )
            
            return {
                "records": result,
                "count": len(result),
                "domain": compiled_domain
            }
            
        except Exception as e:
            logger.error(f"Error in search_read for model {model}: {e}")
            self.audit_logger.log_operation(
                operation="search_read",
                user_id=user_id,
                model=model,
                domain=domain_json,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def name_search(
        self,
        user_id: int,
        model: str,
        name: str,
        operator: str = "ilike",
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Search records by name with security.
        
        Args:
            user_id: User ID
            model: Model name
            name: Name to search for
            operator: Search operator
            limit: Maximum number of results
            
        Returns:
            Dict with search results
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            # Apply hard cap
            limit = min(limit, self.security_config.max_records_limit)
            
            # Execute name_search
            result = await self.pool.execute_kw(
                model=model,
                method="name_search",
                args=[name],
                kwargs={"operator": operator, "limit": limit}
            )
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="name_search",
                user_id=user_id,
                model=model,
                result={"count": len(result)},
                latency_ms=latency_ms
            )
            
            return {
                "results": result,
                "count": len(result)
            }
            
        except Exception as e:
            logger.error(f"Error in name_search for model {model}: {e}")
            self.audit_logger.log_operation(
                operation="name_search",
                user_id=user_id,
                model=model,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def read(
        self,
        user_id: int,
        model: str,
        record_ids: List[int],
        fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Read records with security.
        
        Args:
            user_id: User ID
            model: Model name
            record_ids: List of record IDs
            fields: Fields to retrieve
            
        Returns:
            Dict with read results
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            # Apply hard caps
            if len(record_ids) > self.security_config.max_records_limit:
                record_ids = record_ids[:self.security_config.max_records_limit]
            
            if fields:
                fields = fields[:self.security_config.max_fields_limit]
            
            # Execute read
            result = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[record_ids],
                kwargs={"fields": fields}
            )
            
            # Apply PII masking
            if self.security_config.pii_masking:
                fields_info = await self.schema_introspector.list_fields(user_id, model)
                masked_result = []
                for record in result:
                    masked_record = self.pii_masker.mask_record_data(record, model, fields_info)
                    masked_result.append(masked_record)
                result = masked_result
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="read",
                user_id=user_id,
                model=model,
                record_ids=record_ids,
                result={"count": len(result)},
                latency_ms=latency_ms
            )
            
            return {
                "records": result,
                "count": len(result)
            }
            
        except Exception as e:
            logger.error(f"Error in read for model {model}: {e}")
            self.audit_logger.log_operation(
                operation="read",
                user_id=user_id,
                model=model,
                record_ids=record_ids,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def create(
        self,
        user_id: int,
        model: str,
        values: Dict[str, Any],
        operation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a record with validation and security.
        
        Args:
            user_id: User ID
            model: Model name
            values: Record values
            operation_id: Operation ID for idempotency
            
        Returns:
            Dict with creation result
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            # Validate required fields
            fields_info = await self.schema_introspector.list_fields(user_id, model)
            missing_fields = []
            for field_name, field_info in fields_info.items():
                if field_info.required and field_name not in values:
                    missing_fields.append(field_name)
            
            if missing_fields:
                raise Exception(f"Missing required fields: {', '.join(missing_fields)}")
            
            # Execute create
            result = await self.pool.execute_kw(
                model=model,
                method="create",
                args=[values]
            )
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="create",
                user_id=user_id,
                model=model,
                values=values,
                result={"id": result},
                latency_ms=latency_ms
            )
            
            return {
                "id": result,
                "operation_id": operation_id
            }
            
        except Exception as e:
            logger.error(f"Error in create for model {model}: {e}")
            self.audit_logger.log_operation(
                operation="create",
                user_id=user_id,
                model=model,
                values=values,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def write(
        self,
        user_id: int,
        model: str,
        record_ids: List[int],
        values: Dict[str, Any],
        operation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Write to records with validation and security.
        
        Args:
            user_id: User ID
            model: Model name
            record_ids: List of record IDs
            values: Values to write
            operation_id: Operation ID for idempotency
            
        Returns:
            Dict with write result
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            # Apply hard cap
            if len(record_ids) > self.security_config.max_records_limit:
                record_ids = record_ids[:self.security_config.max_records_limit]
            
            # Execute write
            result = await self.pool.execute_kw(
                model=model,
                method="write",
                args=[record_ids, values]
            )
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="write",
                user_id=user_id,
                model=model,
                record_ids=record_ids,
                values=values,
                result={"success": result},
                latency_ms=latency_ms
            )
            
            return {
                "success": result,
                "operation_id": operation_id
            }
            
        except Exception as e:
            logger.error(f"Error in write for model {model}: {e}")
            self.audit_logger.log_operation(
                operation="write",
                user_id=user_id,
                model=model,
                record_ids=record_ids,
                values=values,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def actions_next_steps(
        self,
        user_id: int,
        model: str,
        record_id: int
    ) -> NextStepsResponse:
        """
        Get next steps suggestions for a record.
        
        Args:
            user_id: User ID
            model: Model name
            record_id: Record ID
            
        Returns:
            NextStepsResponse: Next steps information
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            result = await self.action_discoverer.get_next_steps(model, record_id, user_id)
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="actions_next_steps",
                user_id=user_id,
                model=model,
                record_ids=[record_id],
                result={"actions_count": len(result.available_actions)},
                latency_ms=latency_ms
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting next steps for {model}/{record_id}: {e}")
            self.audit_logger.log_operation(
                operation="actions_next_steps",
                user_id=user_id,
                model=model,
                record_ids=[record_id],
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def actions_call(
        self,
        user_id: int,
        model: str,
        record_id: int,
        method: str,
        parameters: Optional[Dict[str, Any]] = None,
        operation_id: Optional[str] = None
    ) -> ActionCallResponse:
        """
        Call an action method on a record.
        
        Args:
            user_id: User ID
            model: Model name
            record_id: Record ID
            method: Method name to call
            parameters: Method parameters
            operation_id: Operation ID for idempotency
            
        Returns:
            ActionCallResponse: Action call result
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            result = await self.action_discoverer.call_action(
                model, record_id, method, user_id, parameters, operation_id
            )
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="actions_call",
                user_id=user_id,
                model=model,
                record_ids=[record_id],
                values={"method": method, "parameters": parameters},
                result={"success": result.success},
                error=result.error,
                latency_ms=latency_ms
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error calling action {method} on {model}/{record_id}: {e}")
            self.audit_logger.log_operation(
                operation="actions_call",
                user_id=user_id,
                model=model,
                record_ids=[record_id],
                values={"method": method, "parameters": parameters},
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise

    async def picklists(
        self,
        user_id: int,
        model: str,
        field: str,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get picklist values for a field.
        
        Args:
            user_id: User ID
            model: Model name
            field: Field name
            limit: Maximum number of values
            
        Returns:
            Dict with picklist values
        """
        start_time = time.time()
        
        try:
            # Check rate limit
            if not self.rate_limiter.check_rate_limit(user_id=user_id):
                raise Exception("Rate limit exceeded")
            
            # Apply hard cap
            limit = min(limit, self.security_config.max_records_limit)
            
            result = await self.picklist_provider.get_picklist_values(model, field, user_id, limit)
            
            # Audit log
            latency_ms = (time.time() - start_time) * 1000
            self.audit_logger.log_operation(
                operation="picklists",
                user_id=user_id,
                model=model,
                result={"count": len(result)},
                latency_ms=latency_ms
            )
            
            return {
                "values": result,
                "count": len(result)
            }
            
        except Exception as e:
            logger.error(f"Error getting picklist values for {model}.{field}: {e}")
            self.audit_logger.log_operation(
                operation="picklists",
                user_id=user_id,
                model=model,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000
            )
            raise
