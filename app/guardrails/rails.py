"""
Orquestração das rails de entrada e saída — o coração da camada de segurança.

A segurança envolve o núcleo RAG e intercepta a requisição em dois momentos:
nada chega ao Ollama sem passar pela validação de entrada (`apply_input_rail`),
e nada chega ao usuário sem passar pela validação de saída (`apply_output_rail`).

Ordem de execução em cada rail:
1. Checagens **baratas e síncronas** (regex/heurística) despachadas a um
   threadpool — isolando o trabalho CPU-bound do event loop.
2. Checagens **caras** (Llama Guard via Ollama) de forma assíncrona e, na saída,
   por amostragem (`OUTPUT_SAMPLE_RATE`) — para manter a latência no SLA.
3. Auditoria de qualquer violação.

As funções recebem `db`/`request_id`/`user_id`/`doc_id` apenas para a trilha de
auditoria; a lógica de decisão é independente do FastAPI.
"""

import asyncio
import logging
import random
import time
from typing import List, Optional

from app.guardrails import audit, config, detectors, llama_guard
from app.guardrails.pii import detect_pii
from app.guardrails.types import Action, GuardResult, RailStage, Severity, Violation

logger = logging.getLogger(__name__)


def _allow(stage: RailStage, text: str) -> GuardResult:
    return GuardResult(stage=stage, allowed=True, action=Action.ALLOW, text=text)


async def apply_input_rail(
    question: str,
    *,
    db=None,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> GuardResult:
    """Valida a pergunta ANTES de qualquer chamada ao LLM/Ollama.

    Reprova (curto-circuito) em prompt injection, jailbreak, tópico proibido ou
    veredito `unsafe` do Llama Guard. PII é anonimizada (padrão) ou bloqueia,
    conforme `GUARDRAILS_INPUT_PII_ACTION`. Quando reprova, devolve `allowed=False`
    e uma `safe_response` — sem nunca acionar o LLM, economizando inferência.
    """
    start = time.perf_counter()
    if not config.ENABLED:
        return _allow(RailStage.INPUT, question)

    text = question
    violations: List[Violation] = []
    blocked = False

    # 1) checagens baratas (CPU-bound) fora do event loop
    violations.extend(await asyncio.to_thread(detectors.detect_input, question))
    if violations:
        blocked = True  # injeção/jailbreak/tópico proibido → reprova

    # 2) PII: anonimiza (padrão) ou bloqueia
    redacted, pii_violations = await asyncio.to_thread(detect_pii, question, False)
    if pii_violations:
        violations.extend(pii_violations)
        if config.INPUT_PII_ACTION == "block":
            blocked = True
        else:
            text = redacted  # segue anonimizada para o LLM

    # 3) Llama Guard (caro, assíncrono) — só se ainda não reprovou
    if not blocked and config.LLM_ENABLED:
        verdict = await llama_guard.classify_input(text)
        if verdict is not None and verdict.unsafe:
            blocked = True
            violations.append(Violation(
                rail="llama_guard", detector="llama_guard", severity=Severity.HIGH,
                detail="Llama Guard classificou a entrada como unsafe.",
                matches=verdict.categories or ["unsafe"],
            ))

    if blocked:
        action, allowed, safe = Action.BLOCK, False, config.SAFE_INPUT_RESPONSE
    elif text != question:
        action, allowed, safe = Action.ANONYMIZE, True, None
    else:
        action, allowed, safe = Action.ALLOW, True, None

    result = GuardResult(
        stage=RailStage.INPUT, allowed=allowed, action=action,
        text=(safe if blocked else text), violations=violations,
        safe_response=safe, latency_ms=(time.perf_counter() - start) * 1000,
    )
    await audit.record(result, db=db, request_id=request_id, user_id=user_id, doc_id=doc_id)
    return result


async def apply_output_rail(
    answer: str,
    *,
    context: str,
    question: str = "",
    db=None,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> GuardResult:
    """Valida a resposta DEPOIS do LLM e antes do usuário.

    - Fidelidade ao contexto (anti-alucinação): se a resposta não se sustenta nos
      trechos recuperados, é substituída por uma resposta segura.
    - Toxicidade / veredito `unsafe`: substitui por resposta segura.
    - Vazamento de PII/segredos: redige a resposta no lugar.
    - Tom de voz: sinaliza desvios às diretrizes (configurável).

    Sempre devolve algo seguro (`allowed=True`); `action`/`text` indicam o que
    aconteceu com a resposta final.
    """
    start = time.perf_counter()
    if not config.ENABLED:
        return _allow(RailStage.OUTPUT, answer)

    text = answer
    violations: List[Violation] = []
    replace = False  # substituir por resposta segura padrão

    # 1) checagens baratas (CPU-bound) fora do event loop
    tox = await asyncio.to_thread(detectors.detect_toxicity, answer)
    tone = await asyncio.to_thread(detectors.detect_tone, answer)
    faith = await asyncio.to_thread(detectors.detect_faithfulness, answer, context)
    violations.extend(tox + tone + faith)
    if tox or faith:
        replace = True  # ofensivo ou não fundamentado → substitui

    # 2) vazamento de PII/segredos → redige no lugar (não substitui tudo)
    redacted, leak_violations = await asyncio.to_thread(detect_pii, text, True)
    if leak_violations:
        for v in leak_violations:
            v.rail = "pii_leak"
        violations.extend(leak_violations)
        text = redacted

    # 3) Llama Guard de saída (caro, assíncrono, amostrado)
    if config.LLM_ENABLED and random.random() < config.OUTPUT_SAMPLE_RATE:
        verdict = await llama_guard.classify_output(question, answer)
        if verdict is not None and verdict.unsafe:
            replace = True
            violations.append(Violation(
                rail="llama_guard", detector="llama_guard", severity=Severity.HIGH,
                detail="Llama Guard classificou a resposta como unsafe.",
                matches=verdict.categories or ["unsafe"],
            ))

    if replace:
        action, text = Action.BLOCK, config.SAFE_OUTPUT_RESPONSE
    elif text != answer:
        action = Action.REWRITE  # PII redigida
    else:
        action = Action.ALLOW

    result = GuardResult(
        stage=RailStage.OUTPUT, allowed=True, action=action, text=text,
        violations=violations, latency_ms=(time.perf_counter() - start) * 1000,
    )
    await audit.record(result, db=db, request_id=request_id, user_id=user_id, doc_id=doc_id)
    return result
