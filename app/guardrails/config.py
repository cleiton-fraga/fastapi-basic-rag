"""
Configuração da camada de guardrails (lida do ambiente, no estilo dos demais
módulos do projeto — cada módulo lê suas próprias variáveis via `os.getenv`).

A camada de segurança segue o mesmo princípio de **degradação graciosa** do
rerank: se um serviço caro (Llama Guard via Ollama) estiver indisponível, o
endpoint não quebra — o comportamento é controlado por `GUARDRAILS_FAIL_OPEN`.

Variáveis de ambiente
---------------------
Gerais:
- GUARDRAILS_ENABLED        (padrão "true")  liga/desliga toda a camada.
- GUARDRAILS_FAIL_OPEN      (padrão "true")  em erro de um guard, permite seguir.
- GUARDRAILS_AUDIT_TO_MONGO (padrão "true")  persiste a trilha de auditoria no Mongo.
- GUARDRAILS_AUDIT_COLLECTION (padrão "guardrail_audit")

Input rail:
- GUARDRAILS_INPUT_PII_ACTION (padrão "anonymize"; alternativa "block")
- GUARDRAILS_BANNED_TOPICS     (lista separada por vírgula, termos extras)

Output rail:
- GUARDRAILS_FAITHFULNESS_MIN_OVERLAP (padrão "0.18")  limiar do heurístico anti-alucinação.
- GUARDRAILS_OUTPUT_SAMPLE_RATE       (padrão "1.0")   amostragem das checagens caras de saída.
- GUARDRAILS_TONE_BANNED_PHRASES      (lista separada por vírgula; vazio = sem regra de tom)

Checagens caras (Llama Guard 3 via Ollama):
- GUARDRAILS_LLM_ENABLED      (padrão "false") liga o classificador Llama Guard.
- GUARDRAILS_OLLAMA_BASE_URL  (padrão "http://localhost:11434")
- GUARDRAILS_LLAMA_GUARD_MODEL (padrão "llama-guard3")
- GUARDRAILS_LLM_TIMEOUT      (padrão "20") segundos.
"""

import os
from typing import List


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _as_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: str) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# --- Gerais -----------------------------------------------------------------
ENABLED: bool = _as_bool(os.getenv("GUARDRAILS_ENABLED"), default=True)
FAIL_OPEN: bool = _as_bool(os.getenv("GUARDRAILS_FAIL_OPEN"), default=True)
AUDIT_TO_MONGO: bool = _as_bool(os.getenv("GUARDRAILS_AUDIT_TO_MONGO"), default=True)
AUDIT_COLLECTION: str = os.getenv("GUARDRAILS_AUDIT_COLLECTION", "guardrail_audit")

# --- Input rail -------------------------------------------------------------
INPUT_PII_ACTION: str = os.getenv("GUARDRAILS_INPUT_PII_ACTION", "anonymize").strip().lower()
EXTRA_BANNED_TOPICS: List[str] = _as_list(os.getenv("GUARDRAILS_BANNED_TOPICS"))

# --- Output rail ------------------------------------------------------------
FAITHFULNESS_MIN_OVERLAP: float = _as_float(
    os.getenv("GUARDRAILS_FAITHFULNESS_MIN_OVERLAP"), default=0.18
)
OUTPUT_SAMPLE_RATE: float = _as_float(os.getenv("GUARDRAILS_OUTPUT_SAMPLE_RATE"), default=1.0)
TONE_BANNED_PHRASES: List[str] = _as_list(os.getenv("GUARDRAILS_TONE_BANNED_PHRASES"))

# --- Checagens caras (Llama Guard via Ollama) -------------------------------
LLM_ENABLED: bool = _as_bool(os.getenv("GUARDRAILS_LLM_ENABLED"), default=False)
OLLAMA_BASE_URL: str = os.getenv("GUARDRAILS_OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
LLAMA_GUARD_MODEL: str = os.getenv("GUARDRAILS_LLAMA_GUARD_MODEL", "llama-guard3")
LLM_TIMEOUT: float = _as_float(os.getenv("GUARDRAILS_LLM_TIMEOUT"), default=20.0)

# --- Respostas seguras padrão (curto-circuito) ------------------------------
SAFE_INPUT_RESPONSE: str = (
    "Não posso ajudar com essa solicitação. Sua mensagem foi sinalizada pela "
    "camada de segurança. Reformule a pergunta mantendo-a relacionada ao "
    "conteúdo do documento e sem dados sensíveis."
)
SAFE_OUTPUT_RESPONSE: str = (
    "Não encontrei informação suficiente no contexto fornecido para responder "
    "a essa pergunta com segurança."
)
