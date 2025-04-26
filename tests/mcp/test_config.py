import pytest
from mcp.config import MCPConfig, load_config

def test_mcp_config():
    config = MCPConfig(
        host="localhost",
        port=8000,
        api_key="test_key",
        timeout=30,
        max_retries=3
    )
    
    assert config.host == "localhost"
    assert config.port == 8000
    assert config.api_key == "test_key"
    assert config.timeout == 30
    assert config.max_retries == 3

def test_load_config_from_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("""
    {
        "host": "test_host",
        "port": 9000,
        "api_key": "test_api_key",
        "timeout": 60,
        "max_retries": 5
    }
    """)
    
    config = load_config(str(config_file))
    assert config.host == "test_host"
    assert config.port == 9000
    assert config.api_key == "test_api_key"
    assert config.timeout == 60
    assert config.max_retries == 5

def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("MCP_HOST", "env_host")
    monkeypatch.setenv("MCP_PORT", "7000")
    monkeypatch.setenv("MCP_API_KEY", "env_api_key")
    monkeypatch.setenv("MCP_TIMEOUT", "45")
    monkeypatch.setenv("MCP_MAX_RETRIES", "4")
    
    config = load_config()
    assert config.host == "env_host"
    assert config.port == 7000
    assert config.api_key == "env_api_key"
    assert config.timeout == 45
    assert config.max_retries == 4 