"""
Tipos compartilhados pela camada de guardrails.

Estruturas puras (dataclasses/enums) sem acoplamento ao FastAPI, para que as
rails sejam testáveis isoladamente.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RailStage(str, Enum):
    """Momento da interceptação no ciclo de vida da requisição."""

    INPUT = "input"   # antes do LLM/Ollama
    OUTPUT = "output"  # depois do LLM, antes do usuário


class Action(str, Enum):
    """Decisão tomada por uma rail sobre o texto interceptado."""

    ALLOW = "allow"          # segue sem alteração
    ANONYMIZE = "anonymize"  # PII removida/mascarada, segue
    REWRITE = "rewrite"      # conteúdo redigido/substituído parcialmente
    BLOCK = "block"          # reprovado: curto-circuito (input) ou substituição (output)


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Violation:
    """Uma infração detectada por um detector específico."""

    rail: str          # "prompt_injection", "jailbreak", "pii", "banned_topic",
                       # "toxicity", "pii_leak", "faithfulness", "tone", "llama_guard"
    detector: str      # "regex" | "heuristic" | "llama_guard"
    severity: Severity
    detail: str
    matches: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rail": self.rail,
            "detector": self.detector,
            "severity": self.severity.value,
            "detail": self.detail,
            # nunca guardamos PII crua na trilha: apenas a contagem e os rótulos.
            "matches": self.matches,
        }


@dataclass
class GuardResult:
    """Resultado de uma rail (entrada ou saída).

    - `text`: texto final a ser usado a jusante.
      * input  → a pergunta (possivelmente anonimizada) que segue para o LLM.
      * output → a resposta final (possivelmente redigida/substituída) ao usuário.
    - `allowed`: no input, `False` aciona o curto-circuito (não chama o LLM).
      No output é tipicamente `True` (sempre devolvemos algo seguro).
    - `safe_response`: resposta padrão usada no curto-circuito de entrada.
    """

    stage: RailStage
    allowed: bool
    action: Action
    text: str
    violations: List[Violation] = field(default_factory=list)
    safe_response: Optional[str] = None
    latency_ms: float = 0.0

    @property
    def triggered(self) -> bool:
        """Houve qualquer infração (mesmo que não tenha bloqueado)?"""
        return bool(self.violations)
