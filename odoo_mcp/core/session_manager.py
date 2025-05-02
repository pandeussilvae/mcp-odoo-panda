"""
Session Manager implementation for Odoo.
This module provides session management functionality for Odoo API connections.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from odoo_mcp.core.authenticator import OdooAuthenticator
from odoo_mcp.core.connection_pool import ConnectionPool
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError, ConfigurationError, NetworkError, AuthError
)

logger = logging.getLogger(__name__)

class SessionManager:
    """
    Manages Odoo sessions and provides session-related functionality.
    Handles session creation, validation, and cleanup.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        authenticator: OdooAuthenticator,
        pool: ConnectionPool
    ):
        """
        Initialize the session manager.

        Args:
            config: Configuration dictionary
            authenticator: OdooAuthenticator instance
            pool: ConnectionPool instance
        """
        self.config = config
        self.authenticator = authenticator
        self.pool = pool
        self.session_timeout = timedelta(minutes=config.get('session_timeout_minutes', 120))
        self.max_sessions = config.get('max_sessions', 100)
        
        # Session storage
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._user_sessions: Dict[str, List[str]] = {}
        
        # Initialize cleanup task
        self._cleanup_task = None
        self._start_cleanup_task()

    def _start_cleanup_task(self):
        """Start the periodic cleanup task."""
        async def cleanup():
            while True:
                try:
                    await self._cleanup_expired_sessions()
                except Exception as e:
                    logger.error(f"Error during session cleanup: {e}")
                await asyncio.sleep(60)  # Check every minute

        self._cleanup_task = asyncio.create_task(cleanup())

    async def _cleanup_expired_sessions(self):
        """Clean up expired sessions."""
        now = datetime.now()
        expired_keys = [
            key for key, session in self._sessions.items()
            if now - session['created_at'] > self.session_timeout
        ]
        
        for key in expired_keys:
            await self._remove_session(key)

    async def _remove_session(self, session_id: str):
        """Remove a session and update user sessions."""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            username = session['username']
            
            # Remove from user sessions
            if username in self._user_sessions:
                self._user_sessions[username].remove(session_id)
                if not self._user_sessions[username]:
                    del self._user_sessions[username]
            
            # Remove from sessions
            del self._sessions[session_id]

    async def create_session(
        self,
        username: str,
        password: str,
        database: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new session for a user.

        Args:
            username: Odoo username
            password: Odoo password
            database: Optional database name

        Returns:
            Dict[str, Any]: Session data

        Raises:
            AuthError: If authentication fails
            ConfigurationError: If required configuration is missing
        """
        try:
            # Check session limit
            if username in self._user_sessions and len(self._user_sessions[username]) >= self.max_sessions:
                # Remove oldest session
                oldest_session = self._user_sessions[username][0]
                await self._remove_session(oldest_session)

            # Authenticate and create session
            session_id, session = await self.authenticator.authenticate(
                username=username,
                password=password,
                database=database
            )

            # Store session
            self._sessions[session_id] = session
            
            # Update user sessions
            if username not in self._user_sessions:
                self._user_sessions[username] = []
            self._user_sessions[username].append(session_id)

            return session

        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Failed to create session: {str(e)}")

    async def validate_session(self, session_id: str) -> Dict[str, Any]:
        """
        Validate a session and return session data.

        Args:
            session_id: Session ID to validate

        Returns:
            Dict[str, Any]: Session data

        Raises:
            AuthError: If session is invalid or expired
        """
        try:
            # Validate with authenticator
            session = await self.authenticator.validate_session(session_id)
            
            # Update session data
            self._sessions[session_id] = session
            return session

        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Failed to validate session: {str(e)}")

    async def get_user_sessions(self, username: str) -> List[Dict[str, Any]]:
        """
        Get all active sessions for a user.

        Args:
            username: Username to get sessions for

        Returns:
            List[Dict[str, Any]]: List of session data
        """
        sessions = []
        if username in self._user_sessions:
            for session_id in self._user_sessions[username]:
                try:
                    session = await self.validate_session(session_id)
                    sessions.append(session)
                except AuthError:
                    # Session is invalid, remove it
                    await self._remove_session(session_id)
        return sessions

    async def logout(self, session_id: str):
        """
        Logout and invalidate a session.

        Args:
            session_id: Session ID to invalidate
        """
        await self.authenticator.logout(session_id)
        await self._remove_session(session_id)

    async def logout_all(self, username: str):
        """
        Logout all sessions for a user.

        Args:
            username: Username to logout all sessions for
        """
        if username in self._user_sessions:
            for session_id in self._user_sessions[username][:]:
                await self.logout(session_id)

    async def close(self):
        """Close the session manager and cleanup all sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Remove all sessions
        for session_id in list(self._sessions.keys()):
            await self._remove_session(session_id) 