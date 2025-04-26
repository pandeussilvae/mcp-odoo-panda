import pytest
from unittest.mock import Mock, patch
from mcp.connection import MCPConnection
from mcp.config import MCPConfig

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
def mock_connection(mock_config):
    with patch('mcp.connection.requests.Session') as mock_session:
        mock_session.return_value = Mock()
        connection = MCPConnection(mock_config)
        yield connection

def test_connection_init(mock_config):
    connection = MCPConnection(mock_config)
    assert connection.config == mock_config
    assert connection.session is not None

def test_connection_headers(mock_connection):
    headers = mock_connection._get_headers()
    assert "Authorization" in headers
    assert headers["Authorization"] == "Bearer test_key"
    assert "Content-Type" in headers
    assert headers["Content-Type"] == "application/json"

def test_connection_url(mock_connection):
    url = mock_connection._get_url("/test/endpoint")
    assert url == "http://test_host:1234/test/endpoint"

def test_connection_request(mock_connection):
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": "test"}
    mock_connection.session.request.return_value = mock_response

    response = mock_connection.request("GET", "/test")
    
    mock_connection.session.request.assert_called_once()
    assert response == {"data": "test"}

def test_connection_request_error(mock_connection):
    mock_connection.session.request.side_effect = Exception("Connection error")
    
    with pytest.raises(Exception) as exc_info:
        mock_connection.request("GET", "/test")
    
    assert "Connection error" in str(exc_info.value)

def test_connection_retry(mock_connection):
    mock_response = Mock()
    mock_response.status_code = 500
    mock_connection.session.request.return_value = mock_response
    
    with pytest.raises(Exception) as exc_info:
        mock_connection.request("GET", "/test")
    
    assert mock_connection.session.request.call_count == 3  # max_retries + 1 