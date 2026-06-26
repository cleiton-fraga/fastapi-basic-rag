"""
Entrypoint da aplicação FastAPI.

- Carrega variáveis de ambiente via .env.
- Cria a aplicação e registra os routers de usuários e RAG sob o prefixo /api/v1.
- Envolve o núcleo com a camada de guardrails (middleware de correlação +
  rails de entrada/saída aplicadas nos endpoints).
"""

from fastapi import FastAPI
from app.api.v1.users import router as users_router
from app.api.v1.rag import router as rag_router
from app.api.v1.auth import router as auth_router
from app.guardrails import GuardrailsMiddleware


from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Users API", version="1.0.0")

# Envelope transversal da camada de segurança: request_id (correlação da trilha
# de auditoria) e latência. A aplicação das rails de conteúdo fica nos endpoints,
# onde o contexto recuperado está disponível para o output rail.
app.add_middleware(GuardrailsMiddleware)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")
