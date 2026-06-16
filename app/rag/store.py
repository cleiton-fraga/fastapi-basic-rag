"""
Operações de RAG sobre MongoDB: upsert de documentos e busca vetorial de chunks.

- Depende do cliente OpenAI para embeddings e de `get_db()` (indiretamente via handlers) para acesso ao MongoDB.
- Indexe previamente a coleção `chunks` com um índice vetorial chamado `vector_index` no campo `embeddings`.

Variáveis de ambiente (indiretas):
- OPENAI_API_KEY, OPENAI_EMBEDDING_MODEL (ver app/llm/openai_client.py).
- MONGODB_URI, MONGODB_DB (ver app/db/mongo.py).
"""

from typing import List, Dict, Any, Optional
from bson import ObjectId
from app.llm.openai_client import embed_texts
from app.rag.chunk import simple_chunk

# Usa motor no app para obter db (get_db). Aqui, implementamos funções de alto nível.

async def upsert_document(
        db, 
        title: str, 
        content: str,
        owner_id: str) -> Dict[str, Any]:
    """Insere/atualiza documento base e seus chunks com embeddings.

    Fluxo:
    1) insere documento em `documents` e obtém o ObjectId.
    2) realiza chunking (`simple_chunk`) e gera embeddings (`embed_texts`).
    3) substitui chunks existentes por novos em `chunks`.
    Retorna: id lógico do documento (string) e quantidade de chunks.
    """
    

    # 1) cria documento base em 'documents' e obtém o _id
    res = await db["documents"].insert_one({
        "title": title,
        "content": content,
        "owner": owner_id,
    })
    document_id = res.inserted_id

    # 2) chunking + embeddings
    chunks = simple_chunk(content)
    embeddings = embed_texts(chunks)

    # 3) remove chunks antigos e insere os novos
    await db["chunks"].delete_many({"document_id": document_id})
    docs = []
    for chunk_text, emb in zip(chunks, embeddings):
        docs.append({
            "document_id": document_id,
            "chunk": chunk_text,
            "embeddings": emb,
        })
    if docs:
        await db["chunks"].insert_many(docs)
    return {"doc_id": str(document_id), "chunks": len(docs)}

async def get_owned_document_oid(
        db,
        document_id: str,
        owner_id: str
) -> Optional[ObjectId]: 
    """Retorna o ObjectId do documento se pertencer ao owner; caso contrário, None."""
    try:
        oid = ObjectId(document_id)
    except Exception:
        return None
    
    doc = await db["documents"].find_one({"_id": oid, "owner": owner_id})
    
    if not doc:
        return None
    return oid

async def search_similar_chunks(db, doc_id: str, query_embedding: List[float], k: int = 5) -> List[Dict[str, Any]]:
    """Busca chunks similares por vetor usando `$vectorSearch` na coleção `chunks`.

    Detalhes:
    - Filtra por `document_id` para restringir a um documento.
    - Usa índice vetorial `vector_index` em `embeddings`.
    - `k` limita a quantidade de resultados.
    """
    # doc_id é string de ObjectId
    try:
        oid = ObjectId(doc_id)
    except Exception:
        return []
    doc = await db["documents"].find_one({"_id": oid})
    if not doc:
        return []
    document_id: ObjectId = doc["_id"]

    pipeline = [
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embeddings",
                "queryVector": query_embedding,
                "numCandidates": 200,
                "limit": k,
                "filter": {"document_id": document_id}
            }
        },
        {"$project": {"_id": 1, "chunk": 1, "document_id": 1, "score": {"$meta": "vectorSearchScore"}}}
    ]
    cursor = db["chunks"].aggregate(pipeline)
    return [d async for d in cursor]


async def hybrid_search_chunks(
    db,
    doc_id: str,
    query_text: str,
    query_embedding: List[float],
    k: int = 30,
    vector_weight: float = 0.7,
    text_weight: float = 0.3,
) -> List[Dict[str, Any]]:
    """Busca híbrida (vetorial + lexical/BM25) fundida com `$rankFusion`.

    Combina dois pipelines ranqueados sobre a coleção `chunks`:
    - `vector`: `$vectorSearch` no campo `embeddings` (índice `vector_index`).
    - `text`: `$search` (Atlas Search, índice `text_index`) por BM25 no campo `chunk`.

    A fusão é feita por Reciprocal Rank Fusion via operador nativo `$rankFusion`
    (requer MongoDB Atlas 8.1+). Ambos os pipelines são filtrados pelo documento.

    Retorna até `k` chunks com `score` (do `$rankFusion`), ordenados por relevância.
    Pensado para recuperar um conjunto amplo a ser reordenado por rerank.
    """
    try:
        oid = ObjectId(doc_id)
    except Exception:
        return []
    doc = await db["documents"].find_one({"_id": oid})
    if not doc:
        return []
    document_id: ObjectId = doc["_id"]

    pipeline = [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "vector": [
                            {
                                "$vectorSearch": {
                                    "index": "vector_index",
                                    "path": "embeddings",
                                    "queryVector": query_embedding,
                                    "numCandidates": 200,
                                    "limit": k,
                                    "filter": {"document_id": document_id},
                                }
                            }
                        ],
                        "text": [
                            {
                                "$search": {
                                    "index": "text_index",
                                    "compound": {
                                        "must": [
                                            {"text": {"query": query_text, "path": "chunk"}}
                                        ],
                                        "filter": [
                                            {"equals": {"path": "document_id", "value": document_id}}
                                        ],
                                    },
                                }
                            },
                            {"$limit": k},
                        ],
                    }
                },
                "combination": {"weights": {"vector": vector_weight, "text": text_weight}},
            }
        },
        {"$limit": k},
        {
            "$project": {
                "_id": 1,
                "chunk": 1,
                "document_id": 1,
                "score": {"$meta": "score"},
            }
        },
    ]
    cursor = db["chunks"].aggregate(pipeline)
    return [d async for d in cursor]