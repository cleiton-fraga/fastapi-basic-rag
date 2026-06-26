"""
Camada de guardrails: segurança como middleware sobre o núcleo RAG.

Intercepta a requisição em dois momentos:
- `apply_input_rail`  — antes do LLM/Ollama (prompt injection, jailbreak, PII,
  tópicos proibidos, Llama Guard); reprova com curto-circuito.
- `apply_output_rail` — depois do LLM, antes do usuário (fidelidade ao contexto,
  toxicidade, vazamento de PII/segredos, tom de voz, Llama Guard).

`GuardrailsMiddleware` provê o envelope transversal (request_id + latência).
Checagens baratas (regex) rodam síncronas em threadpool; as caras (Llama Guard)
rodam assíncronas/por amostragem. Todo bloqueio gera trilha de auditoria.
"""

from app.guardrails.middleware import GuardrailsMiddleware
from app.guardrails.rails import apply_input_rail, apply_output_rail
from app.guardrails.types import Action, GuardResult, RailStage, Severity, Violation

__all__ = [
    "GuardrailsMiddleware",
    "apply_input_rail",
    "apply_output_rail",
    "GuardResult",
    "Action",
    "RailStage",
    "Severity",
    "Violation",
]
