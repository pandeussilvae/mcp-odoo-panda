# Standardizzazione degli Schemi dei Tool

## Problema

L'errore che si verificava era:

```
Received tool input did not match expected schema
```

Questo errore si verificava quando LangChain tentava di validare l'input per i tool del server MCP, ma gli schemi non erano consistenti.

## Causa del Problema

Il problema era nell'inconsistenza degli schemi dei tool definiti nel `CapabilitiesManager`. Alcuni tool avevano uno schema che richiedeva un wrapper `arguments`, mentre altri no:

### Tool con wrapper `arguments`:
- `odoo_search_read`
- `odoo_read`
- `odoo_create`
- `odoo_write`
- `odoo_unlink`

### Tool senza wrapper `arguments`:
- `odoo_execute_kw`
- `data_export`
- `data_import`
- `report_generator`

Questa inconsistenza causava problemi di validazione dello schema in LangChain.

## Soluzione Implementata

Ho standardizzato tutti gli schemi dei tool per usare il wrapper `arguments`, mantenendo la compatibilità con il codice esistente.

### Schema Standardizzato

Tutti i tool ora seguono questo schema standard:

```json
{
  "type": "object",
  "properties": {
    "arguments": {
      "type": "object",
      "properties": {
        // Tool-specific properties here
      },
      "required": ["required_field1", "required_field2"]
    }
  },
  "required": ["arguments"]
}
```

### Esempi di Schemi Standardizzati

#### odoo_execute_kw
```json
{
  "type": "object",
  "properties": {
    "arguments": {
      "type": "object",
      "properties": {
        "model": {
          "type": "string",
          "description": "Name of the Odoo model"
        },
        "method": {
          "type": "string",
          "description": "Name of the method to execute"
        },
        "args": {
          "type": "array",
          "description": "Positional arguments for the method",
          "items": {"type": "any"}
        },
        "kwargs": {
          "type": "object",
          "description": "Keyword arguments for the method",
          "additionalProperties": true
        }
      },
      "required": ["model", "method"]
    }
  },
  "required": ["arguments"]
}
```

#### data_export
```json
{
  "type": "object",
  "properties": {
    "arguments": {
      "type": "object",
      "properties": {
        "model": {
          "type": "string",
          "description": "Name of the Odoo model"
        },
        "ids": {
          "type": "array",
          "description": "List of record IDs to export",
          "items": {"type": "integer"}
        },
        "fields": {
          "type": "array",
          "description": "List of fields to export",
          "items": {"type": "string"}
        },
        "format": {
          "type": "string",
          "description": "Export format",
          "enum": ["csv", "excel", "json", "xml"]
        }
      },
      "required": ["model", "format"]
    }
  },
  "required": ["arguments"]
}
```

### Tool Aggiunto

Ho anche aggiunto la definizione mancante per il tool `odoo_call_method`:

```json
{
  "name": "odoo_call_method",
  "description": "Call a method on an Odoo model",
  "operations": ["call"],
  "inputSchema": {
    "type": "object",
    "properties": {
      "arguments": {
        "type": "object",
        "properties": {
          "model": {"type": "string", "description": "Name of the Odoo model"},
          "method": {"type": "string", "description": "Name of the method to call"},
          "args": {"type": "array", "description": "Positional arguments for the method", "items": {"type": "any"}},
          "kwargs": {"type": "object", "description": "Keyword arguments for the method", "additionalProperties": true}
        },
        "required": ["model", "method"]
      }
    },
    "required": ["arguments"]
  }
}
```

## Vantaggi della Soluzione

### 1. **Consistenza**
- Tutti i tool seguono lo stesso schema di base
- Facile da comprendere e utilizzare
- Riduce la confusione per gli sviluppatori

### 2. **Compatibilità con LangChain**
- Gli schemi sono ora validi per LangChain
- Elimina gli errori di validazione dello schema
- Migliore integrazione con framework esterni

### 3. **Manutenibilità**
- Codice più pulito e organizzato
- Facile aggiungere nuovi tool seguendo lo stesso pattern
- Riduce la duplicazione di codice

### 4. **Estensibilità**
- Schema flessibile che può essere esteso facilmente
- Supporto per parametri opzionali e obbligatori
- Validazione robusta dei parametri

## Esempi di Utilizzo

### Prima (Schema Inconsistente)
```json
// odoo_execute_kw (senza wrapper)
{
  "model": "res.partner",
  "method": "search_read",
  "args": [[], ["id", "name"]],
  "kwargs": {"limit": 10}
}

// odoo_search_read (con wrapper)
{
  "arguments": {
    "model": "res.partner",
    "domain": [["is_company", "=", True]],
    "fields": ["id", "name"]
  }
}
```

### Dopo (Schema Standardizzato)
```json
// odoo_execute_kw (con wrapper)
{
  "arguments": {
    "model": "res.partner",
    "method": "search_read",
    "args": [[], ["id", "name"]],
    "kwargs": {"limit": 10}
  }
}

// odoo_search_read (con wrapper)
{
  "arguments": {
    "model": "res.partner",
    "domain": [["is_company", "=", True]],
    "fields": ["id", "name"]
  }
}
```

## Tool Supportati

Dopo la standardizzazione, tutti questi tool seguono lo schema coerente:

1. **odoo_search_read** - Cerca e legge record in Odoo
2. **odoo_read** - Legge record specifici da Odoo
3. **odoo_execute_kw** - Esegue un metodo arbitrario su un modello Odoo
4. **odoo_call_method** - Chiama un metodo su un modello Odoo
5. **odoo_create** - Crea un nuovo record in Odoo
6. **odoo_write** - Aggiorna un record esistente in Odoo
7. **odoo_unlink** - Elimina un record da Odoo
8. **data_export** - Esporta dati Odoo in vari formati
9. **data_import** - Importa dati in Odoo
10. **report_generator** - Genera report Odoo

## Test

È stato creato un test (`test_schema_standardization.py`) per verificare che:
- Tutti i tool abbiano lo schema standardizzato
- Gli schemi siano validi per LangChain
- I parametri richiesti siano correttamente definiti

## Compatibilità

Questa modifica è **retrocompatibile** perché:
- Il codice esistente che gestisce i tool continua a funzionare
- La logica di estrazione dei parametri dal wrapper `arguments` è già implementata
- Non sono necessarie modifiche al codice di gestione dei tool

## Migrazione

Per utilizzare i tool con il nuovo schema standardizzato:

1. **Assicurati di usare il wrapper `arguments`** per tutti i tool
2. **Verifica che i parametri richiesti siano presenti** nel wrapper `arguments`
3. **Usa il test fornito** per validare i tuoi input

Esempio di migrazione:
```python
# Prima
response = await client.call_tool("odoo_execute_kw", {
    "model": "res.partner",
    "method": "search_read"
})

# Dopo
response = await client.call_tool("odoo_execute_kw", {
    "arguments": {
        "model": "res.partner",
        "method": "search_read"
    }
})
``` 