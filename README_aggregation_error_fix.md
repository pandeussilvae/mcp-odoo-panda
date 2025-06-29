# Miglioramento della Gestione degli Errori di Aggregazione

## Problema

L'errore che si verificava era:

```
UserError: Funzione di aggregazione 'month' non valida.
```

Questo errore si verificava quando si tentava di utilizzare una funzione di aggregazione non valida nel metodo `read_group()` di Odoo attraverso il tool `odoo_execute_kw` del server MCP.

## Causa del Problema

Il problema era nella gestione degli errori nel server MCP. Specificamente:

1. **Errore generico**: L'errore `UserError` per funzioni di aggregazione non valide non era gestito specificamente
2. **Mancanza di distinzione**: Non c'era distinzione tra diversi tipi di errori di validazione
3. **Messaggi poco chiari**: L'errore veniva catturato come errore generico senza informazioni specifiche

## Soluzione Implementata

Ho migliorato la gestione degli errori per catturare specificamente gli errori di aggregazione:

### 1. Gestione Specifica negli Handler

#### JSONRPCHandler

Ho migliorato la gestione nel metodo `_call_direct`:

```python
elif "UserError" in error_message or "ValidationError" in error_message or "Funzione di aggregazione" in error_message:
    # Extract the actual error message from the data if available
    clean_message = error_data.get('data', {}).get('message', error_message.split('\n')[0])
    # If the message contains aggregation function error, make it more specific
    if "Funzione di aggregazione" in clean_message:
        raise OdooValidationError(f"JSON-RPC Aggregation Error: {clean_message}", original_exception=Exception(str(error_data)))
    else:
        raise OdooValidationError(f"JSON-RPC Validation Error: {clean_message}", original_exception=Exception(str(error_data)))
```

#### XMLRPCHandler

Ho migliorato la gestione nel metodo `execute_kw`:

```python
# Check if this is a validation error (UserError, ValidationError, aggregation error)
elif "UserError" in str(e) or "ValidationError" in str(e) or "Funzione di aggregazione" in str(e):
    if "Funzione di aggregazione" in str(e):
        raise OdooValidationError(f"XML-RPC Aggregation Error: {str(e)}", original_exception=e)
    else:
        raise OdooValidationError(f"XML-RPC Validation Error: {str(e)}", original_exception=e)
```

### 2. Distinzione degli Errori

La soluzione distingue tra:
- **Errori di aggregazione**: Errori specifici per funzioni di aggregazione non valide
- **Errori di validazione generici**: Altri errori di validazione di Odoo

### 3. Messaggi di Errore Migliorati

- **Per errori di aggregazione**: "JSON-RPC Aggregation Error: Funzione di aggregazione 'month' non valida"
- **Per altri errori di validazione**: "JSON-RPC Validation Error: [messaggio specifico]"

## Vantaggi della Soluzione

### 1. **Messaggi di Errore Specifici**
- L'utente riceve un messaggio di errore chiaro e specifico per gli errori di aggregazione
- Distinzione tra diversi tipi di errori di validazione

### 2. **Debugging Migliorato**
- Informazioni dettagliate per il debugging
- Preservazione dell'eccezione originale per analisi approfondite

### 3. **Consistenza**
- Gestione uniforme tra XML-RPC e JSON-RPC
- Segue lo stesso pattern delle altre eccezioni personalizzate

### 4. **Manutenibilità**
- Codice più leggibile e manutenibile
- Facile aggiungere nuovi tipi di errori di validazione

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
        ["amount_total:month"],     // fields with invalid aggregation
        ["partner_id"]              // groupby
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

### Risposta di Errore Migliorata

```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32007,
    "message": "JSON-RPC Aggregation Error: Funzione di aggregazione 'month' non valida",
    "data": {
      "exception": "OdooValidationError",
      "args": ["JSON-RPC Aggregation Error: Funzione di aggregazione 'month' non valida"],
      "original_exception": "UserError: Funzione di aggregazione 'month' non valida"
    }
  },
  "id": 1
}
```

## Funzioni di Aggregazione Valide

Le funzioni di aggregazione valide in Odoo includono:
- `sum` - Somma
- `avg` - Media
- `min` - Minimo
- `max` - Massimo
- `count` - Conteggio

Esempi di utilizzo corretto:
```python
# Corretto
fields = ["amount_total:sum", "partner_id"]
fields = ["amount_total:avg", "partner_id"]

# Non corretto (causa errore)
fields = ["amount_total:month", "partner_id"]  # 'month' non è una funzione di aggregazione
```

## Test

È stato creato un test (`test_aggregation_error_fix.py`) per verificare che la gestione degli errori di aggregazione funzioni correttamente.

## Metodi Simili

Questa correzione segue lo stesso pattern utilizzato per altri tipi di errori come:
- `OdooMethodNotFoundError` - per metodi inesistenti
- `OdooRecordNotFoundError` - per record inesistenti
- `AuthError` - per errori di autenticazione

Ogni tipo di errore ha la sua gestione specifica per una migliore esperienza utente e debugging. 