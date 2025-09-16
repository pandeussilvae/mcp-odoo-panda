"""
Odoo Domain DSL validator and compiler.
This module provides a safe domain language for building Odoo search domains
with validation, compilation, and special value expansion.
"""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# Allowed operators
ALLOWED_OPERATORS = {
    '=', '!=', 'in', 'not in', 'ilike', '=ilike', 
    'child_of', '>', '>=', '<', '<='
}

# Logical operators
LOGICAL_OPERATORS = {'and', 'or', 'not'}

# Special values that get expanded
SPECIAL_VALUES = {
    '__current_company_ids__',
    '__current_user_id__',
    '__today__',
    '__start_of_month__',
    '__start_of_year__',
    '__yesterday__',
    '__tomorrow__',
    '__current_month__',
    '__current_year__'
}

# Maximum depth and size limits for security
MAX_DOMAIN_DEPTH = 10
MAX_DOMAIN_SIZE = 1000


class DomainValidationRequest(BaseModel):
    """Request model for domain validation."""
    model: str
    domain_json: Dict[str, Any]


class DomainValidationResponse(BaseModel):
    """Response model for domain validation."""
    ok: bool
    compiled: Optional[List[Any]] = None
    errors: List[str] = Field(default_factory=list)
    hints: List[str] = Field(default_factory=list)


class DomainValidator:
    """Validates and compiles Odoo domain expressions."""

    def __init__(self, schema_introspector):
        """
        Initialize the domain validator.
        
        Args:
            schema_introspector: SchemaIntrospector instance for field validation
        """
        self.schema_introspector = schema_introspector
        self._field_cache = {}  # Cache field types per model

    async def validate_domain(
        self, 
        model: str, 
        domain_json: Dict[str, Any], 
        user_id: int
    ) -> DomainValidationResponse:
        """
        Validate and compile a domain expression.
        
        Args:
            model: Odoo model name
            domain_json: Domain expression in JSON format
            user_id: User ID for access control
            
        Returns:
            DomainValidationResponse: Validation result
        """
        try:
            # Get model fields for validation
            fields = await self.schema_introspector.list_fields(user_id, model)
            self._field_cache[model] = fields
            
            # Validate domain structure
            validation_result = self._validate_domain_structure(domain_json)
            if not validation_result["ok"]:
                return DomainValidationResponse(
                    ok=False,
                    errors=validation_result["errors"]
                )
            
            # Compile domain
            compiled_domain = self._compile_domain(domain_json, model)
            
            return DomainValidationResponse(
                ok=True,
                compiled=compiled_domain,
                hints=validation_result.get("hints", [])
            )
            
        except Exception as e:
            logger.error(f"Error validating domain for model {model}: {e}")
            return DomainValidationResponse(
                ok=False,
                errors=[f"Validation error: {str(e)}"]
            )

    def _validate_domain_structure(self, domain: Any, depth: int = 0) -> Dict[str, Any]:
        """
        Validate domain structure recursively.
        
        Args:
            domain: Domain expression to validate
            depth: Current recursion depth
            
        Returns:
            Dict with validation result
        """
        if depth > MAX_DOMAIN_DEPTH:
            return {
                "ok": False,
                "errors": [f"Domain depth exceeds maximum ({MAX_DOMAIN_DEPTH})"]
            }
        
        # Check domain size
        domain_str = json.dumps(domain)
        if len(domain_str) > MAX_DOMAIN_SIZE:
            return {
                "ok": False,
                "errors": [f"Domain size exceeds maximum ({MAX_DOMAIN_SIZE} characters)"]
            }
        
        if isinstance(domain, dict):
            # Logical operator
            if len(domain) != 1:
                return {
                    "ok": False,
                    "errors": ["Logical operators must have exactly one key"]
                }
            
            operator = list(domain.keys())[0]
            if operator not in LOGICAL_OPERATORS:
                return {
                    "ok": False,
                    "errors": [f"Unknown logical operator: {operator}"]
                }
            
            value = domain[operator]
            if operator == "not":
                # NOT operator expects a single domain
                if not isinstance(value, (dict, list)) or len(value) != 3:
                    return {
                        "ok": False,
                        "errors": ["NOT operator expects a single domain condition"]
                    }
                return self._validate_domain_structure(value, depth + 1)
            else:
                # AND/OR operators expect a list of domains
                if not isinstance(value, list):
                    return {
                        "ok": False,
                        "errors": [f"{operator.upper()} operator expects a list of domains"]
                    }
                
                for subdomain in value:
                    result = self._validate_domain_structure(subdomain, depth + 1)
                    if not result["ok"]:
                        return result
                
                return {"ok": True, "hints": [f"Valid {operator.upper()} domain"]}
        
        elif isinstance(domain, list):
            # Domain condition: [field, operator, value]
            if len(domain) != 3:
                return {
                    "ok": False,
                    "errors": ["Domain condition must have exactly 3 elements: [field, operator, value]"]
                }
            
            field, operator, value = domain
            
            # Validate field name
            if not isinstance(field, str):
                return {
                    "ok": False,
                    "errors": ["Field name must be a string"]
                }
            
            # Validate operator
            if operator not in ALLOWED_OPERATORS:
                return {
                    "ok": False,
                    "errors": [f"Unknown operator: {operator}. Allowed: {', '.join(ALLOWED_OPERATORS)}"]
                }
            
            # Validate value (basic checks)
            if not self._is_valid_value(value):
                return {
                    "ok": False,
                    "errors": [f"Invalid value type for operator {operator}"]
                }
            
            return {"ok": True, "hints": [f"Valid condition: {field} {operator} {value}"]}
        
        else:
            return {
                "ok": False,
                "errors": ["Domain must be a dictionary or list"]
            }

    def _is_valid_value(self, value: Any) -> bool:
        """
        Check if a value is valid for domain conditions.
        
        Args:
            value: Value to validate
            
        Returns:
            bool: True if value is valid
        """
        if value is None:
            return True
        
        if isinstance(value, (str, int, float, bool, list, tuple)):
            return True
        
        # Check for special values
        if isinstance(value, str) and value in SPECIAL_VALUES:
            return True
        
        return False

    def _compile_domain(self, domain: Any, model: str) -> List[Any]:
        """
        Compile domain to Odoo format.
        
        Args:
            domain: Domain expression
            model: Model name for field validation
            
        Returns:
            List: Compiled domain in Odoo format
        """
        if isinstance(domain, dict):
            operator = list(domain.keys())[0]
            value = domain[operator]
            
            if operator == "and":
                # Convert to Odoo & operator
                compiled = []
                for subdomain in value:
                    compiled.extend(self._compile_domain(subdomain, model))
                return compiled
            
            elif operator == "or":
                # Convert to Odoo | operator
                compiled = []
                for i, subdomain in enumerate(value):
                    if i > 0:
                        compiled.append("|")
                    compiled.extend(self._compile_domain(subdomain, model))
                return compiled
            
            elif operator == "not":
                # Convert to Odoo ! operator
                compiled = ["!"]
                compiled.extend(self._compile_domain(value, model))
                return compiled
        
        elif isinstance(domain, list):
            field, operator, value = domain
            
            # Expand special values
            expanded_value = self._expand_special_value(value)
            
            # Validate field exists in model
            if model in self._field_cache:
                fields = self._field_cache[model]
                if field not in fields:
                    logger.warning(f"Field {field} not found in model {model}")
            
            return [field, operator, expanded_value]
        
        return domain

    def _expand_special_value(self, value: Any) -> Any:
        """
        Expand special values like __today__, __current_user_id__, etc.
        
        Args:
            value: Value to expand
            
        Returns:
            Any: Expanded value
        """
        if not isinstance(value, str):
            return value
        
        if value == "__today__":
            return date.today()
        
        elif value == "__yesterday__":
            return date.today() - timedelta(days=1)
        
        elif value == "__tomorrow__":
            return date.today() + timedelta(days=1)
        
        elif value == "__start_of_month__":
            today = date.today()
            return today.replace(day=1)
        
        elif value == "__start_of_year__":
            today = date.today()
            return today.replace(month=1, day=1)
        
        elif value == "__current_month__":
            return date.today().month
        
        elif value == "__current_year__":
            return date.today().year
        
        elif value == "__current_user_id__":
            # This will be replaced by the actual user ID at runtime
            return value
        
        elif value == "__current_company_ids__":
            # This will be replaced by the actual company IDs at runtime
            return value
        
        return value

    def get_implicit_company_domain(self, model: str) -> List[Any]:
        """
        Get implicit company domain for multi-company models.
        
        Args:
            model: Model name
            
        Returns:
            List: Company domain or empty list
        """
        if model in self._field_cache:
            fields = self._field_cache[model]
            if "company_id" in fields:
                return [("company_id", "in", "__current_company_ids__")]
        
        return []

    def get_implicit_user_domain(self, model: str) -> List[Any]:
        """
        Get implicit user domain for user-specific models.
        
        Args:
            model: Model name
            
        Returns:
            List: User domain or empty list
        """
        if model in self._field_cache:
            fields = self._field_cache[model]
            if "user_id" in fields:
                return [("user_id", "=", "__current_user_id__")]
        
        return []


class DomainPresets:
    """Common domain presets for typical use cases."""
    
    @staticmethod
    def active_records() -> Dict[str, Any]:
        """Get domain for active records."""
        return {"and": [["active", "=", True]]}
    
    @staticmethod
    def this_month() -> Dict[str, Any]:
        """Get domain for records created this month."""
        return {"and": [["create_date", ">=", "__start_of_month__"]]}
    
    @staticmethod
    def this_year() -> Dict[str, Any]:
        """Get domain for records created this year."""
        return {"and": [["create_date", ">=", "__start_of_year__"]]}
    
    @staticmethod
    def my_records() -> Dict[str, Any]:
        """Get domain for user's own records."""
        return {"and": [["user_id", "=", "__current_user_id__"]]}
    
    @staticmethod
    def my_company() -> Dict[str, Any]:
        """Get domain for current company records."""
        return {"and": [["company_id", "in", "__current_company_ids__"]]}
    
    @staticmethod
    def draft_state() -> Dict[str, Any]:
        """Get domain for draft state records."""
        return {"and": [["state", "=", "draft"]]}
    
    @staticmethod
    def confirmed_state() -> Dict[str, Any]:
        """Get domain for confirmed state records."""
        return {"and": [["state", "=", "confirmed"]]}
