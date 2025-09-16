"""
Odoo Schema introspection and caching module.
This module provides dynamic model introspection, field discovery, and schema versioning
with user-specific access control and caching.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from cachetools import TTLCache
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Schema cache with TTL (default 10 minutes)
SCHEMA_CACHE_TTL = 600  # 10 minutes


class FieldInfo(BaseModel):
    """Field information model."""
    name: str
    ttype: str
    required: bool = False
    readonly: bool = False
    relation: Optional[str] = None
    selection: Optional[List[Tuple[str, str]]] = None
    domain: Optional[List] = None
    store: bool = True
    compute: Optional[str] = None
    writeable: bool = True

    def __post_init__(self):
        """Calculate writeable field after initialization."""
        self.writeable = not self.readonly and not self.compute


class ModelSchema(BaseModel):
    """Model schema information."""
    name: str
    fields: Dict[str, FieldInfo]
    access_rights: Dict[str, bool]  # create, read, write, delete
    record_rules: List[str] = Field(default_factory=list)


class SchemaVersion(BaseModel):
    """Schema version information."""
    version: str
    timestamp: datetime
    models_count: int
    fields_count: int


class SchemaIntrospector:
    """Handles Odoo model introspection and schema discovery."""

    def __init__(self, connection_pool, config: Dict[str, Any]):
        """
        Initialize the schema introspector.
        
        Args:
            connection_pool: Odoo connection pool
            config: Server configuration
        """
        self.pool = connection_pool
        self.config = config
        self.cache_ttl = config.get("schema_cache_ttl", SCHEMA_CACHE_TTL)
        
        # User-specific schema cache: {user_id: {model: ModelSchema}}
        self._schema_cache: Dict[int, TTLCache] = {}
        
        # Global schema version cache
        self._version_cache: TTLCache = TTLCache(maxsize=100, ttl=self.cache_ttl)

    def _get_user_cache(self, user_id: int) -> TTLCache:
        """Get or create user-specific cache."""
        if user_id not in self._schema_cache:
            self._schema_cache[user_id] = TTLCache(maxsize=1000, ttl=self.cache_ttl)
        return self._schema_cache[user_id]

    async def get_schema_version(self, user_id: int) -> SchemaVersion:
        """
        Get the current schema version for a user.
        
        Args:
            user_id: Odoo user ID
            
        Returns:
            SchemaVersion: Current schema version information
        """
        cache_key = f"version:{user_id}"
        
        # Check cache first
        if cache_key in self._version_cache:
            return self._version_cache[cache_key]
        
        try:
            # Get accessible models and their fields
            models = await self.list_models(user_id, with_access=True)
            total_fields = 0
            
            # Calculate hash from models and fields
            schema_data = {}
            for model_name in models:
                fields = await self.list_fields(user_id, model_name)
                schema_data[model_name] = {
                    "fields": [f.dict() for f in fields.values()],
                    "access": await self._get_model_access_rights(user_id, model_name)
                }
                total_fields += len(fields)
            
            # Generate deterministic hash
            payload = json.dumps(schema_data, sort_keys=True, separators=(',', ':'))
            version_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]
            
            version_info = SchemaVersion(
                version=version_hash,
                timestamp=datetime.utcnow(),
                models_count=len(models),
                fields_count=total_fields
            )
            
            # Cache the version
            self._version_cache[cache_key] = version_info
            return version_info
            
        except Exception as e:
            logger.error(f"Error getting schema version for user {user_id}: {e}")
            # Return a fallback version
            return SchemaVersion(
                version="unknown",
                timestamp=datetime.utcnow(),
                models_count=0,
                fields_count=0
            )

    async def list_models(self, user_id: int, with_access: bool = True) -> List[str]:
        """
        List accessible models for a user.
        
        Args:
            user_id: Odoo user ID
            with_access: Whether to filter by access rights
            
        Returns:
            List[str]: List of accessible model names
        """
        cache_key = f"models:{user_id}"
        user_cache = self._get_user_cache(user_id)
        
        # Check cache first
        if cache_key in user_cache:
            return user_cache[cache_key]
        
        try:
            # Get all models
            models = await self.pool.execute_kw(
                model="ir.model",
                method="search_read",
                args=[[("state", "=", "base")]],
                kwargs={"fields": ["model", "name"]}
            )
            
            model_names = [m["model"] for m in models]
            
            if with_access:
                # Filter by access rights
                accessible_models = []
                for model_name in model_names:
                    if await self._check_model_access(user_id, model_name):
                        accessible_models.append(model_name)
                model_names = accessible_models
            
            # Cache the result
            user_cache[cache_key] = model_names
            return model_names
            
        except Exception as e:
            logger.error(f"Error listing models for user {user_id}: {e}")
            return []

    async def list_fields(self, user_id: int, model_name: str) -> Dict[str, FieldInfo]:
        """
        List fields for a specific model.
        
        Args:
            user_id: Odoo user ID
            model_name: Name of the model
            
        Returns:
            Dict[str, FieldInfo]: Field information dictionary
        """
        cache_key = f"fields:{user_id}:{model_name}"
        user_cache = self._get_user_cache(user_id)
        
        # Check cache first
        if cache_key in user_cache:
            return user_cache[cache_key]
        
        try:
            # Get model fields
            model_info = await self.pool.execute_kw(
                model="ir.model.fields",
                method="search_read",
                args=[[("model", "=", model_name)]],
                kwargs={"fields": ["name", "ttype", "required", "readonly", "relation", "selection", "domain", "store", "compute"]}
            )
            
            fields = {}
            for field_info in model_info:
                # Handle selection fields
                selection = None
                if field_info.get("selection"):
                    try:
                        # Parse selection string to list of tuples
                        selection_str = field_info["selection"]
                        if isinstance(selection_str, str):
                            # This is a simplified parser - in real implementation you'd need more robust parsing
                            selection = [("value", "Label")]  # Placeholder
                    except:
                        selection = None
                
                field = FieldInfo(
                    name=field_info["name"],
                    ttype=field_info["ttype"],
                    required=field_info.get("required", False),
                    readonly=field_info.get("readonly", False),
                    relation=field_info.get("relation"),
                    selection=selection,
                    domain=field_info.get("domain"),
                    store=field_info.get("store", True),
                    compute=field_info.get("compute")
                )
                fields[field.name] = field
            
            # Cache the result
            user_cache[cache_key] = fields
            return fields
            
        except Exception as e:
            logger.error(f"Error listing fields for model {model_name} and user {user_id}: {e}")
            return {}

    async def _check_model_access(self, user_id: int, model_name: str) -> bool:
        """
        Check if user has access to a model.
        
        Args:
            user_id: Odoo user ID
            model_name: Name of the model
            
        Returns:
            bool: True if user has access
        """
        try:
            # Check ir.model.access
            access_rights = await self.pool.execute_kw(
                model="ir.model.access",
                method="search_read",
                args=[[("model_id.model", "=", model_name), ("group_id.users", "in", [user_id])]],
                kwargs={"fields": ["name", "perm_read", "perm_write", "perm_create", "perm_unlink"]}
            )
            
            if not access_rights:
                return False
            
            # Check if user has at least read access
            for access in access_rights:
                if access.get("perm_read"):
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking model access for {model_name} and user {user_id}: {e}")
            return False

    async def _get_model_access_rights(self, user_id: int, model_name: str) -> Dict[str, bool]:
        """
        Get detailed access rights for a model.
        
        Args:
            user_id: Odoo user ID
            model_name: Name of the model
            
        Returns:
            Dict[str, bool]: Access rights dictionary
        """
        try:
            access_rights = await self.pool.execute_kw(
                model="ir.model.access",
                method="search_read",
                args=[[("model_id.model", "=", model_name), ("group_id.users", "in", [user_id])]],
                kwargs={"fields": ["perm_read", "perm_write", "perm_create", "perm_unlink"]}
            )
            
            if not access_rights:
                return {"read": False, "write": False, "create": False, "delete": False}
            
            # Aggregate rights from all groups
            rights = {"read": False, "write": False, "create": False, "delete": False}
            for access in access_rights:
                rights["read"] |= access.get("perm_read", False)
                rights["write"] |= access.get("perm_write", False)
                rights["create"] |= access.get("perm_create", False)
                rights["delete"] |= access.get("perm_unlink", False)
            
            return rights
            
        except Exception as e:
            logger.error(f"Error getting access rights for {model_name} and user {user_id}: {e}")
            return {"read": False, "write": False, "create": False, "delete": False}

    def invalidate_user_cache(self, user_id: int, model_name: Optional[str] = None):
        """
        Invalidate cache for a specific user and optionally a specific model.
        
        Args:
            user_id: Odoo user ID
            model_name: Optional model name to invalidate
        """
        if user_id in self._schema_cache:
            if model_name:
                # Invalidate specific model cache
                cache_keys = [k for k in self._schema_cache[user_id].keys() if k.startswith(f"fields:{user_id}:{model_name}")]
                for key in cache_keys:
                    del self._schema_cache[user_id][key]
            else:
                # Invalidate all user cache
                self._schema_cache[user_id].clear()

    def clear_all_caches(self):
        """Clear all schema caches."""
        self._schema_cache.clear()
        self._version_cache.clear()
        logger.info("All schema caches cleared")
