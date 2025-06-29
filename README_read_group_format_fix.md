# Fix per il formato non standard del metodo read_group in Odoo MCP Server

## Problema

Il client JSON stava inviando i parametri per il metodo `read_group()` in un formato non standard, causando problemi di parsing e risposta del server.

### Formato Inviato dal Client (Non Standard)

```json
{
  "tool": "odoo_execute_kw",
  "params": {
    "model": "sale.order",
    "method": "read_group",
    "args": [
      {
        "groupby": ["partner_id"],
        "kwargs": {"lazy": false},
        "domain": [
          ["state", "in", ["draft", "sent", "sale"]],
          ["partner_id", "!=", 1]
        ],
        "fields": ["partner_id"]
      }
    ]
  }
}
```

### Formato Atteso dal Server (Standard)

```json
{
  "tool": "odoo_execute_kw",
  "params": {
    "model": "sale.order",
    "method": "read_group",
    "args": [
      [["state", "in", ["draft", "sent", "sale"]], ["partner_id", "!=", 1]],  // domain
      ["partner_id"],  // fields
      ["partner_id"]   // groupby
    ],
    "kwargs": {
      "lazy": false
    }
  }
}
```

## Causa del Problema

Il server MCP si aspettava che i parametri per il metodo `read_group()` fossero passati come array separato:
- `args[0]` = domain
- `args[1]` = fields  
- `args[2]` = groupby
- `kwargs` = parametri opzionali

Ma il client stava inviando tutti i parametri come un unico oggetto nell'array `args`, causando un parsing errato.

## Soluzione Implementata

Ho modificato la gestione del metodo `read_group()` per supportare entrambi i formati:

### Codice Corretto

```python
elif method == "read_group":
    # For read_group method: args[0] = domain, args[1] = fields, args[2] = groupby
    # Optional kwargs: limit, offset, orderby, lazy
    
    # Handle non-standard format where all parameters are in a single object
    if args and len(args) == 1 and isinstance(args[0], dict):
        # Extract parameters from the single object
        param_obj = args[0]
        domain = parse_domain(param_obj.get("domain", []))
        fields = param_obj.get("fields", [])
        groupby = param_obj.get("groupby", [])
        # Merge kwargs from the object with the main kwargs
        merged_kwargs = kwargs_.copy() if kwargs_ else {}
        if "kwargs" in param_obj:
            merged_kwargs.update(param_obj["kwargs"])
    else:
        # Standard format: separate parameters
        domain = parse_domain(args[0] if args else [])
        fields = args[1] if len(args) > 1 else []
        groupby = args[2] if len(args) > 2 else []
        merged_kwargs = kwargs_ if kwargs_ else {}
    
    method_args = [domain, fields, groupby]
    method_kwargs = {}
    if merged_kwargs:
        # Only pass valid kwargs for read_group
        valid_kwargs = ['limit', 'offset', 'orderby', 'lazy']
        for key, value in merged_kwargs.items():
            if key in valid_kwargs:
                method_kwargs[key] = value
```

### Come Funziona

1. **Rilevamento del formato**: Il codice controlla se `args[0]` è un dizionario
2. **Estrazione parametri**: Se è un dizionario, estrae i parametri dall'oggetto
3. **Merge dei kwargs**: Combina i kwargs dell'oggetto con quelli principali
4. **Fallback standard**: Se non è un dizionario, usa il formato standard
5. **Validazione**: Filtra solo i parametri validi per `read_group()`

## Compatibilità

Questa correzione mantiene la compatibilità con entrambi i formati:

- ✅ **Formato standard**: `args = [domain, fields, groupby]`
- ✅ **Formato non standard**: `args = [{domain, fields, groupby, kwargs}]`
- ✅ **Parametri opzionali**: Supporta tutti i parametri validi (`limit`, `offset`, `orderby`, `lazy`)

## Test

Ho creato un test (`test_read_group_nonstandard_format.py`) che verifica:

1. **Test formato non standard**: Verifica che funzioni con tutti i parametri in un oggetto
2. **Test formato standard**: Verifica che continui a funzionare con il formato originale
3. **Test merge kwargs**: Verifica che i kwargs vengano combinati correttamente

### Esempio di Test

```python
# Test formato non standard
test_request = {
    "jsonrpc": "2.0",
    "method": "call_tool",
    "params": {
        "name": "odoo_execute_kw",
        "arguments": {
            "model": "sale.order",
            "method": "read_group",
            "args": [
                {
                    "groupby": ["partner_id"],
                    "kwargs": {"lazy": False},
                    "domain": [
                        ["state", "in", ["draft", "sent", "sale"]],
                        ["partner_id", "!=", 1]
                    ],
                    "fields": ["partner_id"]
                }
            ]
        }
    },
    "id": 1
}
```

## Risultato

Dopo questa correzione:

- ✅ Il server accetta entrambi i formati di parametri
- ✅ I parametri vengono estratti e passati correttamente a Odoo
- ✅ I kwargs vengono combinati e filtrati appropriatamente
- ✅ La compatibilità con il formato standard è mantenuta
- ✅ Il client JSON può inviare i parametri nel formato che preferisce

## Applicazione

Questa correzione è stata applicata a entrambi i tool:
- `odoo_execute_kw`
- `odoo_call_method`

Entrambi ora supportano il formato non standard mantenendo la compatibilità con il formato standard. 