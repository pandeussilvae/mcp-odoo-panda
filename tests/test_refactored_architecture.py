"""
Comprehensive test suite for the refactored MCP Odoo architecture.
Tests the unified handler system, factory pattern, and core components.
"""

import asyncio
import json
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from odoo_mcp.core.handler_factory import HandlerFactory
from odoo_mcp.core.base_handler import BaseOdooHandler
from odoo_mcp.core.xmlrpc_handler import XMLRPCHandler
from odoo_mcp.core.jsonrpc_handler import JSONRPCHandler
from odoo_mcp.core.connection_pool import ConnectionPool
from odoo_mcp.error_handling.exceptions import (
    ConfigurationError,
    AuthError,
    NetworkError,
    OdooMCPError
)


class TestHandlerFactory:
    """Test the handler factory pattern."""
    
    @pytest.fixture
    def test_config(self):
        return {
            "odoo_url": "http://localhost:8069",
            "database": "test_db",
            "username": "test_user",
            "api_key": "test_password",
            "protocol": "xmlrpc"
        }
    
    def test_create_xmlrpc_handler(self, test_config):
        """Test XMLRPC handler creation."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            handler = HandlerFactory.create_handler("xmlrpc", test_config)
            assert isinstance(handler, XMLRPCHandler)
            assert handler.odoo_url == test_config["odoo_url"]
    
    def test_create_jsonrpc_handler(self, test_config):
        """Test JSONRPC handler creation."""
        test_config["protocol"] = "jsonrpc"
        with patch('httpx.AsyncClient'):
            handler = HandlerFactory.create_handler("jsonrpc", test_config)
            assert isinstance(handler, JSONRPCHandler)
            assert handler.odoo_url == test_config["odoo_url"]
    
    def test_unsupported_protocol(self, test_config):
        """Test unsupported protocol raises error."""
        with pytest.raises(ConfigurationError):
            HandlerFactory.create_handler("unsupported", test_config)
    
    def test_protocol_support_check(self):
        """Test protocol support checking."""
        assert HandlerFactory.is_protocol_supported("xmlrpc")
        assert HandlerFactory.is_protocol_supported("jsonrpc")
        assert not HandlerFactory.is_protocol_supported("unsupported")
    
    def test_supported_protocols_list(self):
        """Test getting supported protocols list."""
        protocols = HandlerFactory.get_supported_protocols()
        assert "xmlrpc" in protocols
        assert "jsonrpc" in protocols
        assert len(protocols) == 2
    
    def test_register_custom_handler(self):
        """Test registering a custom handler."""
        class CustomHandler(BaseOdooHandler):
            async def _perform_authentication(self, username, password, database):
                return True
            
            async def execute_kw(self, model, method, args=None, kwargs=None):
                return {}
            
            async def call(self, service, method, args):
                return {}
        
        HandlerFactory.register_handler("custom", CustomHandler)
        assert HandlerFactory.is_protocol_supported("custom")
        
        # Clean up
        HandlerFactory._handler_registry.pop("custom")


class TestBaseHandler:
    """Test the base handler functionality."""
    
    @pytest.fixture
    def test_config(self):
        return {
            "odoo_url": "http://localhost:8069",
            "database": "test_db",
            "username": "test_user",
            "api_key": "test_password"
        }
    
    def test_configuration_validation(self, test_config):
        """Test configuration validation."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            handler = XMLRPCHandler(test_config)
            
            assert handler.odoo_url == test_config["odoo_url"]
            assert handler.database == test_config["database"]
            assert handler.username == test_config["username"]
            assert handler.password == test_config["api_key"]
    
    def test_missing_required_config(self):
        """Test missing required configuration raises error."""
        config = {"odoo_url": "http://localhost:8069"}  # Missing required fields
        
        with pytest.raises(ConfigurationError):
            XMLRPCHandler(config)
    
    def test_hashable_conversion(self, test_config):
        """Test hashable conversion for caching."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            handler = XMLRPCHandler(test_config)
            
            test_data = {
                "list": [1, 2, 3],
                "dict": {"key": "value"},
                "string": "test",
                "int": 42
            }
            
            hashable = handler._make_hashable(test_data)
            assert isinstance(hashable, tuple)
            
            # Should be able to use as dictionary key
            cache = {hashable: "test_value"}
            assert cache[hashable] == "test_value"
    
    def test_read_method_detection(self, test_config):
        """Test read method detection."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            handler = XMLRPCHandler(test_config)
            
            # Read methods
            assert handler.is_read_method("object", "read")
            assert handler.is_read_method("object", "search")
            assert handler.is_read_method("object", "search_read")
            assert handler.is_read_method("object", "fields_get")
            
            # Write methods
            assert not handler.is_read_method("object", "write")
            assert not handler.is_read_method("object", "create")
            assert not handler.is_read_method("object", "unlink")
            
            # Common service
            assert not handler.is_read_method("common", "login")
            assert not handler.is_read_method("common", "version")


class TestXMLRPCHandler:
    """Test XMLRPC handler implementation."""
    
    @pytest.fixture
    def test_config(self):
        return {
            "odoo_url": "http://localhost:8069",
            "database": "test_db",
            "username": "test_user",
            "api_key": "test_password"
        }
    
    def test_xmlrpc_handler_creation(self, test_config):
        """Test XMLRPC handler creation."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy') as mock_proxy:
            mock_common = MagicMock()
            mock_models = MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]
            
            handler = XMLRPCHandler(test_config)
            
            assert handler.common == mock_common
            assert handler.models == mock_models
    
    @pytest.mark.asyncio
    async def test_authentication_success(self, test_config):
        """Test successful authentication."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy') as mock_proxy:
            mock_common = MagicMock()
            mock_common.authenticate.return_value = 123
            mock_models = MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]
            
            handler = XMLRPCHandler(test_config)
            
            result = await handler._perform_authentication(
                "user", "pass", "db"
            )
            assert result == 123
            mock_common.authenticate.assert_called_once_with("db", "user", "pass", {})
    
    @pytest.mark.asyncio
    async def test_authentication_failure(self, test_config):
        """Test authentication failure."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy') as mock_proxy:
            mock_common = MagicMock()
            mock_common.authenticate.side_effect = Exception("Connection refused")
            mock_models = MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]
            
            handler = XMLRPCHandler(test_config)
            
            with pytest.raises(AuthError):
                await handler._perform_authentication("user", "pass", "db")
    
    @pytest.mark.asyncio
    async def test_call_common_service(self, test_config):
        """Test calling common service methods."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy') as mock_proxy:
            mock_common = MagicMock()
            mock_common.version.return_value = "18.0"
            mock_models = MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]
            
            handler = XMLRPCHandler(test_config)
            
            with patch('asyncio.get_event_loop') as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(return_value="18.0")
                
                result = await handler.call("common", "version", [])
                assert result == "18.0"
    
    @pytest.mark.asyncio
    async def test_call_object_service(self, test_config):
        """Test calling object service methods."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy') as mock_proxy:
            mock_common = MagicMock()
            mock_models = MagicMock()
            mock_models.execute_kw.return_value = [{"id": 1, "name": "Test"}]
            mock_proxy.side_effect = [mock_common, mock_models]
            
            handler = XMLRPCHandler(test_config)
            
            with patch('asyncio.get_event_loop') as mock_loop:
                mock_loop.return_value.run_in_executor = AsyncMock(
                    return_value=[{"id": 1, "name": "Test"}]
                )
                
                result = await handler.call("object", "read", ["res.partner", [1], ["name"]])
                assert result == [{"id": 1, "name": "Test"}]
    
    @pytest.mark.asyncio
    async def test_call_unknown_service(self, test_config):
        """Test calling unknown service raises error."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy') as mock_proxy:
            mock_common = MagicMock()
            mock_models = MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]
            
            handler = XMLRPCHandler(test_config)
            
            with pytest.raises(OdooMCPError):
                await handler.call("unknown", "method", [])
    
    @pytest.mark.asyncio
    async def test_cleanup(self, test_config):
        """Test handler cleanup."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy') as mock_proxy:
            mock_common = MagicMock()
            mock_models = MagicMock()
            mock_proxy.side_effect = [mock_common, mock_models]
            
            handler = XMLRPCHandler(test_config)
            await handler.cleanup()
            
            mock_common.close.assert_called_once()
            mock_models.close.assert_called_once()


class TestJSONRPCHandler:
    """Test JSONRPC handler implementation."""
    
    @pytest.fixture
    def test_config(self):
        return {
            "odoo_url": "http://localhost:8069",
            "database": "test_db",
            "username": "test_user",
            "api_key": "test_password"
        }
    
    def test_jsonrpc_handler_creation(self, test_config):
        """Test JSONRPC handler creation."""
        with patch('httpx.AsyncClient'):
            handler = JSONRPCHandler(test_config)
            assert handler.odoo_url == test_config["odoo_url"]
            assert handler.database == test_config["database"]
    
    @pytest.mark.asyncio
    async def test_authentication_success(self, test_config):
        """Test successful authentication."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": 123}
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            
            handler = JSONRPCHandler(test_config)
            
            result = await handler._perform_authentication(
                "user", "pass", "db"
            )
            assert result == 123
    
    @pytest.mark.asyncio
    async def test_authentication_failure(self, test_config):
        """Test authentication failure."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"error": {"message": "Login failed"}}
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            
            handler = JSONRPCHandler(test_config)
            
            with pytest.raises(AuthError):
                await handler._perform_authentication("user", "pass", "db")
    
    @pytest.mark.asyncio
    async def test_call_success(self, test_config):
        """Test successful JSON-RPC call."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"result": {"data": "test"}}
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            
            handler = JSONRPCHandler(test_config)
            
            result = await handler.call("object", "read", ["res.partner", [1]])
            assert result == {"data": "test"}
    
    @pytest.mark.asyncio
    async def test_call_http_error(self, test_config):
        """Test HTTP error handling."""
        with patch('httpx.AsyncClient') as mock_client:
            # Mock response that raises HTTP error
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500 Internal Server Error",
                request=MagicMock(),
                response=mock_response
            )
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            
            handler = JSONRPCHandler(test_config)
            
            with pytest.raises(NetworkError):
                await handler.call("object", "read", ["res.partner", [1]])
    
    @pytest.mark.asyncio
    async def test_call_jsonrpc_error(self, test_config):
        """Test JSON-RPC error handling."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "error": {"code": -32601, "message": "Method not found"}
            }
            mock_client.return_value.post = AsyncMock(return_value=mock_response)
            
            handler = JSONRPCHandler(test_config)
            
            with pytest.raises(OdooMCPError):
                await handler.call("object", "invalid_method", [])
    
    @pytest.mark.asyncio
    async def test_cleanup(self, test_config):
        """Test handler cleanup."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_aclose = AsyncMock()
            mock_client.return_value.aclose = mock_aclose
            
            handler = JSONRPCHandler(test_config)
            await handler.cleanup()
            
            mock_aclose.assert_called_once()


class TestConnectionPool:
    """Test connection pool functionality."""
    
    @pytest.fixture
    def test_config(self):
        return {
            "odoo_url": "http://localhost:8069",
            "database": "test_db",
            "username": "test_user",
            "api_key": "test_password",
            "max_connections": 5,
            "connection_timeout": 30
        }
    
    def test_connection_pool_creation(self, test_config):
        """Test connection pool creation."""
        pool = ConnectionPool(test_config, HandlerFactory.create_handler)
        
        assert pool.max_size == 5
        assert pool.timeout == 30
        assert len(pool.connections) == 0
    
    @pytest.mark.asyncio
    async def test_get_connection_creates_new(self, test_config):
        """Test getting a connection creates a new one."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            pool = ConnectionPool(test_config, HandlerFactory.create_handler)
            
            connection = await pool.get_connection()
            assert connection is not None
            assert len(pool.connections) == 1
            assert connection.in_use is True
    
    @pytest.mark.asyncio
    async def test_get_connection_reuses_existing(self, test_config):
        """Test getting a connection reuses existing available one."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            pool = ConnectionPool(test_config, HandlerFactory.create_handler)
            
            # Get first connection
            conn1 = await pool.get_connection()
            
            # Release it
            await pool.release_connection(conn1.connection)
            
            # Get second connection (should reuse)
            conn2 = await pool.get_connection()
            
            assert conn1 is conn2
            assert len(pool.connections) == 1
    
    @pytest.mark.asyncio
    async def test_max_connections_limit(self, test_config):
        """Test maximum connections limit."""
        test_config["max_connections"] = 2
        
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            pool = ConnectionPool(test_config, HandlerFactory.create_handler)
            
            # Get max connections
            conn1 = await pool.get_connection()
            conn2 = await pool.get_connection()
            
            assert len(pool.connections) == 2
            
            # Try to get another (should fail)
            with pytest.raises(Exception):  # PoolTimeoutError
                await pool.get_connection()
    
    @pytest.mark.asyncio
    async def test_close_all_connections(self, test_config):
        """Test closing all connections."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            pool = ConnectionPool(test_config, HandlerFactory.create_handler)
            
            # Create some connections
            conn1 = await pool.get_connection()
            conn2 = await pool.get_connection()
            
            assert len(pool.connections) == 2
            
            # Close all
            await pool.close_all()
            
            assert len(pool.connections) == 0


class TestErrorHandling:
    """Test error handling and exceptions."""
    
    def test_base_exception(self):
        """Test base OdooMCPError."""
        error = OdooMCPError("Test error", code=-32000)
        
        assert error.message == "Test error"
        assert error.code == -32000
        assert str(error) == "Test error"
    
    def test_specific_exceptions(self):
        """Test specific exception types."""
        auth_error = AuthError("Authentication failed")
        assert auth_error.code == -32001
        
        config_error = ConfigurationError("Configuration issue")
        assert config_error.code == -32004
        
        network_error = NetworkError("Network issue")
        assert network_error.code == -32002
    
    def test_jsonrpc_error_conversion(self):
        """Test JSON-RPC error conversion."""
        error = OdooMCPError("Test error", code=-32000)
        jsonrpc_error = error.to_jsonrpc_error()
        
        assert jsonrpc_error["code"] == -32000
        assert jsonrpc_error["message"] == "Test error"
        assert "exception" in jsonrpc_error["data"]
        assert jsonrpc_error["data"]["exception"] == "OdooMCPError"
    
    def test_error_with_original_exception(self):
        """Test error with original exception."""
        original = ValueError("Original error")
        error = OdooMCPError("Wrapper error", original_exception=original)
        
        jsonrpc_error = error.to_jsonrpc_error()
        assert "original_exception" in jsonrpc_error["data"]
        assert "Original error" in jsonrpc_error["data"]["original_exception"]


class TestIntegration:
    """Integration tests for the refactored architecture."""
    
    @pytest.fixture
    def test_config(self):
        return {
            "odoo_url": "http://localhost:8069",
            "database": "test_db",
            "username": "test_user",
            "api_key": "test_password",
            "protocol": "xmlrpc",
            "max_connections": 3
        }
    
    @pytest.mark.asyncio
    async def test_factory_with_pool_integration(self, test_config):
        """Test factory pattern integration with connection pool."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'):
            # Create pool with factory
            pool = ConnectionPool(test_config, HandlerFactory.create_handler)
            
            # Get connection (should create handler via factory)
            connection = await pool.get_connection()
            
            assert connection.connection is not None
            assert isinstance(connection.connection, XMLRPCHandler)
            assert connection.connection.odoo_url == test_config["odoo_url"]
    
    @pytest.mark.asyncio
    async def test_protocol_switching(self, test_config):
        """Test switching between protocols."""
        with patch('odoo_mcp.core.xmlrpc_handler.ServerProxy'), \
             patch('httpx.AsyncClient'):
            
            # Test XMLRPC
            xmlrpc_handler = HandlerFactory.create_handler("xmlrpc", test_config)
            assert isinstance(xmlrpc_handler, XMLRPCHandler)
            
            # Test JSONRPC
            test_config["protocol"] = "jsonrpc"
            jsonrpc_handler = HandlerFactory.create_handler("jsonrpc", test_config)
            assert isinstance(jsonrpc_handler, JSONRPCHandler)
    
    def test_configuration_validation_across_handlers(self, test_config):
        """Test configuration validation works across different handlers."""
        # Remove required field
        invalid_config = test_config.copy()
        del invalid_config["database"]
        
        with pytest.raises(ConfigurationError):
            HandlerFactory.create_handler("xmlrpc", invalid_config)
        
        with pytest.raises(ConfigurationError):
            HandlerFactory.create_handler("jsonrpc", invalid_config)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
