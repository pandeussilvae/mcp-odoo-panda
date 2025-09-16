"""
Odoo Authentication Handler.
This module provides authentication functionality for Odoo API connections.
"""

import logging
import asyncio
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

from odoo_mcp.core.connection_pool import ConnectionPool, get_connection_pool
from odoo_mcp.error_handling.exceptions import (
    OdooMCPError,
    ConfigurationError,
    NetworkError,
    AuthError,
)

logger = logging.getLogger(__name__)

# Global authenticator instance
_authenticator = None


def initialize_authenticator(config: Dict[str, Any]) -> None:
    """
    Initialize the global authenticator.

    Args:
        config: Configuration dictionary

    Raises:
        ConfigurationError: If the authenticator is already initialized
    """
    global _authenticator
    if _authenticator is not None:
        raise ConfigurationError("Authenticator is already initialized")

    pool = get_connection_pool()
    _authenticator = Authenticator(config, pool)
    logger.info("Authenticator initialized successfully")


def get_authenticator() -> "Authenticator":
    """
    Get the global authenticator instance.

    Returns:
        Authenticator: The global authenticator instance

    Raises:
        ConfigurationError: If the authenticator is not initialized
    """
    if _authenticator is None:
        raise ConfigurationError("Authenticator is not initialized")
    return _authenticator


class Authenticator:
    """
    Handles authentication for Odoo API connections.
    Provides session management, token refresh, and error handling.
    """

    def __init__(self, config: Dict[str, Any], pool: ConnectionPool):
        """
        Initialize the Odoo authenticator.

        Args:
            config: Configuration dictionary
            pool: Connection pool instance
        """
        self.config = config
        self.pool = pool
        self.session_timeout = timedelta(minutes=config.get("session_timeout_minutes", 120))
        self.refresh_threshold = timedelta(minutes=config.get("refresh_threshold_minutes", 10))

        # Session storage
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._refresh_tasks: Dict[str, asyncio.Task] = {}

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
            key for key, session in self._sessions.items() if now - session["created_at"] > self.session_timeout
        ]

        for key in expired_keys:
            await self._remove_session(key)

    async def _remove_session(self, session_id: str):
        """Remove a session and its refresh task."""
        if session_id in self._refresh_tasks:
            self._refresh_tasks[session_id].cancel()
            try:
                await self._refresh_tasks[session_id]
            except asyncio.CancelledError:
                pass
            del self._refresh_tasks[session_id]

        if session_id in self._sessions:
            del self._sessions[session_id]

    async def authenticate(
        self, username: str, password: str, database: Optional[str] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Authenticate with Odoo and create a session.

        Args:
            username: Odoo username
            password: Odoo password
            database: Optional database name

        Returns:
            Tuple[str, Dict[str, Any]]: Session ID and session data

        Raises:
            AuthError: If authentication fails
            ConfigurationError: If required configuration is missing
        """
        try:
            # Get database from config if not provided
            db = database or self.config.get("database")
            if not db:
                raise ConfigurationError("Database name is required")

            # Authenticate with Odoo
            uid = await self.pool.execute_kw(model="common", method="login", args=[db, username, password], kwargs={})

            if not uid:
                raise AuthError("Invalid credentials")

            # Create session
            session_id = f"{db}_{username}_{datetime.now().timestamp()}"
            session = {
                "id": session_id,
                "uid": uid,
                "username": username,
                "database": db,
                "created_at": datetime.now(),
                "last_activity": datetime.now(),
            }
            self._sessions[session_id] = session

            # Start refresh task
            self._refresh_tasks[session_id] = asyncio.create_task(self._refresh_session(session_id))

            return session_id, session

        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Authentication failed: {str(e)}")

    async def _refresh_session(self, session_id: str):
        """Periodically refresh the session."""
        while True:
            try:
                session = self._sessions.get(session_id)
                if not session:
                    break

                # Check if refresh is needed
                if datetime.now() - session["created_at"] > self.session_timeout - self.refresh_threshold:
                    # Re-authenticate
                    new_session_id, new_session = await self.authenticate(
                        username=session["username"],
                        password=self.config.get("password", ""),
                        database=session["database"],
                    )

                    # Update session
                    self._sessions[new_session_id] = new_session
                    await self._remove_session(session_id)
                    break

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"Error refreshing session {session_id}: {e}")
                await asyncio.sleep(60)  # Wait before retrying

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
        session = self._sessions.get(session_id)
        if not session:
            raise AuthError("Invalid session")

        if datetime.now() - session["created_at"] > self.session_timeout:
            await self._remove_session(session_id)
            raise AuthError("Session expired")

        # Update last activity
        session["last_activity"] = datetime.now()
        return session

    async def logout(self, session_id: str):
        """
        Logout and invalidate a session.

        Args:
            session_id: Session ID to invalidate
        """
        await self._remove_session(session_id)

    async def close(self):
        """Close the authenticator and cleanup all sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Remove all sessions
        for session_id in list(self._sessions.keys()):
            await self._remove_session(session_id)
