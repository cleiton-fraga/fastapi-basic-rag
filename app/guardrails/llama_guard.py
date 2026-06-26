"""
Classificador Llama Guard 3 via Ollama — a checagem **cara** das rails.

Reaproveita o runtime que já temos: o mesmo Ollama que serve o LLM serve o guard
(open-weight, sem dependência de nuvem). É a segunda camada, empilhada sobre os
regex baratos — porque nenhuma técnica isolada basta.

Usa `httpx.AsyncClient` (já nas dependências) contra a API nativa do Ollama
(`/api/chat`), sem SDK adicional. Llama Guard classifica a última mensagem da
conversa e responde `safe` ou `unsafe\nS<categoria>` segundo sua taxonomia.

Degradação graciosa: desligado por padrão (`GUARDRAILS_LLM_ENABLED=false`) e, em
erro de rede/serviço, devolve `None` (veredito desconhecido) — quem chama decide
conforme `GUARDRAILS_FAIL_OPEN`. Uma falha do guard nunca derruba o endpoint.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.guardrails import config

logger = logging.getLogger(__name__)


@dataclass
class GuardVerdict:
    unsafe: bool
    categories: List[str]
    raw: str


def _parse(content: str) -> GuardVerdict:
    """Interpreta a saída textual do Llama Guard: 'safe' | 'unsafe\\nS1,S2'."""
    text = (content or "").strip()
    first = text.splitlines()[0].strip().lower() if text else ""
    unsafe = first.startswith("unsafe")
    categories: List[str] = []
    if unsafe:
        lines = text.splitlines()
        if len(lines) > 1:
            categories = [c.strip() for c in lines[1].replace(",", " ").split() if c.strip()]
    return GuardVerdict(unsafe=unsafe, categories=categories, raw=text)


async def _classify(messages: List[dict]) -> Optional[GuardVerdict]:
    """Chama o Ollama com uma conversa e devolve o veredito, ou `None` em falha/desligado."""
    if not config.LLM_ENABLED:
        return None
    try:
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": config.LLAMA_GUARD_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0},
                },
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
    except Exception as exc:  # rede, timeout, modelo ausente — degrada sem quebrar
        logger.warning(
            "Llama Guard indisponível (model=%s): %s", config.LLAMA_GUARD_MODEL, exc
        )
        return None
    return _parse(content)


async def classify_input(question: str) -> Optional[GuardVerdict]:
    """Classifica uma mensagem do usuário (entrada)."""
    return await _classify([{"role": "user", "content": question}])


async def classify_output(question: str, answer: str) -> Optional[GuardVerdict]:
    """Classifica a resposta do assistente no contexto da pergunta (saída).

    Llama Guard avalia o último turno; passar a pergunta + a resposta faz o
    classificador julgar especificamente o turno do assistente.
    """
    return await _classify([
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ])
