# Create Method Fix for "Invalid field 'values'" Error

## Problem Description

The MCP server was encountering a `ValueError: Invalid field 'values' on model 'calendar.event'` error when calling the `create` method on Odoo models. This error occurred because:

1. The tool was receiving parameters with a nested structure like `kwargs.values`
2. The code was incorrectly passing the entire `kwargs` object to Odoo instead of extracting the actual field values
3. Odoo was trying to create a record with a field called `'values'` which doesn't exist in the model

## Root Cause

The error occurred in the `odoo_create` tool when processing parameters like:

```json
{
  "tool": "odoo_create",
  "params": {
    "model": "calendar.event",
    "kwargs": {
      "values": {
        "location": "Lecce",
        "stop": "2025-07-01 14:00:00",
        "name": "Incontro a Lecce con Lars",
        "start": "2025-07-01 13:00:00"
      }
    },
    "args": [],
    "method": "create"
  }
}
```

The problematic code was:
```python
elif kwargs:
    values = kwargs  # ❌ This passed the entire kwargs object to Odoo
```

This caused Odoo to receive:
```python
{
    "values": {
        "location": "Lecce",
        "stop": "2025-07-01 14:00:00",
        "name": "Incontro a Lecce con Lars",
        "start": "2025-07-01 13:00:00"
    }
}
```

Instead of the expected:
```python
{
    "location": "Lecce",
    "stop": "2025-07-01 14:00:00",
    "name": "Incontro a Lecce con Lars",
    "start": "2025-07-01 13:00:00"
}
```

## Solution

### Enhanced Parameter Extraction Logic

The parameter extraction logic in the `odoo_create` tool has been improved to properly handle nested `values` structures:

```python
elif tool_name == "odoo_create":
    model = tool_args.get("model")
    # Extract parameters from arguments array first, then args, then kwargs, then tool_args
    arguments = tool_args.get("arguments", [])
    args = tool_args.get("args", [])
    kwargs = tool_args.get("kwargs", {})
    
    # Check if values are in arguments array
    if arguments and len(arguments) > 0:
        values = arguments[0]
    elif args and len(args) > 0:
        values = args[0]
    elif kwargs and "values" in kwargs:
        values = kwargs["values"]  # ✅ Extract values from nested structure
    elif kwargs:
        # If kwargs doesn't have a "values" key, use the entire kwargs as values
        values = kwargs
    else:
        values = tool_args.get("values", {})
    
    result = await self.pool.execute_kw(
        model=model,
        method="create",
        args=[values],
        kwargs={}
    )
```

### Consistent Implementation Across Tools

The same fix has been applied consistently across all tools that handle the `create` method:

1. **odoo_create** - Fixed parameter extraction
2. **odoo_execute_kw** - Already had correct implementation
3. **odoo_call_method** - Already had correct implementation

## Supported Parameter Structures

The fix now supports multiple ways to pass values for record creation:

### 1. Nested values structure (the problematic case):
```json
{
  "kwargs": {
    "values": {
      "name": "Test Event",
      "start": "2025-07-01 10:00:00"
    }
  }
}
```

### 2. Direct values in kwargs:
```json
{
  "kwargs": {
    "name": "Test Event",
    "start": "2025-07-01 10:00:00"
  }
}
```

### 3. Values in args array:
```json
{
  "args": [{
    "name": "Test Event",
    "start": "2025-07-01 10:00:00"
  }]
}
```

### 4. Values in arguments array:
```json
{
  "arguments": [{
    "name": "Test Event",
    "start": "2025-07-01 10:00:00"
  }]
}
```

## Testing

A comprehensive test script `test_create_method_fix.py` has been created to verify:

1. **Parameter extraction tests:**
   - Nested `kwargs.values` structure
   - Direct `kwargs` values
   - Empty `kwargs`

2. **Create method tests:**
   - `odoo_create` tool with various parameter structures
   - `odoo_execute_kw` tool with create method
   - `odoo_call_method` tool with create method

## Usage Examples

### Before (would cause error):
```json
{
  "tool": "odoo_create",
  "params": {
    "model": "calendar.event",
    "kwargs": {
      "values": {
        "location": "Lecce",
        "name": "Incontro a Lecce con Lars",
        "start": "2025-07-01 13:00:00",
        "stop": "2025-07-01 14:00:00"
      }
    }
  }
}
```
**Result:** ❌ `ValueError: Invalid field 'values' on model 'calendar.event'`

### After (works correctly):
```json
{
  "tool": "odoo_create",
  "params": {
    "model": "calendar.event",
    "kwargs": {
      "values": {
        "location": "Lecce",
        "name": "Incontro a Lecce con Lars",
        "start": "2025-07-01 13:00:00",
        "stop": "2025-07-01 14:00:00"
      }
    }
  }
}
```
**Result:** ✅ Record created successfully

### Alternative formats (also work):
```json
{
  "tool": "odoo_create",
  "params": {
    "model": "calendar.event",
    "kwargs": {
      "location": "Lecce",
      "name": "Incontro a Lecce con Lars",
      "start": "2025-07-01 13:00:00",
      "stop": "2025-07-01 14:00:00"
    }
  }
}
```

## Error Handling

The fix provides robust error handling:

1. **Backward compatibility:** Existing parameter structures continue to work
2. **Flexible input:** Supports multiple ways to pass values
3. **Graceful fallback:** Falls back to empty values if no valid input is found
4. **Clear logging:** Logs parameter extraction decisions for debugging

## Benefits

1. **Fixes the error:** Eliminates the "Invalid field 'values'" error
2. **Improves flexibility:** Supports multiple parameter structures
3. **Maintains compatibility:** Existing code continues to work
4. **Better debugging:** Enhanced logging helps identify parameter issues

## Files Modified

- `odoo_mcp/core/mcp_server.py` - Enhanced parameter extraction in `odoo_create` tool
- `test_create_method_fix.py` - New test script
- `README_create_method_fix.md` - This documentation

## Running Tests

To test the fix:

```bash
python test_create_method_fix.py
```

The test will verify that:
- Nested `kwargs.values` structures are handled correctly
- Direct `kwargs` values still work
- The "Invalid field 'values'" error is prevented
- All parameter structures are supported

## Related Issues

This fix addresses the same type of parameter extraction issues that could occur in other methods. The pattern established here can be applied to other tools that need to handle nested parameter structures. 