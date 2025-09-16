"""
Enhanced ORM security module for Odoo MCP.
This module provides implicit domain injection, PII masking, rate limiting,
and audit logging for secure ORM operations.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# PII field patterns for masking
PII_FIELD_PATTERNS = {
    'email': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    'phone': r'[\+]?[0-9\s\-\(\)]{8,}',
    'ssn': r'\d{3}-\d{2}-\d{4}',
    'credit_card': r'\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}'
}

# Fields that commonly contain PII
COMMON_PII_FIELDS = {
    'email', 'phone', 'mobile', 'fax', 'ssn', 'tax_id', 'vat',
    'credit_card', 'bank_account', 'passport', 'drivers_license'
}

# Rate limiting configuration
DEFAULT_RATE_LIMIT = 60  # requests per minute
DEFAULT_BURST_LIMIT = 100  # burst requests


class SecurityConfig(BaseModel):
    """Security configuration model."""
    pii_masking: bool = True
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT
    rate_limit_burst: int = DEFAULT_BURST_LIMIT
    audit_logging: bool = True
    implicit_domains: bool = True
    max_payload_size: int = 1024 * 1024  # 1MB
    max_fields_limit: int = 100
    max_records_limit: int = 200


class ImplicitDomainManager:
    """Manages implicit domain injection for security and multi-company support."""

    def __init__(self, schema_introspector):
        """
        Initialize the implicit domain manager.
        
        Args:
            schema_introspector: SchemaIntrospector instance
        """
        self.schema_introspector = schema_introspector

    async def get_implicit_domains(
        self, 
        model: str, 
        user_id: int,
        base_domain: Optional[List[Any]] = None
    ) -> List[Any]:
        """
        Get implicit domains to inject for security.
        
        Args:
            model: Model name
            user_id: User ID
            base_domain: Base domain to extend
            
        Returns:
            List: Extended domain with implicit security filters
        """
        implicit_domains = []
        
        try:
            # Get user information
            user_info = await self._get_user_info(user_id)
            if not user_info:
                return base_domain or []
            
            # Company domain (multi-company)
            if self._should_add_company_domain(model, user_info):
                company_domain = [("company_id", "in", user_info.get("company_ids", []))]
                implicit_domains.extend(company_domain)
            
            # User domain (user-specific records)
            if self._should_add_user_domain(model, user_info):
                user_domain = [("user_id", "=", user_id)]
                implicit_domains.extend(user_domain)
            
            # Record rules domain (if applicable)
            record_rules_domain = await self._get_record_rules_domain(model, user_id)
            if record_rules_domain:
                implicit_domains.extend(record_rules_domain)
            
            # Combine with base domain
            if base_domain:
                if implicit_domains:
                    # Use AND logic to combine
                    combined_domain = ["&"]
                    combined_domain.extend(base_domain)
                    combined_domain.extend(implicit_domains)
                    return combined_domain
                else:
                    return base_domain
            else:
                return implicit_domains
                
        except Exception as e:
            logger.error(f"Error getting implicit domains for {model}: {e}")
            return base_domain or []

    def _should_add_company_domain(self, model: str, user_info: Dict[str, Any]) -> bool:
        """Check if company domain should be added."""
        # Add company domain for multi-company models
        company_models = {
            'sale.order', 'purchase.order', 'account.move', 'stock.picking',
            'crm.lead', 'project.project', 'hr.employee'
        }
        return model in company_models and user_info.get("company_ids")

    def _should_add_user_domain(self, model: str, user_info: Dict[str, Any]) -> bool:
        """Check if user domain should be added."""
        # Add user domain for user-specific models
        user_models = {
            'mail.message', 'res.users.log', 'hr.attendance'
        }
        return model in user_models

    async def _get_user_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user information including company IDs."""
        try:
            user_data = await self.schema_introspector.pool.execute_kw(
                model="res.users",
                method="read",
                args=[[user_id]],
                kwargs={"fields": ["company_id", "company_ids"]}
            )
            
            if user_data:
                user = user_data[0]
                return {
                    "company_id": user.get("company_id"),
                    "company_ids": user.get("company_ids", [])
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting user info for {user_id}: {e}")
            return None

    async def _get_record_rules_domain(self, model: str, user_id: int) -> Optional[List[Any]]:
        """Get domain from record rules if applicable."""
        try:
            # This is a simplified implementation
            # In a real implementation, you'd need to query ir.rule
            return None
        except Exception as e:
            logger.error(f"Error getting record rules domain for {model}: {e}")
            return None


class PIIMasker:
    """Handles PII masking in responses."""

    def __init__(self, config: SecurityConfig):
        """
        Initialize the PII masker.
        
        Args:
            config: Security configuration
        """
        self.config = config
        self.pii_fields_cache = {}  # Cache PII fields per model

    def mask_record_data(
        self, 
        data: Dict[str, Any], 
        model: str,
        fields_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Mask PII data in a record.
        
        Args:
            data: Record data to mask
            model: Model name
            fields_info: Field information for the model
            
        Returns:
            Dict: Masked record data
        """
        if not self.config.pii_masking:
            return data
        
        masked_data = data.copy()
        
        try:
            # Get PII fields for this model
            pii_fields = self._get_pii_fields(model, fields_info)
            
            # Mask PII values
            for field, value in masked_data.items():
                if field in pii_fields and value:
                    masked_data[field] = self._mask_value(field, value)
            
            return masked_data
            
        except Exception as e:
            logger.error(f"Error masking PII data for {model}: {e}")
            return data

    def _get_pii_fields(self, model: str, fields_info: Optional[Dict[str, Any]]) -> Set[str]:
        """Get PII fields for a model."""
        if model in self.pii_fields_cache:
            return self.pii_fields_cache[model]
        
        pii_fields = set()
        
        if fields_info:
            for field_name, field_info in fields_info.items():
                if self._is_pii_field(field_name, field_info):
                    pii_fields.add(field_name)
        
        # Add common PII fields that might not be in fields_info
        pii_fields.update(COMMON_PII_FIELDS)
        
        self.pii_fields_cache[model] = pii_fields
        return pii_fields

    def _is_pii_field(self, field_name: str, field_info: Dict[str, Any]) -> bool:
        """Check if a field contains PII."""
        field_name_lower = field_name.lower()
        
        # Check field name patterns
        for pii_pattern in COMMON_PII_FIELDS:
            if pii_pattern in field_name_lower:
                return True
        
        # Check field type
        field_type = field_info.get("ttype", "")
        if field_type in ["char", "text"]:
            # Additional checks for text fields
            if any(pii_hint in field_name_lower for pii_hint in ["email", "phone", "id", "ssn"]):
                return True
        
        return False

    def _mask_value(self, field_name: str, value: Any) -> str:
        """Mask a PII value."""
        if not value:
            return value
        
        value_str = str(value)
        field_lower = field_name.lower()
        
        if "email" in field_lower:
            return self._mask_email(value_str)
        elif "phone" in field_lower or "mobile" in field_lower:
            return self._mask_phone(value_str)
        elif "ssn" in field_lower or "tax_id" in field_lower:
            return self._mask_ssn(value_str)
        elif "credit_card" in field_lower:
            return self._mask_credit_card(value_str)
        else:
            # Generic masking for other PII fields
            return self._generic_mask(value_str)

    def _mask_email(self, email: str) -> str:
        """Mask email address."""
        if "@" not in email:
            return email
        
        username, domain = email.split("@", 1)
        if len(username) <= 2:
            masked_username = username
        else:
            masked_username = username[0] + "*" * (len(username) - 2) + username[-1]
        
        return f"{masked_username}@{domain}"

    def _mask_phone(self, phone: str) -> str:
        """Mask phone number."""
        digits = "".join(filter(str.isdigit, phone))
        if len(digits) <= 4:
            return phone
        
        masked = "*" * (len(digits) - 4) + digits[-4:]
        return masked

    def _mask_ssn(self, ssn: str) -> str:
        """Mask SSN or tax ID."""
        if len(ssn) <= 4:
            return ssn
        
        masked = "*" * (len(ssn) - 4) + ssn[-4:]
        return masked

    def _mask_credit_card(self, card: str) -> str:
        """Mask credit card number."""
        digits = "".join(filter(str.isdigit, card))
        if len(digits) <= 4:
            return card
        
        masked = "*" * (len(digits) - 4) + digits[-4:]
        return masked

    def _generic_mask(self, value: str) -> str:
        """Generic masking for unknown PII fields."""
        if len(value) <= 2:
            return value
        
        return value[0] + "*" * (len(value) - 2) + value[-1]


class RateLimiter:
    """Enhanced rate limiter with per-user and per-IP tracking."""

    def __init__(self, config: SecurityConfig):
        """
        Initialize the rate limiter.
        
        Args:
            config: Security configuration
        """
        self.config = config
        self.user_limits = {}  # {user_id: {count: int, reset_time: float}}
        self.ip_limits = {}    # {ip: {count: int, reset_time: float}}
        self.global_limits = {"count": 0, "reset_time": time.time()}

    def check_rate_limit(
        self, 
        user_id: Optional[int] = None, 
        ip_address: Optional[str] = None
    ) -> bool:
        """
        Check if request is within rate limits.
        
        Args:
            user_id: User ID
            ip_address: IP address
            
        Returns:
            bool: True if request is allowed
        """
        current_time = time.time()
        
        # Check global limits
        if not self._check_global_limit(current_time):
            return False
        
        # Check user limits
        if user_id and not self._check_user_limit(user_id, current_time):
            return False
        
        # Check IP limits
        if ip_address and not self._check_ip_limit(ip_address, current_time):
            return False
        
        # Increment counters
        self._increment_counters(user_id, ip_address, current_time)
        
        return True

    def _check_global_limit(self, current_time: float) -> bool:
        """Check global rate limit."""
        if current_time > self.global_limits["reset_time"]:
            self.global_limits = {"count": 0, "reset_time": current_time + 60}
        
        return self.global_limits["count"] < self.config.rate_limit_burst

    def _check_user_limit(self, user_id: int, current_time: float) -> bool:
        """Check user-specific rate limit."""
        if user_id not in self.user_limits:
            self.user_limits[user_id] = {"count": 0, "reset_time": current_time + 60}
        
        user_limit = self.user_limits[user_id]
        if current_time > user_limit["reset_time"]:
            user_limit["count"] = 0
            user_limit["reset_time"] = current_time + 60
        
        return user_limit["count"] < self.config.rate_limit_per_minute

    def _check_ip_limit(self, ip_address: str, current_time: float) -> bool:
        """Check IP-specific rate limit."""
        if ip_address not in self.ip_limits:
            self.ip_limits[ip_address] = {"count": 0, "reset_time": current_time + 60}
        
        ip_limit = self.ip_limits[ip_address]
        if current_time > ip_limit["reset_time"]:
            ip_limit["count"] = 0
            ip_limit["reset_time"] = current_time + 60
        
        return ip_limit["count"] < self.config.rate_limit_per_minute

    def _increment_counters(
        self, 
        user_id: Optional[int], 
        ip_address: Optional[str], 
        current_time: float
    ):
        """Increment all relevant counters."""
        # Global counter
        self.global_limits["count"] += 1
        
        # User counter
        if user_id and user_id in self.user_limits:
            self.user_limits[user_id]["count"] += 1
        
        # IP counter
        if ip_address and ip_address in self.ip_limits:
            self.ip_limits[ip_address]["count"] += 1


class AuditLogger:
    """Structured audit logging for ORM operations."""

    def __init__(self, config: SecurityConfig):
        """
        Initialize the audit logger.
        
        Args:
            config: Security configuration
        """
        self.config = config
        self.logger = logging.getLogger("audit")

    def log_operation(
        self,
        operation: str,
        user_id: int,
        model: str,
        record_ids: Optional[List[int]] = None,
        domain: Optional[List[Any]] = None,
        values: Optional[Dict[str, Any]] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        latency_ms: Optional[float] = None,
        ip_address: Optional[str] = None
    ):
        """
        Log an ORM operation for audit purposes.
        
        Args:
            operation: Operation type (search_read, create, write, etc.)
            user_id: User ID performing the operation
            model: Model name
            record_ids: Record IDs involved
            domain: Search domain used
            values: Values written
            result: Operation result
            error: Error message if failed
            latency_ms: Operation latency in milliseconds
            ip_address: IP address of the request
        """
        if not self.config.audit_logging:
            return
        
        try:
            audit_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "operation": operation,
                "user_id": user_id,
                "model": model,
                "record_ids": record_ids,
                "domain": domain,
                "values_diff": self._get_values_diff(values) if values else None,
                "result_summary": self._summarize_result(result),
                "success": error is None,
                "error": error,
                "latency_ms": latency_ms,
                "ip_address": ip_address
            }
            
            # Log as structured JSON
            self.logger.info(json.dumps(audit_entry))
            
        except Exception as e:
            logger.error(f"Failed to log audit entry: {e}")

    def _get_values_diff(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Get a safe representation of values for audit."""
        if not values:
            return {}
        
        # Filter out sensitive fields
        safe_values = {}
        for key, value in values.items():
            if not self._is_sensitive_field(key):
                safe_values[key] = value
        
        return safe_values

    def _is_sensitive_field(self, field_name: str) -> bool:
        """Check if a field name suggests sensitive data."""
        sensitive_patterns = {
            'password', 'secret', 'key', 'token', 'credential',
            'ssn', 'tax_id', 'credit_card', 'bank_account'
        }
        
        field_lower = field_name.lower()
        return any(pattern in field_lower for pattern in sensitive_patterns)

    def _summarize_result(self, result: Any) -> Dict[str, Any]:
        """Create a summary of the operation result."""
        if result is None:
            return {"type": "none"}
        
        if isinstance(result, list):
            return {
                "type": "list",
                "count": len(result),
                "sample": result[:3] if len(result) > 3 else result
            }
        elif isinstance(result, dict):
            return {
                "type": "dict",
                "keys": list(result.keys()),
                "size": len(result)
            }
        else:
            return {
                "type": type(result).__name__,
                "value": str(result)[:100]  # Truncate long values
            }
