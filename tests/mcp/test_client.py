import pytest
from unittest.mock import Mock, patch, AsyncMock
from mcp.client import MCPClient
from mcp.config import MCPConfig
from mcp.types import Resource, ResourceType

@pytest.fixture
def mock_config():
    return MCPConfig(
        host="test_host",
        port=1234,
        api_key="test_key",
        timeout=30,
        max_retries=3
    )

@pytest.fixture
def mock_connection():
    with patch('mcp.client.MCPConnection') as mock_conn:
        mock_conn.return_value = Mock()
        yield mock_conn

@pytest.fixture
def client(mock_config, mock_connection):
    return MCPClient(mock_config)

def test_client_init(mock_config):
    client = MCPClient(mock_config)
    assert client.config == mock_config
    assert client.connection is not None

def test_client_get_resource(client, mock_connection):
    mock_response = {
        "uri": "test://resource/1",
        "type": "record",
        "data": {"id": 1, "name": "Test"},
        "mime_type": "application/json"
    }
    mock_connection.return_value.request.return_value = mock_response

    resource = client.get_resource("test://resource/1")
    
    assert isinstance(resource, Resource)
    assert resource.uri == "test://resource/1"
    assert resource.type == ResourceType.RECORD
    assert resource.data == {"id": 1, "name": "Test"}
    assert resource.mime_type == "application/json"

def test_client_get_resource_list(client, mock_connection):
    mock_response = {
        "uri": "test://resource/list",
        "type": "list",
        "data": [
            {"id": 1, "name": "Test 1"},
            {"id": 2, "name": "Test 2"}
        ],
        "mime_type": "application/json"
    }
    mock_connection.return_value.request.return_value = mock_response

    resource = client.get_resource_list("test://resource/list")
    
    assert isinstance(resource, Resource)
    assert resource.uri == "test://resource/list"
    assert resource.type == ResourceType.LIST
    assert len(resource.data) == 2
    assert resource.mime_type == "application/json"

def test_client_get_binary_resource(client, mock_connection):
    mock_response = {
        "uri": "test://resource/binary/1",
        "type": "binary",
        "data": b"test binary data",
        "mime_type": "application/octet-stream"
    }
    mock_connection.return_value.request.return_value = mock_response

    resource = client.get_binary_resource("test://resource/binary/1")
    
    assert isinstance(resource, Resource)
    assert resource.uri == "test://resource/binary/1"
    assert resource.type == ResourceType.BINARY
    assert resource.data == b"test binary data"
    assert resource.mime_type == "application/octet-stream"

def test_client_create_resource(client, mock_connection):
    mock_response = {
        "uri": "test://resource/new",
        "type": "record",
        "data": {"id": 1, "name": "New Resource"},
        "mime_type": "application/json"
    }
    mock_connection.return_value.request.return_value = mock_response

    resource = client.create_resource("test://resource", {"name": "New Resource"})
    
    assert isinstance(resource, Resource)
    assert resource.uri == "test://resource/new"
    assert resource.type == ResourceType.RECORD
    assert resource.data == {"id": 1, "name": "New Resource"}
    assert resource.mime_type == "application/json"

def test_client_update_resource(client, mock_connection):
    mock_response = {
        "uri": "test://resource/1",
        "type": "record",
        "data": {"id": 1, "name": "Updated Resource"},
        "mime_type": "application/json"
    }
    mock_connection.return_value.request.return_value = mock_response

    resource = client.update_resource("test://resource/1", {"name": "Updated Resource"})
    
    assert isinstance(resource, Resource)
    assert resource.uri == "test://resource/1"
    assert resource.type == ResourceType.RECORD
    assert resource.data == {"id": 1, "name": "Updated Resource"}
    assert resource.mime_type == "application/json"

def test_client_delete_resource(client, mock_connection):
    mock_connection.return_value.request.return_value = {"success": True}
    
    result = client.delete_resource("test://resource/1")
    
    assert result == {"success": True}
    mock_connection.return_value.request.assert_called_once_with(
        "DELETE",
        "/resource/1"
    )

def test_client_error_handling(client, mock_connection):
    mock_connection.return_value.request.side_effect = Exception("API Error")
    
    with pytest.raises(Exception) as exc_info:
        client.get_resource("test://resource/1")
    
    assert "API Error" in str(exc_info.value) 