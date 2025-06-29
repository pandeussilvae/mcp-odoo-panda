# Miglioramento della Gestione degli Errori per Metodi Inesistenti

## Problema

L'errore che si verificava era:

```
AttributeError: The method 'do_something' does not exist on the model 'res.partner'
```

Questo errore si verificava quando si tentava di chiamare un metodo che non esiste sul modello Odoo attraverso il tool `odoo_execute_kw` del server MCP.

## Causa del Problema

Il problema era nella gestione degli errori nel server MCP. Specificamente:

1. **Errore generico**: L'errore `AttributeError` per metodi inesistenti non era gestito specificamente
2. **Mancanza di eccezione dedicata**: Non esisteva un'eccezione specifica per questo tipo di errore
3. **Gestione inadeguata**: L'errore veniva catturato come errore generico e non forniva informazioni chiare all'utente

## Soluzione Implementata

Ho implementato un sistema di gestione degli errori più robusto e specifico:

### 1. Nuova Eccezione Dedicata

Ho aggiunto una nuova eccezione `OdooMethodNotFoundError` nel file `odoo_mcp/error_handling/exceptions.py`:

```python
class OdooMethodNotFoundError(OdooMCPError):
    """Odoo method not found error."""
    def __init__(self, model: str, method: str, original_exception: Optional[Exception] = None):
        message = f"The method '{method}' does not exist on the model '{model}'"
        super().__init__(message, code=-32016, original_exception=original_exception)
        self.model = model
        self.method = method
```

### 2. Gestione Specifica negli Handler

#### JSONRPCHandler

Ho aggiunto la gestione specifica nel metodo `_call_direct`:

```python
elif "does not exist on the model" in error_message or "AttributeError" in error_message:
    # Extract model and method from error message
    match = re.search(r"The method '([^']+)' does not exist on the model '([^']+)'", error_message)
    if match:
        method_name = match.group(1)
        model_name = match.group(2)
        raise OdooMethodNotFoundError(model_name, method_name, original_exception=Exception(str(error_data)))
    else:
        raise ProtocolError(f"JSON-RPC Method Not Found Error: {full_error}", original_exception=Exception(str(error_data)))
```

#### XMLRPCHandler

Ho aggiunto la gestione specifica nel metodo `execute_kw`:

```python
except Fault as e:
    logger.error(f"XML-RPC Fault: {str(e)}")
    # Check if this is a method not found error
    if "does not exist on the model" in str(e) or "AttributeError" in str(e):
        match = re.search(r"The method '([^']+)' does not exist on the model '([^']+)'", str(e))
        if match:
            method_name = match.group(1)
            model_name = match.group(2)
            raise OdooMethodNotFoundError(model_name, method_name, original_exception=e)
        else:
            raise ProtocolError(f"XML-RPC Method Not Found Error: {str(e)}", original_exception=e)
    else:
        raise ProtocolError(f"XML-RPC Fault: {str(e)}", original_exception=e)
```

### 3. Aggiornamento degli Import

Ho aggiornato gli import nei file:
- `odoo_mcp/core/mcp_server.py`
- `odoo_mcp/core/jsonrpc_handler.py`
- `odoo_mcp/core/xmlrpc_handler.py`

## Vantaggi della Soluzione

### 1. **Messaggi di Errore Chiari**
- L'utente riceve un messaggio di errore specifico e comprensibile
- Include il nome del modello e del metodo che non esiste

### 2. **Gestione Strutturata**
- Codice di errore dedicato (-32016)
- Possibilità di gestire questo tipo di errore specificamente nel client

### 3. **Debugging Migliorato**
- Informazioni dettagliate per il debugging
- Preservazione dell'eccezione originale per analisi approfondite

### 4. **Consistenza**
- Gestione uniforme tra XML-RPC e JSON-RPC
- Segue lo stesso pattern delle altre eccezioni personalizzate

## Esempio di Utilizzo

```json
{
  "jsonrpc": "2.0",
  "method": "call_tool",
  "params": {
    "name": "odoo_execute_kw",
    "arguments": {
      "model": "res.partner",
      "method": "do_something",  // Metodo inesistente
      "args": [],
      "kwargs": {}
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
    "code": -32016,
    "message": "The method 'do_something' does not exist on the model 'res.partner'",
    "data": {
      "exception": "OdooMethodNotFoundError",
      "args": ["res.partner", "do_something"],
      "original_exception": "AttributeError: The method 'do_something' does not exist on the model 'res.partner'"
    }
  },
  "id": 1
}
```

## Test

È stato creato un test (`test_method_not_found_fix.py`) per verificare che la gestione degli errori funzioni correttamente.

## Metodi Simili

Questa correzione segue lo stesso pattern utilizzato per altri tipi di errori come:
- `OdooRecordNotFoundError` - per record inesistenti
- `OdooValidationError` - per errori di validazione
- `AuthError` - per errori di autenticazione

Ogni tipo di errore ha la sua eccezione dedicata per una gestione più precisa e informativa. 