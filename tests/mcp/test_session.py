import pytest
from unittest.mock import Mock, patch
from mcp_local_backup.session import MCPSession, SessionError

@pytest.fixture
def mock_config():
    return Mock(
        session_timeout=3600,
        max_sessions=100
    )

@pytest.fixture
def session_manager(mock_config):
    return MCPSession(mock_config)

def test_session_init(mock_config):
    session = MCPSession(mock_config)
    assert session.config == mock_config
    assert session.sessions == {}

def test_session_create(session_manager):
    session_id = session_manager.create_session()
    assert session_id in session_manager.sessions
    assert session_manager.sessions[session_id].is_active()

def test_session_get(session_manager):
    session_id = session_manager.create_session()
    session = session_manager.get_session(session_id)
    assert session is not None
    assert session.is_active()

def test_session_get_invalid(session_manager):
    with pytest.raises(SessionError):
        session_manager.get_session("invalid_id")

def test_session_destroy(session_manager):
    session_id = session_manager.create_session()
    session_manager.destroy_session(session_id)
    assert session_id not in session_manager.sessions

def test_session_destroy_invalid(session_manager):
    with pytest.raises(SessionError):
        session_manager.destroy_session("invalid_id")

def test_session_expiration(session_manager):
    session_id = session_manager.create_session()
    session = session_manager.sessions[session_id]
    session.last_activity = 0  # Simulate expired session
    assert not session.is_active()

def test_session_max_sessions(session_manager):
    # Create maximum number of sessions
    for _ in range(100):
        session_manager.create_session()
    
    # Should raise error when trying to create more sessions
    with pytest.raises(SessionError):
        session_manager.create_session()

def test_session_cleanup(session_manager):
    # Create some sessions
    for _ in range(5):
        session_manager.create_session()
    
    # Expire some sessions
    for session_id in list(session_manager.sessions.keys())[:2]:
        session_manager.sessions[session_id].last_activity = 0
    
    # Cleanup expired sessions
    session_manager.cleanup_expired_sessions()
    
    # Should only have 3 active sessions
    assert len(session_manager.sessions) == 3

def test_session_activity(session_manager):
    session_id = session_manager.create_session()
    session = session_manager.sessions[session_id]
    old_activity = session.last_activity
    
    session_manager.update_activity(session_id)
    assert session.last_activity > old_activity 