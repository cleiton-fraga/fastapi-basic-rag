"""
Trilha de auditoria das rails.

Fundamental para compliance: cada bloqueio (e cada anonimização/reescrita) é
registrado, criando uma trilha monitorável — algo que deixa de ser opcional sob
regimes como o EU AI Act.

Dois destinos, ambes best-effort (nunca quebram a requisição):
- log estruturado (sempre);
- coleção MongoDB `guardrail_audit` (se `GUARDRAILS_AUDIT_TO_MONGO` e houver `db`).

Por design, **não** registramos o texto cru que disparou a regra — apenas
rótulos, severidades e contagens das violações (ver `Violation.matches`), para a
própria trilha não virar um repositório de PII.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.guardrails import config
from app.guardrails.types import GuardResult

logger = logging.getLogger("app.guardrails.audit")


def _build_event(
    result: GuardResult,
    *,
    request_id: Optional[str],
    user_id: Optional[str],
    doc_id: Optional[str],
) -> Dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc),
        "request_id": request_id,
        "user_id": user_id,
        "doc_id": doc_id,
        "stage": result.stage.value,
        "action": result.action.value,
        "allowed": result.allowed,
        "latency_ms": round(result.latency_ms, 2),
        "violations": [v.to_dict() for v in result.violations],
    }


async def record(
    result: GuardResult,
    *,
    db=None,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> None:
    """Registra a decisão de uma rail. No-op se não houve violação."""
    if not result.triggered:
        return

    event = _build_event(result, request_id=request_id, user_id=user_id, doc_id=doc_id)

    rails = ",".join(sorted({v.rail for v in result.violations}))
    logger.warning(
        "[guardrails] stage=%s action=%s allowed=%s rails=[%s] user=%s req=%s",
        event["stage"], event["action"], event["allowed"], rails, user_id, request_id,
    )

    if db is not None and config.AUDIT_TO_MONGO:
        try:
            await db[config.AUDIT_COLLECTION].insert_one(dict(event))
        except Exception:  # persistência é best-effort; trilha em log já garantida
            logger.exception("[guardrails] falha ao persistir auditoria no Mongo")
