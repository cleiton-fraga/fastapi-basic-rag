# ContextProject — fastapi-basic-rag

Resumo de contexto para orientar próximas interações no chat com foco em arquitetura, APIs, módulos e decisões do projeto.

## Visão geral
- API FastAPI com autenticação JWT, CRUD de usuários e fluxo RAG (Retrieval-Augmented Generation) com MongoDB + OpenAI.
- Entrypoint: `app/main.py` registra rotas versionadas sob `/api/v1`.
- Principais módulos:
  - Segurança (JWT/bcrypt): `app/core/security.py`
  - Banco (Motor/Mongo): `app/db/mongo.py`
  - Dependência de auth (Bearer): `app/deps/auth.py`
  - OpenAI (embeddings/chat): `app/llm/openai_client.py`
  - RAG (chunking/armazenamento/busca): pasta `app/rag/`
  - Guardrails (input/output rails + middleware): pasta `app/guardrails/`
  - Rotas v1: pasta `app/api/v1/`

## Stack e versões
- Python 3.11+
- FastAPI, Uvicorn
- motor/pymongo (MongoDB)
- python-jose, bcrypt
- pypdf
- openai
- python-dotenv

## Variáveis de ambiente (.env)
- Mongo:
  - `MONGODB_URI`, `MONGODB_DB` (ver `app/db/mongo.py`)
- OpenAI:
  - `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_CHAT_MODEL` (ver `app/llm/openai_client.py`)
- JWT:
  - `SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` (ver `app/core/security.py`)

## Endpoints (v1)
- Auth
  - POST `/auth/login` → modelo `Token` (ver `app/schemas/auth.py`) | fonte: `app/api/v1/auth.py`
  - POST `/auth/logout` → mensagem informativa | `app/api/v1/auth.py`
- Users (protegidos por Bearer)
  - GET `/users` → lista `UserOut` | `app/api/v1/users.py`
  - GET `/users/{user_id}` → `UserOut` | `app/api/v1/users.py`
  - POST `/users` → cria `UserOut` | `app/api/v1/users.py`
  - PUT `/users/{user_id}` → atualiza `UserOut` | `app/api/v1/users.py`
  - DELETE `/users/{user_id}` → 204 | `app/api/v1/users.py`
- RAG (protegidos por Bearer)
  - POST `/rag/documents` multipart (PDF + title) → `UploadDocResponse` | `app/api/v1/rag.py`
  - POST `/rag/ask` → `AnswerResponse` | `app/api/v1/rag.py`
    - Envolvido pelos guardrails: `apply_input_rail` (antes do LLM, com curto-circuito)
      e `apply_output_rail` (depois do LLM). Ver `app/guardrails/` e `docs/guardrails.md`.

## Símbolos importantes
- Segurança:
  - `app.core.security.hash_password`, `app.core.security.verify_password`, `app.core.security.create_access_token`, `app.core.security.decode_token`
  - `app.deps.auth.get_current_user_id`
- Banco:
  - `app.db.mongo.get_db`
- Users:
  - Rotas em `app/api/v1/users.py` com conversor `_to_user_out`
- RAG:
  - `app.rag.chunk.simple_chunk`
  - `app.rag.store.upsert_document`, `app.rag.store.get_owned_document_oid`, `app.rag.store.search_similar_chunks`
- OpenAI:
  - `app.llm.openai_client.embed_texts`, `app.llm.openai_client.chat_completion`

## Modelo de dados (Mongo)
- `users`: `{ _id, name, email, status, password_hash }`
- `documents`: `{ _id, title, content, owner }`
- `chunks`: `{ _id, document_id, chunk, embeddings }`

Índice vetorial necessário (coleção `chunks`, campo `embeddings`, nome `vector_index`, dimensões 3072 p/ `text-embedding-3-large`). Ver instruções no `README.md`.

## Fluxos principais
- Login
  1) Busca usuário por email
  2) Verifica senha com `app.core.security.verify_password`
  3) Gera JWT via `app.core.security.create_access_token`
- Users CRUD
  - Operações diretas em coleção `users` com validações básicas e hash de senha
- RAG
  - Upload PDF: valida MIME/arquivo, extrai até 15 páginas (função privada no router), chunking via `app.rag.chunk.simple_chunk`, embeddings com `app.llm.openai_client.embed_texts`, armazenamento via `app.rag.store.upsert_document`
  - Perguntar: valida posse com `app.rag.store.get_owned_document_oid`, gera embedding da pergunta, busca `$vectorSearch` via `app.rag.store.search_similar_chunks`, e responde com `app.llm.openai_client.chat_completion`

## Como executar
- Instalar dependências (venv recomendado). Ver `README.md`.
- Rodar:
```sh
uvicorn app.main:app --reload
```
- Docs: http://localhost:8000/docs

## Exemplos rápidos (cURL)
- Login (OAuth2 password):
```sh
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=<email>&password=<senha>"
```
- Listar usuários:
```sh
curl http://localhost:8000/api/v1/users -H "Authorization: Bearer <token>"
```
- Upload PDF:
```sh
curl -X POST http://localhost:8000/api/v1/rag/documents \
  -H "Authorization: Bearer <token>" \
  -F "file=@/caminho/arquivo.pdf;type=application/pdf" \
  -F "title=Meu Documento"
```

## Observações e dívidas técnicas
- Hash de senha duplicado em `app/api/v1/users.py`; padronizar usando `app.core.security.hash_password`.
- Nome do parâmetro em `list_users_endpoint`: `create_user_id` → `current_user_id` para consistência (`app/api/v1/users.py`).
- "Upsert" em `app.rag.store.upsert_document` realiza sempre insert; implementar upsert real caso necessário (por `owner+title`).
- Cliente OpenAI síncrono em rotas async; `chat_completion` em `/rag/ask` já é isolado em threadpool (`run_in_threadpool`), mas `embed_texts` ainda roda síncrono — considerar Async API ou threadpool (`app/llm/openai_client.py`).
- Validação MIME inclui "binary/octet-stream"; comum é "application/octet-stream" (`app/api/v1/rag.py`).
- Código legado não usado: `app/db/memory.py` (id numérico vs `UserOut.id` string).
- `load_dotenv()` chamado em múltiplos módulos; centralizar configurações reduziria acoplamento.
- Verificar índices adicionais no Mongo: unique `users.email`, `documents.owner`, `chunks.document_id`.

## Boas práticas sugeridas
- Criar módulo de settings (ex.: `app/core/settings.py`) e importar variáveis (evita múltiplos `load_dotenv()`).
- Mover extração de PDF para util (ex.: `app/rag/pdf.py`) e manter router fino.
- Adicionar hooks de startup para garantir índices (incluindo unique em `users.email`).
- Testes: criar fixtures de DB e mocks de OpenAI para validar rotas e fluxo RAG.

## Erros comuns
- 401 Invalid token: conferir header Authorization e `SECRET_KEY`.
- 400 PDF inválido/limite de 15 páginas no upload RAG.
- 404 No context found: checar índice vetorial e chunks inseridos.
- Dimensão do embedding incompatível com o índice: ajustar `dimensions`.

Referências rápidas:
- App: `app/main.py`
- Segurança: `app/core/security.py`, `app/deps/auth.py`
- Banco: `app/db/mongo.py`
- Users: `app/api/v1/users.py`, Schemas: `app/schemas/user.py`
- RAG: `app/api/v1/rag.py`, `app/rag/chunk.py`, `app/rag/store.py`, Schemas: `app/schemas/rag.py`
- OpenAI: `app/llm/openai_client.py`
- README: `README.md`
