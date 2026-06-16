# fastapi-basic-rag

API FastAPI com autenticação JWT, CRUD de usuários e um exemplo de RAG (Retrieval-Augmented Generation) usando MongoDB (Motor) + OpenAI (embeddings e chat).

- Código principal: [app/main.py](app/main.py)
- Rotas:
  - Auth: [app/api/v1/auth.py](app/api/v1/auth.py)
  - Users: [app/api/v1/users.py](app/api/v1/users.py)
  - RAG: [app/api/v1/rag.py](app/api/v1/rag.py)
- Núcleo de segurança: [app/core/security.py](app/core/security.py)
- Banco: [app/db/mongo.py](app/db/mongo.py)
- Client OpenAI: [app/llm/openai_client.py](app/llm/openai_client.py)
- RAG utils: [app/rag/chunk.py](app/rag/chunk.py), [app/rag/store.py](app/rag/store.py)
- Schemas Pydantic: [app/schemas](app/schemas)

## Visão geral

- Autenticação via OAuth2 password flow com JWT Bearer.
- CRUD de usuários protegido por token.
- Upload de PDF (até 15 páginas), extração de texto, chunking simples e indexação de embeddings no MongoDB.
- Pergunta-resposta baseada em recuperação vetorial dos chunks do documento.

Arquitetura (alto nível):
- API (FastAPI): camadas de rotas, dependências e schemas.
- Segurança: JWT HS256 e bcrypt para senhas ([app/core/security.py](app/core/security.py)).
- Persistência: MongoDB assíncrono (Motor) ([app/db/mongo.py](app/db/mongo.py)).
- LLM: OpenAI para embeddings e chat ([app/llm/openai_client.py](app/llm/openai_client.py)).
- RAG: chunking + upsert + busca vetorial ([app/rag/chunk.py](app/rag/chunk.py), [app/rag/store.py](app/rag/store.py)).

## Pastas e módulos

- [app/api/v1/auth.py](app/api/v1/auth.py): Login/logout. Usa [`app.core.security.create_access_token`](app/core/security.py) e [`app.core.security.verify_password`](app/core/security.py).
- [app/api/v1/users.py](app/api/v1/users.py): Endpoints de usuários. Hash de senha local, CRUD em coleção users.
- [app/api/v1/rag.py](app/api/v1/rag.py): Upload de PDFs e perguntas. Usa:
  - [`app.rag.chunk.simple_chunk`](app/rag/chunk.py)
  - [`app.llm.openai_client.embed_texts`](app/llm/openai_client.py)
  - [`app.llm.openai_client.chat_completion`](app/llm/openai_client.py)
  - [`app.rag.store.upsert_document`](app/rag/store.py)
  - [`app.rag.store.search_similar_chunks`](app/rag/store.py)
  - [`app.rag.store.get_owned_document_oid`](app/rag/store.py)
- [app/core/security.py](app/core/security.py): JWT (HS256) e bcrypt.
- [app/db/mongo.py](app/db/mongo.py): Cliente Motor + `get_db()`.
- [app/deps/auth.py](app/deps/auth.py): Dependência para extrair `sub` do JWT.
- [app/llm/openai_client.py](app/llm/openai_client.py): OpenAI Embeddings/Chat.
- [app/rag/store.py](app/rag/store.py): Upsert de documento e chunks; busca vetorial por `$vectorSearch`.

## Requisitos

- Python 3.11+
- MongoDB Atlas com Search habilitado (ou MongoDB com suporte ao `$vectorSearch`)
- Conta OpenAI e chave de API
- Pip/venv (ou gerenciador equivalente)

Principais dependências (pip):
- fastapi, uvicorn
- motor, pymongo
- python-jose, bcrypt
- pypdf
- python-dotenv
- openai

## Configuração (.env)

Crie um arquivo `.env` na raiz com:

```
# Mongo
MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>/?retryWrites=true&w=majority
MONGODB_DB=curso_api

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
OPENAI_CHAT_MODEL=gpt-4o-mini

# JWT
SECRET_KEY=troque-esta-chave
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

- O modelo `text-embedding-3-large` gera vetores de dimensão 3072 (ajuste o índice vetorial conforme essa dimensão).
- As variáveis são carregadas por [`dotenv.load_dotenv()`](app/llm/openai_client.py), ([app/db/mongo.py](app/db/mongo.py)) e ([app/core/security.py](app/core/security.py)).

## Índice vetorial no MongoDB (Atlas Search)

Crie um índice de busca vetorial chamado `vector_index` na coleção `chunks` para o campo `embeddings`. Em ambientes Atlas, execute no MongoDB Shell:

```
use curso_api
db.runCommand({
  createSearchIndexes: "chunks",
  indexes: [
    {
      name: "vector_index",
      definition: {
        mappings: {
          dynamic: true,
          fields: {
            embeddings: {
              type: "knnVector",
              dimensions: 3072,        // ajuste se trocar o modelo de embedding
              similarity: "cosine"
            }
          }
        }
      }
    }
  ]
})
```

- O pipeline de busca usa `$vectorSearch` com `index: "vector_index"` e filtro por `document_id` (veja [`app.rag.store.search_similar_chunks`](app/rag/store.py)).

## Busca híbrida e re-ranking

A rota `/rag/ask` usa **busca híbrida** (vetorial + lexical/BM25) fundida pelo
operador nativo `$rankFusion` (requer **MongoDB Atlas 8.1+**) e, em seguida,
**re-ranking** por cross-encoder via API (padrão: Cohere). Veja
[`app.rag.store.hybrid_search_chunks`](app/rag/store.py) e [`app.rag.rerank.rerank`](app/rag/rerank.py).

### Índice de texto (Atlas Search) — necessário para o BM25

Além do `vector_index`, crie um índice de texto `text_index` na coleção `chunks`
indexando o campo `chunk` (busca lexical) e `document_id` (filtro por documento):

```
use curso_api
db.runCommand({
  createSearchIndexes: "chunks",
  indexes: [
    {
      name: "text_index",
      definition: {
        mappings: {
          dynamic: false,
          fields: {
            chunk: { type: "string" },
            document_id: { type: "objectId" }
          }
        }
      }
    }
  ]
})
```

### Variáveis de ambiente do rerank

- `RERANK_API_KEY`: chave da API de rerank. **Se ausente, o rerank é desativado**
  e os candidatos da busca híbrida são usados na ordem original (sem quebrar o `/ask`).
- `RERANK_BASE_URL`: endpoint base (padrão: `https://api.cohere.com`). Troque para
  usar Jina/Voyage com a mesma estrutura de request `/v2/rerank`.
- `RERANK_MODEL`: modelo de rerank (padrão: `rerank-v3.5`).

### Parâmetros do `/rag/ask`

- `candidates` (padrão: 30): quantidade recuperada na busca híbrida antes do rerank.
- `k` (padrão: 5): quantidade de chunks finais (após rerank) usados no contexto.

## Instalação

- Criar e ativar virtualenv:
```
python -m venv .venv
source .venv/bin/activate
```

- Instalar dependências:
```
pip install -U pip
pip install fastapi uvicorn[standard] motor "pymongo>=4.6" python-jose[cryptography] bcrypt pypdf python-dotenv openai
```

## Executando

- Iniciar o servidor:
```
uvicorn app.main:app --reload
```

- Documentação:
  - Swagger UI: http://localhost:8000/docs
  - ReDoc: http://localhost:8000/redoc

## Bootstrapping: criando o primeiro usuário

Os endpoints de usuários exigem token. Para criar o primeiro usuário, insira manualmente um documento em `users` com `password_hash` em bcrypt.

Gerando hash em Python REPL:

```
python -c "import bcrypt; print(bcrypt.hashpw(b'sua-senha', bcrypt.gensalt()).decode())"
```

Inserindo no Mongo Shell:

```
use curso_api
db.users.insertOne({
  name: "Admin",
  email: "admin@example.com",
  status: "ativo",
  password_hash: "<cole-o-hash-aqui>"
})
```

Depois, faça login e use o token para as demais rotas.

## Endpoints e exemplos

Base URL: `http://localhost:8000/api/v1`

- Login (OAuth2 password)
```
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=sua-senha"
```

Resposta:
```
{
  "access_token": "...",
  "token_type": "bearer"
}
```

Use o header `Authorization: Bearer <token>` nas rotas protegidas.

- Listar usuários
```
curl http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer <token>"
```

- Criar usuário
```
curl -X POST http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alice",
    "email": "alice@example.com",
    "status": "ativo",
    "password": "segredo123"
  }'
```

- Upload de documento (PDF) para RAG
```
curl -X POST http://localhost:8000/api/v1/rag/documents \
  -H "Authorization: Bearer <token>" \
  -F "file=@/caminho/arquivo.pdf;type=application/pdf" \
  -F "title=Meu Documento"
```

Resposta:
```
{
  "doc_id": "<ObjectId>",
  "chunks": 12
}
```

- Perguntar com base no documento
```
curl -X POST http://localhost:8000/api/v1/rag/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "<ObjectId>",
    "question": "Qual é o objetivo do documento?",
    "k": 5
  }'
```

Resposta:
```
{
  "answer": "…",
  "sources": ["chunk_id=...","chunk_id=..."]
}
```

Observações do RAG:
- Extração de PDF limitada a 15 páginas ([app/api/v1/rag.py](app/api/v1/rag.py)).
- Chunking com janelas de 1000 caracteres e sobreposição de 100 ([`app.rag.chunk.simple_chunk`](app/rag/chunk.py)).
- Embeddings e chat via OpenAI ([`app.llm.openai_client.embed_texts`](app/llm/openai_client.py), [`app.llm.openai_client.chat_completion`](app/llm/openai_client.py)).
- Busca vetorial com `$vectorSearch` em `chunks.embeddings` usando índice `vector_index` ([`app.rag.store.search_similar_chunks`](app/rag/store.py)).

## Variáveis de ambiente (referência)

- Mongo: `MONGODB_URI`, `MONGODB_DB` ([app/db/mongo.py](app/db/mongo.py))
- OpenAI: `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL`, `OPENAI_CHAT_MODEL` ([app/llm/openai_client.py](app/llm/openai_client.py))
- JWT: `SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` ([app/core/security.py](app/core/security.py))

## Estrutura de dados

- Coleção `documents`: `{ _id, title, content, owner }`
- Coleção `chunks`: `{ _id, document_id, chunk, embeddings }`
- Coleção `users`: `{ _id, name, email, status, password_hash }`

## Erros comuns e solução

- 401 Invalid token: verifique `Authorization: Bearer <token>` e `SECRET_KEY`.
- 400 Falha ao ler PDF: cheque tipo/arquivo e limite de páginas.
- 404 No context found: verifique se o índice vetorial existe e se há chunks inseridos.
- Dimensão incompatível: ajuste `dimensions` do índice conforme o modelo de embedding (ex.: 3072).

## Desenvolvimento

- Padrões de schema em [app/schemas](app/schemas).
- Dependência de autenticação via [`app.deps.auth.get_current_user_id`](app/deps/auth.py).
- Lógica de CRUD em [app/api/v1/users.py](app/api/v1/users.py).
- Operações RAG em [app/rag/store.py](app/rag/store.py).

## Licença

Licenciado sob MIT. Veja [LICENSE](LICENSE).
