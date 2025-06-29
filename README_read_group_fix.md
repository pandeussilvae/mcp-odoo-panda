# Fix per il metodo read_group in Odoo MCP Server

## Problema

L'errore che si verificava era:

```
TypeError: read_group() got multiple values for argument 'domain'
```

Questo errore si verificava quando si tentava di chiamare il metodo `read_group()` di Odoo attraverso il tool `odoo_execute_kw` del server MCP.

## Causa del Problema

Il problema era nella gestione del metodo `read_group()` nel codice del server MCP. Specificamente:

1. **Firma del metodo `read_group()`**: Il metodo ha una firma specifica:
   ```python
   read_group(domain, fields, groupby, limit=None, offset=0, orderby=False, lazy=True)
   ```

2. **Gestione mancante**: Nel codice originale, il metodo `read_group()` non era gestito specificamente e cadeva nel caso `else` che assumeva che `args[0]` fossero gli ID del record, mentre per `read_group()` `args[0]` dovrebbe essere il `domain`.

3. **Duplicazione dell'argomento**: Quando il `domain` era presente sia negli `args` che nei `kwargs`, questo causava la duplicazione dell'argomento.

## Soluzione Implementata

Ho aggiunto la gestione specifica per il metodo `read_group()` in entrambi i tool:
- `odoo_call_method`
- `odoo_execute_kw`

### Codice Aggiunto

```python
elif method == "read_group":
    # For read_group method: args[0] = domain, args[1] = fields, args[2] = groupby
    # Optional kwargs: limit, offset, orderby, lazy
    domain = parse_domain(args[0] if args else [])
    fields = args[1] if len(args) > 1 else []
    groupby = args[2] if len(args) > 2 else []
    method_args = [domain, fields, groupby]
    method_kwargs = {}
    if kwargs_:
        # Only pass valid kwargs for read_group
        valid_kwargs = ['limit', 'offset', 'orderby', 'lazy']
        for key, value in kwargs_.items():
            if key in valid_kwargs:
                method_kwargs[key] = value
```

### Come Funziona

1. **Estrazione dei parametri**: Il codice estrae correttamente:
   - `domain` da `args[0]`
   - `fields` da `args[1]`
   - `groupby` da `args[2]`

2. **Validazione dei kwargs**: Solo i parametri validi per `read_group()` vengono passati nei `kwargs`:
   - `limit`
   - `offset`
   - `orderby`
   - `lazy`

3. **Prevenzione della duplicazione**: Il `domain` viene passato solo come argomento posizionale, evitando la duplicazione.

## Esempio di Utilizzo

```json
{
  "jsonrpc": "2.0",
  "method": "call_tool",
  "params": {
    "name": "odoo_execute_kw",
    "arguments": {
      "model": "sale.order",
      "method": "read_group",
      "args": [
        [["state", "=", "draft"]],  // domain
        ["amount_total", "partner_id"],  // fields
        ["partner_id"]  // groupby
      ],
      "kwargs": {
        "limit": 10,
        "offset": 0
      }
    }
  },
  "id": 1
}
```

## Test

È stato creato un test (`test_read_group_fix.py`) per verificare che la correzione funzioni correttamente.

## Metodi Simili

Questa correzione segue lo stesso pattern utilizzato per altri metodi Odoo come:
- `search_read`
- `search`
- `search_count`
- `fields_get`
- `default_get`

Ogni metodo ha la sua gestione specifica per evitare problemi di parametri duplicati o malformati. 