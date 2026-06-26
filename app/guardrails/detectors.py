"""
Detectores **baratos e síncronos** (CPU-bound) das rails.

Princípio de engenharia adotado da literatura: rodar as checagens baratas (regex/
heurística) de forma síncrona e as caras (LLM) de forma assíncrona/por amostragem,
mantendo a latência dentro do SLA. Estas funções são puras e determinísticas;
nas rails são despachadas para um threadpool (`asyncio.to_thread`) para não
bloquear o event loop.
"""

import re
from typing import List

from app.guardrails import config, patterns
from app.guardrails.types import Severity, Violation

# Stopwords curtas pt/en para o heurístico de fidelidade não inflar a sobreposição
# com palavras vazias.
_STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "um", "uma", "que", "com", "por", "para", "os", "as", "se", "ao", "à", "the",
    "and", "for", "with", "this", "that", "from", "are", "was", "were", "his",
    "her", "its", "they", "you", "not", "but", "all", "can", "has", "have",
}

_WORD_RE = re.compile(r"[\wÀ-ÿ]{4,}", re.UNICODE)

# Frases que sinalizam, legitimamente, ausência de resposta — não devem ser
# punidas pelo heurístico de fidelidade.
_ABSTENTION_RE = re.compile(
    r"\b(n[ãa]o\s+(sei|encontrei|h[áa]|possuo|tenho|consigo)|"
    r"informa[çc][ãa]o\s+insuficiente|n[ãa]o\s+est[áa]\s+no\s+contexto|"
    r"(i\s+)?(don'?t|do not)\s+know|insufficient\s+information|not\s+in\s+the\s+context)\b",
    re.IGNORECASE | re.UNICODE,
)


def _tokens(text: str) -> set:
    return {
        w.lower()
        for w in _WORD_RE.findall(text or "")
        if w.lower() not in _STOPWORDS
    }


# --- Input detectors --------------------------------------------------------

def detect_input(text: str) -> List[Violation]:
    """Roda os detectores baratos de entrada: injeção, jailbreak e tópicos proibidos."""
    violations: List[Violation] = []

    inj = patterns.any_match(patterns.PROMPT_INJECTION, text)
    if inj:
        violations.append(Violation(
            rail="prompt_injection", detector="regex", severity=Severity.HIGH,
            detail="Possível tentativa de sobrescrever as instruções do sistema.",
            matches=inj,
        ))

    jb = patterns.any_match(patterns.JAILBREAK, text)
    if jb:
        violations.append(Violation(
            rail="jailbreak", detector="regex", severity=Severity.HIGH,
            detail="Possível tentativa de jailbreak / remoção de salvaguardas.",
            matches=jb,
        ))

    banned = patterns.any_match(patterns.BANNED_TOPICS, text)
    extra = [t for t in config.EXTRA_BANNED_TOPICS if re.search(re.escape(t), text, re.IGNORECASE)]
    if banned or extra:
        violations.append(Violation(
            rail="banned_topic", detector="regex", severity=Severity.HIGH,
            detail="Conteúdo em tópico proibido / fora de escopo.",
            matches=(banned + extra)[:5],
        ))

    return violations


# --- Output detectors -------------------------------------------------------

def detect_toxicity(text: str) -> List[Violation]:
    hits = patterns.any_match(patterns.TOXICITY, text)
    if not hits:
        return []
    return [Violation(
        rail="toxicity", detector="regex", severity=Severity.MEDIUM,
        detail="Linguagem ofensiva detectada.", matches=hits,
    )]


def detect_tone(text: str) -> List[Violation]:
    """Tom de voz corporativo: sinaliza frases banidas configuradas pela organização.

    Por padrão a lista é vazia (no-op). Regras de fluxo/tom mais ricas ficam a
    cargo de NeMo Guardrails (Colang) como camada complementar.
    """
    if not config.TONE_BANNED_PHRASES:
        return []
    hits = [p for p in config.TONE_BANNED_PHRASES if re.search(re.escape(p), text, re.IGNORECASE)]
    if not hits:
        return []
    return [Violation(
        rail="tone", detector="regex", severity=Severity.LOW,
        detail="Resposta fora das diretrizes de tom de voz da organização.",
        matches=hits[:5],
    )]


def detect_faithfulness(answer: str, context: str) -> List[Violation]:
    """Heurístico anti-alucinação: mede o quanto a resposta se sustenta no contexto.

    Calcula a fração dos tokens de conteúdo da resposta que também aparecem no
    contexto recuperado. Abaixo de `FAITHFULNESS_MIN_OVERLAP`, a resposta é
    sinalizada como possivelmente não fundamentada.

    Respostas de abstenção ("não sei", "não está no contexto") são isentas — são
    o comportamento desejado quando falta evidência. É um sinal barato e
    aproximado; a verificação robusta cabe ao juiz LLM / Llama Guard (amostrado).
    """
    if not answer or not answer.strip():
        return []
    if _ABSTENTION_RE.search(answer):
        return []

    ans_tokens = _tokens(answer)
    if not ans_tokens:
        return []
    ctx_tokens = _tokens(context)
    if not ctx_tokens:
        # Sem contexto não há como fundamentar — trata como não fundamentado.
        overlap = 0.0
    else:
        overlap = len(ans_tokens & ctx_tokens) / len(ans_tokens)

    if overlap < config.FAITHFULNESS_MIN_OVERLAP:
        return [Violation(
            rail="faithfulness", detector="heuristic", severity=Severity.MEDIUM,
            detail=(
                f"Baixa sobreposição com o contexto recuperado "
                f"(overlap={overlap:.2f} < {config.FAITHFULNESS_MIN_OVERLAP:.2f}); "
                f"possível alucinação."
            ),
            matches=[f"overlap={overlap:.2f}"],
        )]
    return []
