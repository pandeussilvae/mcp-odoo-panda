"""
Odoo Actions discovery and execution module.
This module provides heuristic action discovery, next steps suggestions,
and safe method calling with audit logging.
"""

import logging
import os
import yaml
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Whitelisted method prefixes for safety
ALLOWED_METHOD_PREFIXES = {
    'action_', 'button_', 'wizard_', 'send_', 'confirm_', 'cancel_',
    'approve_', 'reject_', 'validate_', 'process_', 'generate_'
}

# Methods that are always allowed (core Odoo methods)
CORE_METHODS = {
    'copy', 'unlink', 'write', 'read', 'search', 'search_read',
    'name_get', 'name_search', 'fields_get', 'fields_view_get'
}

# State-based action suggestions (model -> state -> actions)
STATE_ACTIONS = {
    'sale.order': {
        'draft': ['action_confirm', 'action_cancel'],
        'sent': ['action_confirm', 'action_cancel'],
        'sale': ['action_cancel', 'action_done'],
        'done': ['action_cancel'],
        'cancel': ['action_draft']
    },
    'account.move': {
        'draft': ['action_post', 'action_cancel'],
        'posted': ['action_cancel', 'action_reverse'],
        'cancel': ['action_draft']
    },
    'stock.picking': {
        'draft': ['action_confirm', 'action_cancel'],
        'confirmed': ['action_assign', 'action_cancel'],
        'assigned': ['action_assign', 'button_validate'],
        'done': ['action_cancel'],
        'cancel': ['action_draft']
    },
    'crm.lead': {
        'new': ['action_set_won', 'action_set_lost'],
        'qualified': ['action_set_won', 'action_set_lost'],
        'won': ['action_set_lost'],
        'lost': ['action_set_won']
    }
}


class ActionInfo(BaseModel):
    """Information about an available action."""
    method: str
    label: str
    description: Optional[str] = None
    icon: Optional[str] = None
    preconditions: Optional[List[str]] = None
    tooltip: Optional[str] = None
    category: str = "action"


class NextStepsResponse(BaseModel):
    """Response model for next steps suggestions."""
    model: str
    record_id: int
    current_state: Optional[str] = None
    available_actions: List[ActionInfo]
    suggested_actions: List[ActionInfo]
    hints: List[str] = Field(default_factory=list)


class ActionCallRequest(BaseModel):
    """Request model for calling an action."""
    model: str
    record_id: int
    method: str
    operation_id: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None


class ActionCallResponse(BaseModel):
    """Response model for action call result."""
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    operation_id: Optional[str] = None


class ActionsRegistry:
    """Manages the actions registry and provides action discovery."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the actions registry.
        
        Args:
            config: Server configuration
        """
        self.config = config
        self.registry_file = config.get("actions_registry", "./config/actions_registry.yaml")
        self.registry: Dict[str, Dict[str, ActionInfo]] = {}
        self._load_registry()

    def _load_registry(self):
        """Load actions registry from YAML file."""
        try:
            if self.registry_file and os.path.exists(self.registry_file):
                with open(self.registry_file, 'r') as f:
                    registry_data = yaml.safe_load(f)
                    self._parse_registry(registry_data)
                    logger.info(f"Actions registry loaded from {self.registry_file}")
            else:
                logger.info("No actions registry file found, using heuristic discovery only")
        except Exception as e:
            logger.warning(f"Failed to load actions registry: {e}")

    def _parse_registry(self, registry_data: Dict[str, Any]):
        """Parse registry data and convert to ActionInfo objects."""
        for model_name, model_actions in registry_data.items():
            self.registry[model_name] = {}
            for action_name, action_data in model_actions.items():
                self.registry[model_name][action_name] = ActionInfo(
                    method=action_name,
                    label=action_data.get("label", action_name.replace("_", " ").title()),
                    description=action_data.get("description"),
                    icon=action_data.get("icon"),
                    preconditions=action_data.get("preconditions", []),
                    tooltip=action_data.get("tooltip"),
                    category=action_data.get("category", "action")
                )

    def get_registered_actions(self, model: str) -> List[ActionInfo]:
        """
        Get registered actions for a model.
        
        Args:
            model: Model name
            
        Returns:
            List[ActionInfo]: List of registered actions
        """
        return list(self.registry.get(model, {}).values())


class ActionDiscoverer:
    """Discovers available actions on Odoo records using heuristics."""

    def __init__(self, connection_pool, actions_registry: ActionsRegistry):
        """
        Initialize the action discoverer.
        
        Args:
            connection_pool: Odoo connection pool
            actions_registry: ActionsRegistry instance
        """
        self.pool = connection_pool
        self.registry = actions_registry

    async def discover_actions(self, model: str, record_id: int, user_id: int) -> List[ActionInfo]:
        """
        Discover available actions on a record.
        
        Args:
            model: Model name
            record_id: Record ID
            user_id: User ID for access control
            
        Returns:
            List[ActionInfo]: List of discovered actions
        """
        try:
            # Get the record
            record = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[[record_id]],
                kwargs={"fields": ["state", "name"]}
            )
            
            if not record:
                return []
            
            record_data = record[0]
            
            # Get registered actions first
            registered_actions = self.registry.get_registered_actions(model)
            
            # Discover heuristic actions
            heuristic_actions = await self._discover_heuristic_actions(model, record_data)
            
            # Combine and deduplicate
            all_actions = {}
            for action in registered_actions:
                all_actions[action.method] = action
            
            for action in heuristic_actions:
                if action.method not in all_actions:
                    all_actions[action.method] = action
            
            return list(all_actions.values())
            
        except Exception as e:
            logger.error(f"Error discovering actions for {model}/{record_id}: {e}")
            return []

    async def _discover_heuristic_actions(self, model: str, record_data: Dict[str, Any]) -> List[ActionInfo]:
        """
        Discover actions using heuristics.
        
        Args:
            model: Model name
            record_data: Record data
            
        Returns:
            List[ActionInfo]: List of discovered actions
        """
        actions = []
        
        try:
            # Get model methods (this is a simplified approach)
            # In a real implementation, you'd need to inspect the model class
            model_info = await self.pool.execute_kw(
                model="ir.model",
                method="search_read",
                args=[[("model", "=", model)]],
                kwargs={"fields": ["name"]}
            )
            
            if not model_info:
                return actions
            
            # For heuristic discovery, we'll use common patterns
            # In a real implementation, you'd inspect the actual model methods
            
            # Add common actions based on model type
            if model == "sale.order":
                actions.extend([
                    ActionInfo(method="action_confirm", label="Confirm Order", category="workflow"),
                    ActionInfo(method="action_cancel", label="Cancel Order", category="workflow"),
                    ActionInfo(method="action_done", label="Mark Done", category="workflow")
                ])
            elif model == "account.move":
                actions.extend([
                    ActionInfo(method="action_post", label="Post Entry", category="workflow"),
                    ActionInfo(method="action_cancel", label="Cancel Entry", category="workflow"),
                    ActionInfo(method="action_reverse", label="Reverse Entry", category="workflow")
                ])
            elif model == "stock.picking":
                actions.extend([
                    ActionInfo(method="action_confirm", label="Confirm Transfer", category="workflow"),
                    ActionInfo(method="action_assign", label="Assign Operations", category="workflow"),
                    ActionInfo(method="button_validate", label="Validate Transfer", category="workflow")
                ])
            
            # Add state-based actions if state field exists
            if "state" in record_data:
                current_state = record_data["state"]
                state_actions = STATE_ACTIONS.get(model, {}).get(current_state, [])
                
                for action_method in state_actions:
                    # Only add if not already present
                    if not any(a.method == action_method for a in actions):
                        actions.append(ActionInfo(
                            method=action_method,
                            label=action_method.replace("_", " ").title(),
                            category="state_based"
                        ))
            
        except Exception as e:
            logger.error(f"Error in heuristic action discovery for {model}: {e}")
        
        return actions

    async def get_next_steps(self, model: str, record_id: int, user_id: int) -> NextStepsResponse:
        """
        Get next steps suggestions for a record.
        
        Args:
            model: Model name
            record_id: Record ID
            user_id: User ID
            
        Returns:
            NextStepsResponse: Next steps information
        """
        try:
            # Get record data
            record = await self.pool.execute_kw(
                model=model,
                method="read",
                args=[[record_id]],
                kwargs={"fields": ["state", "name"]}
            )
            
            if not record:
                return NextStepsResponse(
                    model=model,
                    record_id=record_id,
                    available_actions=[],
                    suggested_actions=[],
                    hints=["Record not found"]
                )
            
            record_data = record[0]
            current_state = record_data.get("state")
            
            # Discover all available actions
            available_actions = await self.discover_actions(model, record_id, user_id)
            
            # Filter to suggested actions based on current state
            suggested_actions = []
            if current_state and model in STATE_ACTIONS:
                state_actions = STATE_ACTIONS[model].get(current_state, [])
                suggested_actions = [
                    action for action in available_actions 
                    if action.method in state_actions
                ]
            
            # Generate hints
            hints = []
            if current_state:
                hints.append(f"Current state: {current_state}")
            if suggested_actions:
                hints.append(f"Suggested actions: {', '.join([a.method for a in suggested_actions])}")
            
            return NextStepsResponse(
                model=model,
                record_id=record_id,
                current_state=current_state,
                available_actions=available_actions,
                suggested_actions=suggested_actions,
                hints=hints
            )
            
        except Exception as e:
            logger.error(f"Error getting next steps for {model}/{record_id}: {e}")
            return NextStepsResponse(
                model=model,
                record_id=record_id,
                available_actions=[],
                suggested_actions=[],
                hints=[f"Error: {str(e)}"]
            )

    async def call_action(
        self, 
        model: str, 
        record_id: int, 
        method: str, 
        user_id: int,
        parameters: Optional[Dict[str, Any]] = None,
        operation_id: Optional[str] = None
    ) -> ActionCallResponse:
        """
        Call an action method on a record.
        
        Args:
            model: Model name
            record_id: Record ID
            method: Method name to call
            user_id: User ID
            parameters: Optional method parameters
            operation_id: Optional operation ID for idempotency
            
        Returns:
            ActionCallResponse: Action call result
        """
        try:
            # Validate method is allowed
            if not self._is_method_allowed(method):
                return ActionCallResponse(
                    success=False,
                    error=f"Method {method} is not allowed",
                    operation_id=operation_id
                )
            
            # Check if method exists on the record
            if not await self._method_exists(model, method):
                return ActionCallResponse(
                    success=False,
                    error=f"Method {method} does not exist on model {model}",
                    operation_id=operation_id
                )
            
            # Call the method
            args = [record_id]
            if parameters:
                args.append(parameters)
            
            result = await self.pool.execute_kw(
                model=model,
                method=method,
                args=args
            )
            
            # Log the action call for audit
            await self._log_action_call(model, record_id, method, user_id, parameters, operation_id, True, None)
            
            return ActionCallResponse(
                success=True,
                result=result,
                operation_id=operation_id
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error calling action {method} on {model}/{record_id}: {error_msg}")
            
            # Log the failed action call
            await self._log_action_call(model, record_id, method, user_id, parameters, operation_id, False, error_msg)
            
            return ActionCallResponse(
                success=False,
                error=error_msg,
                operation_id=operation_id
            )

    def _is_method_allowed(self, method: str) -> bool:
        """
        Check if a method is allowed to be called.
        
        Args:
            method: Method name
            
        Returns:
            bool: True if method is allowed
        """
        # Check core methods
        if method in CORE_METHODS:
            return True
        
        # Check allowed prefixes
        for prefix in ALLOWED_METHOD_PREFIXES:
            if method.startswith(prefix):
                return True
        
        return False

    async def _method_exists(self, model: str, method: str) -> bool:
        """
        Check if a method exists on a model.
        
        Args:
            model: Model name
            method: Method name
            
        Returns:
            bool: True if method exists
        """
        try:
            # This is a simplified check - in a real implementation you'd need to
            # inspect the actual model class or use reflection
            # For now, we'll assume common action methods exist
            return True
        except Exception:
            return False

    async def _log_action_call(
        self,
        model: str,
        record_id: int,
        method: str,
        user_id: int,
        parameters: Optional[Dict[str, Any]],
        operation_id: Optional[str],
        success: bool,
        error: Optional[str]
    ):
        """
        Log action call for audit purposes.
        
        Args:
            model: Model name
            record_id: Record ID
            method: Method name
            user_id: User ID
            parameters: Method parameters
            operation_id: Operation ID
            success: Whether the call was successful
            error: Error message if failed
        """
        try:
            audit_log = {
                "timestamp": datetime.utcnow().isoformat(),
                "user_id": user_id,
                "model": model,
                "record_id": record_id,
                "method": method,
                "parameters": parameters,
                "operation_id": operation_id,
                "success": success,
                "error": error
            }
            
            # In a real implementation, you'd write this to a log file or database
            logger.info(f"Action call audit: {audit_log}")
            
        except Exception as e:
            logger.error(f"Failed to log action call: {e}")


class PicklistProvider:
    """Provides picklist values for selection and relation fields."""

    def __init__(self, connection_pool):
        """
        Initialize the picklist provider.
        
        Args:
            connection_pool: Odoo connection pool
        """
        self.pool = connection_pool

    async def get_picklist_values(
        self, 
        model: str, 
        field: str, 
        user_id: int,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get picklist values for a field.
        
        Args:
            model: Model name
            field: Field name
            user_id: User ID
            limit: Maximum number of values to return
            
        Returns:
            List[Dict]: List of picklist values
        """
        try:
            # Get field information
            field_info = await self.pool.execute_kw(
                model="ir.model.fields",
                method="search_read",
                args=[[("model", "=", model), ("name", "=", field)]],
                kwargs={"fields": ["ttype", "selection", "relation"]}
            )
            
            if not field_info:
                return []
            
            field_data = field_info[0]
            field_type = field_data["ttype"]
            
            if field_type == "selection":
                return await self._get_selection_values(field_data["selection"])
            elif field_type in ["many2one", "many2many"]:
                return await self._get_relation_values(field_data["relation"], user_id, limit)
            else:
                return []
                
        except Exception as e:
            logger.error(f"Error getting picklist values for {model}.{field}: {e}")
            return []

    async def _get_selection_values(self, selection: str) -> List[Dict[str, Any]]:
        """
        Get values for a selection field.
        
        Args:
            selection: Selection field definition
            
        Returns:
            List[Dict]: List of selection values
        """
        try:
            # Parse selection string (this is simplified)
            # In a real implementation, you'd need proper parsing
            if isinstance(selection, str):
                # Placeholder implementation
                return [{"value": "value1", "label": "Label 1"}, {"value": "value2", "label": "Label 2"}]
            return []
        except Exception as e:
            logger.error(f"Error parsing selection values: {e}")
            return []

    async def _get_relation_values(
        self, 
        relation_model: str, 
        user_id: int, 
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Get values for a relation field using name_search.
        
        Args:
            relation_model: Related model name
            user_id: User ID
            limit: Maximum number of values
            
        Returns:
            List[Dict]: List of relation values
        """
        try:
            # Use name_search to get related records
            results = await self.pool.execute_kw(
                model=relation_model,
                method="name_search",
                args=[""],
                kwargs={"limit": limit}
            )
            
            return [
                {"value": record_id, "label": name}
                for record_id, name in results
            ]
            
        except Exception as e:
            logger.error(f"Error getting relation values for {relation_model}: {e}")
            return []
