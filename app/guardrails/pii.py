"""
Detecção e anonimização de PII e segredos.

- No **input rail**: anonimiza (ou bloqueia) dados sensíveis antes de mandar a
  pergunta ao LLM — nada de PII chega ao Ollama.
- No **output rail**: redige PII/segredos que por acaso vazem na resposta antes
  de devolver ao usuário.

Os padrões cobrem identificadores brasileiros (CPF, CNPJ, telefone) e genéricos
(e-mail, cartão de crédito), além de credenciais comuns (chaves de API, tokens
Bearer/JWT) — estes últimos importam sobretudo no vazamento de saída.

A redação substitui cada ocorrência por um rótulo `[TIPO_REDACTED]`, preservando
a forma do texto para auditoria sem expor o dado.
"""

import re
from typing import List, Pattern, Tuple

from app.guardrails.types import Severity, Violation

_FLAGS = re.IGNORECASE | re.UNICODE

# (rótulo, severidade, padrão). A ordem importa: padrões mais específicos antes
# dos genéricos (ex.: cartão antes de números soltos).
_PII_RULES: List[Tuple[str, Severity, Pattern[str]]] = [
    ("CPF", Severity.HIGH, re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", _FLAGS)),
    ("CNPJ", Severity.HIGH, re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", _FLAGS)),
    ("CREDIT_CARD", Severity.HIGH, re.compile(r"\b(?:\d[ -]?){13,16}\b", _FLAGS)),
    ("EMAIL", Severity.MEDIUM, re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", _FLAGS)),
    (
        "PHONE_BR",
        Severity.MEDIUM,
        re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b", _FLAGS),
    ),
]

# Segredos/credenciais — relevantes sobretudo no vazamento de saída.
_SECRET_RULES: List[Tuple[str, Severity, Pattern[str]]] = [
    ("OPENAI_KEY", Severity.HIGH, re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")),
    ("AWS_KEY", Severity.HIGH, re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("BEARER_TOKEN", Severity.HIGH, re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b", _FLAGS)),
    ("JWT", Severity.HIGH, re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b")),
]


def _scan(text: str, rules) -> Tuple[str, List[Violation]]:
    """Aplica `rules` redigindo as ocorrências e acumulando violações."""
    redacted = text
    violations: List[Violation] = []
    for label, severity, pattern in rules:
        found = pattern.findall(redacted)
        if not found:
            continue
        redacted = pattern.sub(f"[{label}_REDACTED]", redacted)
        violations.append(
            Violation(
                rail="pii",
                detector="regex",
                severity=severity,
                detail=f"{label} detectado e mascarado ({len(found)}x)",
                matches=[f"{label}:{len(found)}"],  # rótulo + contagem, nunca o valor
            )
        )
    return redacted, violations


def detect_pii(text: str, include_secrets: bool = False) -> Tuple[str, List[Violation]]:
    """Redige PII (e opcionalmente segredos) em `text`.

    Retorna `(texto_redigido, violações)`. Sem ocorrências, devolve o texto
    original e lista vazia.
    """
    rules = list(_PII_RULES)
    if include_secrets:
        rules = rules + _SECRET_RULES
    return _scan(text, rules)
