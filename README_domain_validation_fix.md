# Domain Validation Fix for search_count Method

## Problem Description

The MCP server was encountering a `TypeError: 'bool' object is not subscriptable` error when calling the `search_count` method on Odoo models. This error occurred because:

1. The domain parameter was being passed as a boolean value (`True` or `False`) instead of a list
2. Odoo's `is_false` function in `expression.py` tried to access `token[1]` and `token[2]` on a boolean value
3. The `parse_domain` function wasn't properly handling boolean inputs

## Root Cause

The error traceback showed:
```
File "/usr/lib/python3/dist-packages/odoo/osv/expression.py", line 226, in is_false
    elif token[1] == 'in' and not (isinstance(token[2], Query) or token[2]):
TypeError: 'bool' object is not subscriptable
```

This happened when the domain was passed as `True` or `False` instead of a proper domain list like `[["name", "=", "value"]]`.

## Solution

### 1. Enhanced `parse_domain` Function

The `parse_domain` function in `odoo_mcp/core/mcp_server.py` has been improved to:

- Handle `None` inputs gracefully
- Detect and log boolean inputs as errors
- Handle empty strings
- Validate domain structure for lists/tuples
- Provide better error logging

```python
def parse_domain(domain_input):
    """
    Parse domain from various input formats.
    
    Args:
        domain_input: Can be a list, tuple, or string representation of a domain
        
    Returns:
        list: Properly formatted domain list
    """
    # Handle None case
    if domain_input is None:
        logger.debug("Domain input is None, returning empty list")
        return []
    
    # Handle boolean case - this is likely an error
    if isinstance(domain_input, bool):
        logger.warning(f"Domain input is boolean: {domain_input}. This is likely an error. Returning empty list.")
        return []
    
    # Handle empty string case
    if isinstance(domain_input, str) and not domain_input.strip():
        logger.debug("Domain input is empty string, returning empty list")
        return []
    
    # ... rest of the function with enhanced validation
```

### 2. Additional Validation in Method Handlers

Added validation in all domain-using methods (`search_count`, `search`, `search_read`, `read_group`) to ensure the domain is always a valid list:

```python
elif method == "search_count":
    # For search_count method: args[0] = domain
    domain = parse_domain(args[0] if args else [])
    # Additional validation to ensure domain is a valid list
    if not isinstance(domain, list):
        logger.error(f"Invalid domain type for search_count: {type(domain)}. Converting to empty list.")
        domain = []
    method_args = [domain]
    method_kwargs = {}
```

## Affected Methods

The fix has been applied to all methods that use domains:

- `search_count`
- `search`
- `search_read`
- `read_group`

## Testing

A comprehensive test script `test_domain_validation_fix.py` has been created to verify:

1. **parse_domain function tests:**
   - Boolean inputs (`True`, `False`)
   - `None` inputs
   - Empty strings
   - Valid domain strings and lists
   - Invalid inputs

2. **search_count method tests:**
   - Boolean domains
   - `None` domains
   - Empty string domains
   - Valid domains

## Usage Examples

### Before (would cause error):
```python
# This would cause the boolean error
result = await server.call_tool("odoo_execute_kw", {
    "model": "res.partner",
    "method": "search_count",
    "args": [True],  # ❌ Boolean - would cause error
    "kwargs": {}
})
```

### After (handled gracefully):
```python
# This now works correctly
result = await server.call_tool("odoo_execute_kw", {
    "model": "res.partner",
    "method": "search_count",
    "args": [True],  # ✅ Boolean - converted to empty list
    "kwargs": {}
})

# Valid domain still works
result = await server.call_tool("odoo_execute_kw", {
    "model": "res.partner",
    "method": "search_count",
    "args": [[["name", "=", "Test"]]],  # ✅ Valid domain
    "kwargs": {}
})
```

## Error Handling

The fix provides graceful error handling:

1. **Logging:** All invalid inputs are logged with appropriate warning/error messages
2. **Fallback:** Invalid domains are converted to empty lists `[]`
3. **Continuity:** The operation continues with the fallback value instead of crashing

## Benefits

1. **Prevents crashes:** The server no longer crashes on boolean domain inputs
2. **Better debugging:** Enhanced logging helps identify the source of invalid domains
3. **Backward compatibility:** Valid domains continue to work as expected
4. **Robustness:** Handles edge cases that might occur in real-world usage

## Files Modified

- `odoo_mcp/core/mcp_server.py` - Enhanced `parse_domain` function and added validation
- `test_domain_validation_fix.py` - New test script
- `README_domain_validation_fix.md` - This documentation

## Running Tests

To test the fix:

```bash
python test_domain_validation_fix.py
```

The test will verify that:
- Boolean domains are handled gracefully
- Valid domains still work correctly
- The `parse_domain` function returns proper lists for all inputs 