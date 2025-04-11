from pydantic import BaseModel, Field, ValidationError, validator
from typing import Optional, List, Dict, Any, Union

# Modelli Base per JSON-RPC
class BaseJsonRpcRequest(BaseModel):
    jsonrpc: str = Field("2.0", const=True)
    method: str
    id: Optional[Union[str, int]] = None

# Modelli per i parametri specifici di ogni metodo

class EchoParams(BaseModel):
    message: Optional[str] = "echo!"

class CreateSessionParams(BaseModel):
    username: Optional[str] = None
    api_key: Optional[str] = None

    @validator('*', pre=True, always=True)
    def check_at_least_one(cls, v, values):
        if not values.get('username') and not values.get('api_key'):
            raise ValueError("Either 'username' or 'api_key' must be provided for create_session")
        # Se username è fornito, api_key (o password) potrebbe essere necessaria a seconda della config Odoo
        # Ma la logica di autenticazione gestirà questo, qui validiamo solo la presenza di almeno uno.
        return v

class DestroySessionParams(BaseModel):
    session_id: str = Field(..., min_length=1) # Assicuriamo che non sia vuoto

class CallOdooParams(BaseModel):
    model: str = Field(..., min_length=1)
    method: str = Field(..., min_length=1)
    args: List[Any] = Field(default_factory=list)
    kwargs: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    uid: Optional[int] = None
    password: Optional[str] = None # Potrebbe essere api_key a seconda della config

    @validator('password', always=True)
    def check_password_with_uid(cls, v, values):
        uid = values.get('uid')
        if uid is not None and v is None:
            raise ValueError("Parameter 'password' (or api_key) is required if 'uid' is provided.")
        return v

    @validator('uid', always=True)
    def check_uid_with_password(cls, v, values):
        password = values.get('password')
        if password is not None and v is None:
            raise ValueError("Parameter 'uid' is required if 'password' (or api_key) is provided.")
        return v

# Mappatura nome metodo -> modello parametri
METHOD_PARAMS_MAP: Dict[str, Optional[Type[BaseModel]]] = {
    "echo": EchoParams,
    "create_session": CreateSessionParams,
    "destroy_session": DestroySessionParams,
    "call_odoo": CallOdooParams,
    # Aggiungere altri metodi qui se necessario
}

def validate_request_params(method: str, params: Dict[str, Any]) -> BaseModel:
    """
    Valida i parametri di una richiesta JSON-RPC usando Pydantic.

    Args:
        method: Il nome del metodo JSON-RPC.
        params: Il dizionario dei parametri ricevuti.

    Returns:
        Un'istanza del modello Pydantic validato.

    Raises:
        ValidationError: Se la validazione fallisce.
        KeyError: Se il metodo non è mappato a un modello di validazione.
    """
    model_class = METHOD_PARAMS_MAP.get(method)
    if model_class is None:
        # Se un metodo non ha parametri specifici o non è nel map,
        # possiamo decidere di non validare o usare un modello vuoto.
        # Per ora, solleviamo un errore se non è esplicitamente mappato
        # (tranne forse per metodi interni/di test senza parametri).
        # Se 'echo' non avesse parametri, potremmo fare:
        # if method == 'echo': return BaseModel() # Modello vuoto
        raise KeyError(f"No validation model defined for method: {method}")

    return model_class(**params)
