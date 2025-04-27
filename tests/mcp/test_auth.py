import pytest
from unittest.mock import Mock, patch
from mcp_local_backup.auth import MCPAuth, AuthError

@pytest.fixture
def mock_config():
    return Mock(
        api_key="test_key",
        timeout=30
    )

@pytest.fixture
def auth(mock_config):
    return MCPAuth(mock_config)

def test_auth_init(mock_config):
    auth = MCPAuth(mock_config)
    assert auth.config == mock_config

def test_auth_validate_token(auth):
    # Test valid token
    assert auth.validate_token("test_key") is True
    
    # Test invalid token
    assert auth.validate_token("invalid_key") is False

def test_auth_generate_token(auth):
    token = auth.generate_token()
    assert isinstance(token, str)
    assert len(token) > 0

def test_auth_get_auth_header(auth):
    header = auth.get_auth_header()
    assert "Authorization" in header
    assert header["Authorization"].startswith("Bearer ")

def test_auth_authenticate_request(auth):
    request = Mock()
    auth.authenticate_request(request)
    assert "Authorization" in request.headers
    assert request.headers["Authorization"].startswith("Bearer ")

def test_auth_authenticate_request_no_token(auth):
    request = Mock()
    request.headers = {}
    with pytest.raises(AuthError):
        auth.authenticate_request(request)

def test_auth_authenticate_request_invalid_token(auth):
    request = Mock()
    request.headers = {"Authorization": "Bearer invalid_token"}
    with pytest.raises(AuthError):
        auth.authenticate_request(request)

def test_auth_refresh_token(auth):
    old_token = auth.generate_token()
    new_token = auth.refresh_token(old_token)
    assert new_token != old_token
    assert auth.validate_token(new_token) is True

def test_auth_token_expiration(auth):
    token = auth.generate_token()
    # Simulate token expiration
    auth._tokens[token] = 0
    assert auth.validate_token(token) is False 