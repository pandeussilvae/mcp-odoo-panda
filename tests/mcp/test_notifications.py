import pytest
from unittest.mock import Mock, patch
from mcp.notifications import MCPNotification, NotificationManager

@pytest.fixture
def mock_config():
    return Mock(
        notification_queue_size=1000,
        notification_timeout=30
    )

@pytest.fixture
def notification_manager(mock_config):
    return NotificationManager(mock_config)

def test_notification_init():
    notification = MCPNotification(
        type="resource_updated",
        resource_uri="test://resource/1",
        data={"id": 1, "name": "Test"}
    )
    assert notification.type == "resource_updated"
    assert notification.resource_uri == "test://resource/1"
    assert notification.data == {"id": 1, "name": "Test"}

def test_notification_manager_init(mock_config):
    manager = NotificationManager(mock_config)
    assert manager.config == mock_config
    assert manager.queue.maxsize == 1000

def test_notification_manager_add(notification_manager):
    notification = MCPNotification(
        type="resource_updated",
        resource_uri="test://resource/1",
        data={"id": 1, "name": "Test"}
    )
    notification_manager.add_notification(notification)
    assert not notification_manager.queue.empty()

def test_notification_manager_get(notification_manager):
    notification = MCPNotification(
        type="resource_updated",
        resource_uri="test://resource/1",
        data={"id": 1, "name": "Test"}
    )
    notification_manager.add_notification(notification)
    retrieved = notification_manager.get_notification()
    assert retrieved == notification

def test_notification_manager_queue_full(notification_manager):
    # Fill up the queue
    for i in range(1000):
        notification = MCPNotification(
            type="resource_updated",
            resource_uri=f"test://resource/{i}",
            data={"id": i}
        )
        notification_manager.add_notification(notification)
    
    # Should raise error when queue is full
    with pytest.raises(Exception):
        notification_manager.add_notification(MCPNotification(
            type="resource_updated",
            resource_uri="test://resource/1001",
            data={"id": 1001}
        ))

def test_notification_manager_timeout(notification_manager):
    # Should raise timeout error when no notifications are available
    with pytest.raises(Exception):
        notification_manager.get_notification(timeout=0.1)

def test_notification_manager_clear(notification_manager):
    # Add some notifications
    for i in range(5):
        notification = MCPNotification(
            type="resource_updated",
            resource_uri=f"test://resource/{i}",
            data={"id": i}
        )
        notification_manager.add_notification(notification)
    
    # Clear the queue
    notification_manager.clear_notifications()
    assert notification_manager.queue.empty()

def test_notification_manager_subscribe(notification_manager):
    callback = Mock()
    notification_manager.subscribe("resource_updated", callback)
    assert "resource_updated" in notification_manager.subscribers
    assert callback in notification_manager.subscribers["resource_updated"]

def test_notification_manager_unsubscribe(notification_manager):
    callback = Mock()
    notification_manager.subscribe("resource_updated", callback)
    notification_manager.unsubscribe("resource_updated", callback)
    assert "resource_updated" not in notification_manager.subscribers 