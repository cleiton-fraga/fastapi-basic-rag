"""
Bancos de expressões regulares para as checagens **baratas e síncronas** das
rails — a primeira linha de defesa, antes de qualquer chamada cara a LLM.

A literatura é clara: nenhuma técnica isolada basta. Estes regex/heurísticas
empilham com o classificador (Llama Guard) em `llama_guard.py`. São propositalmente
conservadores — alta precisão, foco em padrões inequívocos — para minimizar
falso-positivo, deixando os casos ambíguos para o classificador.

Todos os padrões são compilados com IGNORECASE | UNICODE para cobrir pt-BR e en.
"""

import re
from typing import List, Pattern

_FLAGS = re.IGNORECASE | re.UNICODE


def _compile(patterns: List[str]) -> List[Pattern[str]]:
    return [re.compile(p, _FLAGS) for p in patterns]


# --- Prompt injection: tentativas de sobrescrever as instruções do sistema ---
PROMPT_INJECTION: List[Pattern[str]] = _compile([
    r"\bignore?\b.{0,30}\b(all|todas?|previous|prior|anterior(es)?|acima|above)\b.{0,30}\b(instru(c|ç)(o|õ)es|instructions|prompt|regras?|rules?)\b",
    r"\bdisregard\b.{0,30}\b(previous|prior|above|all)\b.{0,30}\b(instructions|prompt|rules?)\b",
    r"\b(desconsider(e|ar)|esque(c|ç)a)\b.{0,30}\b(instru(c|ç)(o|õ)es|regras?|prompt)\b",
    r"\b(sobrescrev(a|er)|override)\b.{0,30}\b(instru(c|ç)(o|õ)es|prompt|sistema|system)\b",
    r"\b(revele|mostre|imprima|repita|reveal|show|print|repeat)\b.{0,30}\b(system\s*prompt|prompt\s*do\s*sistema|instru(c|ç)(o|õ)es\s*do\s*sistema|suas\s*instru(c|ç)(o|õ)es|your\s*(system\s*)?(prompt|instructions))\b",
    r"\b(new|nova[s]?|updated?)\b.{0,20}\b(instructions?|instru(c|ç)(o|õ)es|system\s*prompt)\b\s*[:：]",
    # marcadores de injeção de papel / template chat
    r"<\|?\s*(im_start|im_end|system|assistant)\s*\|?>",
    r"(?m)^\s*#{1,3}\s*(system|sistema)\b",
    r"\[\s*(system|sistema)\s*\]",
])

# --- Jailbreak: personas e modos que removem salvaguardas ---
JAILBREAK: List[Pattern[str]] = _compile([
    r"\bjailbreak\b",
    r"\bDAN\b.{0,20}\b(mode|do anything now)\b",
    r"\bdo anything now\b",
    r"\b(developer|debug)\s*mode\b",
    r"\bmodo\s*(desenvolvedor|de\s*desenvolvimento|sem\s*restri(c|ç)(o|õ)es)\b",
    r"\b(act|behave|pretend|finja|aja|comporte-se)\b.{0,20}\bas\b.{0,30}\b(no|sem)\b.{0,20}\b(restri(c|ç)(o|õ)es|filtros?|filters?|rules?|limita(c|ç)(o|õ)es)\b",
    r"\b(sem|without|no)\s*(restri(c|ç)(o|õ)es|filtros?|filters?|censura|censorship|limita(c|ç)(o|õ)es|moral|ethics?|(é|e)tica)\b",
    r"\byou are now\b.{0,40}\b(unfiltered|unrestricted|amoral|jailbroken)\b",
    r"\b(bypass|contorn(e|ar)|burl(e|ar))\b.{0,30}\b(safety|seguran(c|ç)a|filtros?|guard(rails)?|restri(c|ç)(o|õ)es)\b",
])

# --- Tópicos proibidos (default mínimo, seguro e genérico; extensível por env) ---
# Foco em segurança crítica; políticas específicas da organização devem ser
# adicionadas via GUARDRAILS_BANNED_TOPICS.
BANNED_TOPICS: List[Pattern[str]] = _compile([
    r"\b(como\s+(fabricar|construir|fazer)|how\s+to\s+(make|build|manufacture))\b.{0,40}\b(bomba|explosiv[oa]s?|bomb|explosive|arma\s+de\s+fogo|firearm)\b",
    r"\b(sintetizar|synthesize|fabricar|cozinhar|cook)\b.{0,30}\b(metanfetamina|methamphetamine|coca(í|i)na|cocaine|drogas?\s+il(í|i)citas?)\b",
    r"\b(como\s+(me\s+)?(matar|suicidar)|how\s+to\s+(kill\s+myself|commit\s+suicide)|m(é|e)todos?\s+de\s+suic(í|i)dio)\b",
])

# --- Toxicidade (lista curta e representativa; extensível por env) ---
# A detecção robusta de toxicidade é tarefa de classificador (Llama Guard); este
# regex pega apenas casos explícitos como rede de segurança barata.
_TOXIC_TERMS = [
    "idiota", "imbecil", "otário", "otario", "vai se foder", "vsf",
    "merda", "porra", "fdp", "filho da puta", "arrombado", "babaca",
    "fuck", "shit", "asshole", "bitch", "bastard", "moron", "retard",
]
TOXICITY: List[Pattern[str]] = _compile([
    r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b" for term in _TOXIC_TERMS
])


def any_match(patterns: List[Pattern[str]], text: str) -> List[str]:
    """Retorna os trechos casados (rótulos curtos) por `patterns` em `text`.

    Os trechos são truncados para 60 chars para servirem de evidência na
    auditoria sem reproduzir conteúdo longo.
    """
    hits: List[str] = []
    for pat in patterns:
        m = pat.search(text)
        if m:
            snippet = m.group(0)
            hits.append(snippet[:60])
    return hits
