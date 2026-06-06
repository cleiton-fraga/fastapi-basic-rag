"""
Cliente OpenAI para embeddings e chat.

- Carrega variáveis de ambiente via .env.
- Expõe funções utilitárias para gerar embeddings e completions de chat.

Variáveis de ambiente:
- OPENAI_API_KEY: chave da API.
- OPENAI_BASE_URL: endpoint compatível com API OpenAI (ex.: Ollama em http://localhost:11434/v1).
- OPENAI_EMBEDDING_MODEL: modelo de embedding (padrão: "text-embedding-3-large").
- OPENAI_CHAT_MODEL: modelo de chat (padrão: "gpt-4o-mini").
"""

import logging
import os
from typing import List
from openai import OpenAI

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL") or None
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logger.warning("OpenAI client base_url=%s", OPENAI_BASE_URL or "(default OpenAI)")

CLIENT = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Gera embeddings para uma lista de textos usando `EMBEDDING_MODEL`."""
    try:
        resp = CLIENT.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    except Exception as exc:
        effective_url = OPENAI_BASE_URL or "https://api.openai.com/v1"
        raise RuntimeError(
            f"Embeddings call failed (base_url={effective_url!r}, model={EMBEDDING_MODEL!r}): {exc}"
        ) from exc
    return [d.embedding for d in resp.data]


def chat_completion(system_prompt: str, user_prompt: str) -> str:
    """Obtém uma resposta de chat do modelo configurado em `CHAT_MODEL`.

    Observação: `temperature=0.2` para reduzir variância nas respostas.
    """
    resp = CLIENT.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content or ""