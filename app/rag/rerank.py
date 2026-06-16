"""
Re-ranking de chunks por cross-encoder via API de rerank (padrão: Cohere).

- Reordena um conjunto de candidatos olhando query + texto juntos, mais preciso
  que a similaridade de cosseno usada na recuperação.
- Usa `httpx` (já presente nas dependências); não exige SDK adicional.
- Se a chave não estiver configurada, `rerank` é um no-op e devolve os candidatos
  na ordem original (degradação graciosa).

Variáveis de ambiente:
- RERANK_API_KEY: chave da API de rerank (ex.: Cohere). Se ausente, rerank é desativado.
- RERANK_BASE_URL: endpoint base (padrão: "https://api.cohere.com").
- RERANK_MODEL: modelo de rerank (padrão: "rerank-v3.5").
"""

import logging
import os
from typing import List, Dict, Any

import httpx

logger = logging.getLogger(__name__)

RERANK_API_KEY = os.getenv("RERANK_API_KEY")
RERANK_BASE_URL = os.getenv("RERANK_BASE_URL", "https://api.cohere.com").rstrip("/")
RERANK_MODEL = os.getenv("RERANK_MODEL", "rerank-v3.5")

# Campo de texto de cada chunk usado como documento no rerank.
_TEXT_FIELD = "chunk"


def is_enabled() -> bool:
    """Indica se o re-ranking está configurado (chave presente)."""
    return bool(RERANK_API_KEY)


def rerank(query: str, candidates: List[Dict[str, Any]], top_n: int) -> List[Dict[str, Any]]:
    """Reordena `candidates` por relevância à `query` e devolve os `top_n` melhores.

    - `candidates`: lista de documentos de chunk (cada um com a chave `chunk`).
    - Em caso de chave ausente ou erro de rede/API, faz fallback para os primeiros
      `top_n` candidatos na ordem recebida, sem interromper a resposta.
    - Anexa `rerank_score` a cada item retornado quando o rerank é aplicado.
    """
    if not candidates:
        return []
    if not is_enabled():
        return candidates[:top_n]

    documents = [c.get(_TEXT_FIELD, "") for c in candidates]
    try:
        resp = httpx.post(
            f"{RERANK_BASE_URL}/v2/rerank",
            headers={
                "Authorization": f"Bearer {RERANK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": RERANK_MODEL,
                "query": query,
                "documents": documents,
                "top_n": min(top_n, len(documents)),
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as exc:  # rede, auth, payload — degrada sem quebrar o /ask
        logger.warning("Rerank falhou (model=%s), usando ordem original: %s", RERANK_MODEL, exc)
        return candidates[:top_n]

    reranked: List[Dict[str, Any]] = []
    for r in results:
        idx = r.get("index")
        if idx is None or idx >= len(candidates):
            continue
        item = dict(candidates[idx])
        item["rerank_score"] = r.get("relevance_score")
        reranked.append(item)
    return reranked or candidates[:top_n]
