import pytest
from mcp.resource_types import ResourceType, Resource, Tool, Prompt

def test_resource_type():
    assert ResourceType.RECORD.value == "record"
    assert ResourceType.LIST.value == "list"
    assert ResourceType.BINARY.value == "binary"

def test_resource():
    resource = Resource(
        uri="test://resource/1",
        type=ResourceType.RECORD,
        data={"id": 1, "name": "Test"},
        mime_type="application/json"
    )
    
    assert resource.uri == "test://resource/1"
    assert resource.type == ResourceType.RECORD
    assert resource.data == {"id": 1, "name": "Test"}
    assert resource.mime_type == "application/json"

def test_tool():
    tool = Tool(
        name="test_tool",
        description="A test tool",
        input_schema={
            "type": "object",
            "properties": {
                "param1": {"type": "string"},
                "param2": {"type": "number"}
            }
        }
    )
    
    assert tool.name == "test_tool"
    assert tool.description == "A test tool"
    assert tool.input_schema["type"] == "object"
    assert "param1" in tool.input_schema["properties"]

def test_prompt():
    prompt = Prompt(
        name="test_prompt",
        description="A test prompt",
        arguments=[
            {
                "name": "arg1",
                "type": "string",
                "description": "First argument"
            }
        ]
    )
    
    assert prompt.name == "test_prompt"
    assert prompt.description == "A test prompt"
    assert len(prompt.arguments) == 1
    assert prompt.arguments[0]["name"] == "arg1" 