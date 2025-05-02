"""
Odoo MCP Session Manager implementation.
"""

import logging
import time
from typing import Dict, Any, Optional, Union, Type
from odoo_mcp.core.authenticator import OdooAuthenticator
from odoo_mcp.core.connection_pool import ConnectionPool
from odoo_mcp.error_handling.exceptions import SessionError, AuthError, OdooMCPError

logger = logging.getLogger(__name__)

class Session:
    """Session class for managing user sessions."""

    def __init__(self, session_id: str, user_id: int, username: str, expires_at: float):
        """
        Initialize session.

        Args:
            session_id: Session identifier
            user_id: User identifier
            username: Username
            expires_at: Expiration timestamp
        """
        self.session_id = session_id
        self.user_id = user_id
        self.username = username
        self.expires_at = expires_at
        self.last_activity = time.time()

    def is_expired(self) -> bool:
        """
        Check if session is expired.

        Returns:
            bool: True if expired, False otherwise
        """
        return time.time() > self.expires_at

    def update_activity(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = time.time()

class SessionManager:
    """Session manager implementation."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize session manager.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.authenticator = OdooAuthenticator(config)
        self.connection_pool = ConnectionPool(config)
        self._sessions: Dict[str, Session] = {}
        self._session_lifetime = config.get('session_lifetime', 3600)  # 1 hour default

    async def create_session(self, username: str, password: str) -> Session:
        """
        Create a new session.

        Args:
            username: Username
            password: Password

        Returns:
            Session: Created session

        Raises:
            AuthError: If authentication fails
            SessionError: If session creation fails
        """
        try:
            # Authenticate user
            auth_result = await self.authenticator.authenticate(username, password)
            if not auth_result:
                raise AuthError("Authentication failed")

            # Create session
            session_id = f"{username}_{int(time.time())}"
            expires_at = time.time() + self._session_lifetime
            session = Session(session_id, auth_result['uid'], username, expires_at)
            self._sessions[session_id] = session

            return session

        except AuthError as e:
            raise AuthError(f"Failed to create session: {str(e)}")
        except Exception as e:
            raise SessionError(f"Unexpected error during session creation: {str(e)}")

    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get session by ID.

        Args:
            session_id: Session identifier

        Returns:
            Optional[Session]: Session if found and valid, None otherwise
        """
        session = self._sessions.get(session_id)
        if session and not session.is_expired():
            session.update_activity()
            return session
        return None

    def end_session(self, session_id: str) -> None:
        """
        End a session.

        Args:
            session_id: Session identifier
        """
        if session_id in self._sessions:
            del self._sessions[session_id]

    def cleanup_expired_sessions(self) -> None:
        """Remove expired sessions."""
        current_time = time.time()
        expired_sessions = [
            session_id for session_id, session in self._sessions.items()
            if session.is_expired()
        ]
        for session_id in expired_sessions:
            del self._sessions[session_id]
