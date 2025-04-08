import asyncio
import os
import sys

# Add the project root to the Python path to allow importing odoo_mcp
# This is often needed when running examples directly from within the examples dir
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from odoo_mcp.core.mcp_server import main as run_mcp_server
from odoo_mcp.error_handling.exceptions import ConfigurationError

async def run_example():
    """
    Runs the Odoo MCP server using a configuration file.
    """
    # --- Configuration ---
    # 1. COPY `odoo_mcp/config/config.dev.yaml` to a new file (e.g., `my_config.yaml`).
    # 2. EDIT `my_config.yaml` with your actual Odoo instance details:
    #    - odoo_url
    #    - database
    #    - username
    #    - api_key (or password)
    # 3. Specify the path to your config file below.
    config_file_path = "odoo_mcp/config/config.dev.yaml" # CHANGE THIS to your config file path if needed

    print("--- Odoo MCP Server Example ---")
    print(f"Attempting to run server using config: {config_file_path}")
    print("Ensure the configuration file exists and contains valid Odoo credentials.")
    print("The server will start listening on stdio.")
    print("You can send JSON-RPC requests via stdin (one JSON object per line).")
    print("-" * 30)

    # --- Example JSON-RPC Requests (Send via stdin) ---
    # Note: Ensure the JSON is on a single line when sending via stdin.

    # Example 1: Echo method
    # {"jsonrpc": "2.0", "method": "echo", "params": {"message": "Hello MCP!"}, "id": 1}

    # Example 2: Call Odoo 'search_count' on res.partner (using XMLRPC handler by default)
    # {"jsonrpc": "2.0", "method": "call_odoo", "params": {"model": "res.partner", "method": "search_count", "args": [[]]}, "id": "req-partner-count"}

    # Example 3: Call Odoo 'read' on res.users (user ID 2, requires appropriate permissions)
    # {"jsonrpc": "2.0", "method": "call_odoo", "params": {"model": "res.users", "method": "read", "args": [[2], ["name", "login"]]}, "id": 3}

    # Example 4: Create a session (if SessionManager and Authenticator are fully integrated)
    # {"jsonrpc": "2.0", "method": "create_session", "params": {"username": "your_user", "api_key": "your_pass"}, "id": "session-req"}

    # Example 5: Call Odoo using a session ID (requires session handling in call_odoo)
    # {"jsonrpc": "2.0", "method": "call_odoo", "params": {"session_id": "YOUR_SESSION_ID", "model": "res.company", "method": "search_read", "args": [[]], "kwargs": {"limit": 1, "fields": ["name"]}}, "id": 4}

    print("Waiting for server to start (Press Ctrl+C to stop)...")
    print("-" * 30)

    try:
        # Run the main server function from mcp_server.py
        await run_mcp_server(config_path=config_file_path)
    except ConfigurationError as e:
        print(f"\nCONFIG ERROR: {e}")
        print("Please ensure the config file path is correct and the file is valid.")
    except Exception as e:
        print(f"\nUNEXPECTED ERROR during server run: {e}")

if __name__ == "__main__":
    # Note: The main function in mcp_server already sets up basic logging
    # if config loading fails, and then detailed logging from the config.
    asyncio.run(run_example())
