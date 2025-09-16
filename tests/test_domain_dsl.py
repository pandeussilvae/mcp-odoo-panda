"""Test domain DSL functionality."""

import pytest
from odoo_mcp.domain_dsl import DomainValidator, DomainPresets


class MockSchemaIntrospector:
    """Mock schema introspector for testing."""
    
    async def list_fields(self, user_id, model):
        return {
            "name": {"ttype": "char", "required": True},
            "company_id": {"ttype": "many2one", "relation": "res.company"},
            "state": {"ttype": "selection"},
            "create_date": {"ttype": "datetime"}
        }


@pytest.mark.asyncio
async def test_domain_validation_simple():
    """Test simple domain validation."""
    validator = DomainValidator(MockSchemaIntrospector())
    
    # Valid domain
    domain = ["name", "=", "Test"]
    result = await validator.validate_domain("res.partner", domain, 1)
    assert result.ok
    assert result.compiled == ["name", "=", "Test"]


@pytest.mark.asyncio
async def test_domain_validation_logical():
    """Test logical operator validation."""
    validator = DomainValidator(MockSchemaIntrospector())
    
    # Valid AND domain
    domain = {"and": [["name", "=", "Test"], ["state", "=", "active"]]}
    result = await validator.validate_domain("res.partner", domain, 1)
    assert result.ok
    assert "&" in result.compiled


@pytest.mark.asyncio
async def test_domain_presets():
    """Test domain presets."""
    # Test active records preset
    preset = DomainPresets.active_records()
    assert preset["and"] == [["active", "=", True]]
    
    # Test this month preset
    preset = DomainPresets.this_month()
    assert preset["and"] == [["create_date", ">=", "__start_of_month__"]]
