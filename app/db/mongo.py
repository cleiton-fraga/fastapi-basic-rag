"""
Conexão assíncrona com MongoDB via Motor.

- Carrega variáveis de ambiente de um arquivo .env (quando presente).
- Inicializa um cliente `AsyncIOMotorClient` usando a URI definida.
- Expõe `get_db()` para obter a instância do database configurado.

Variáveis de ambiente:
- MONGODB_URI: URI do MongoDB. Padrão: "mongodb://localhost:27017".
- MONGODB_DB: Nome do database utilizado. Padrão: "curso_api".
"""

import os
import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from dotenv import load_dotenv

load_dotenv()  # Carrega valores do arquivo .env para o ambiente (se existir)


MONGODB_URI: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")

# uuidRepresentation="standard" garante compatibilidade moderna com UUIDs.
# tlsCAFile=certifi.where() resolve SSL no Python 3.14+ com MongoDB Atlas.
client: AsyncIOMotorClient = AsyncIOMotorClient(
    MONGODB_URI, uuidRepresentation="standard", tlsCAFile=certifi.where()
)

def get_db() -> AsyncIOMotorDatabase:
    """Retorna a instância do database configurado via MONGODB_DB.

    Observações rápidas:
    - Lê o nome do database de MONGODB_DB a cada chamada.
    - Útil para injeção como dependência nas rotas do FastAPI.
    """
    return client[os.getenv("MONGODB_DB", "curso_api")]