"""
Stage 4: turn the verdict into a sentence a compliance officer would sign.

Deterministic on purpose. The justification is not decoration — it is the audit trail
for the decision, so it must say exactly what the rules used, with the real values, and
must read the same way every run. A second LLM call would write prettier Spanish and
cost us reproducibility, which is the more valuable of the two.

The wording follows how an analyst writes a file note: the conclusion first, then the
evidence that supports it, then the evidence that argues against it, and finally the
caveats (missing data, decoys that were deliberately not used).
"""
from __future__ import annotations

from .classifier import (
    CONFIRMS,
    CONTRADICTS,
    LIKELY_TYPO,
    NO_DATA,
    Verdict,
)
from .schema import Observation


def _join(parts: list[str]) -> str:
    """'a', 'b', 'c' -> 'a, b y c' — Spanish list punctuation."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} y {parts[-1]}"


def justify(obs: Observation, verdict: Verdict) -> str:
    name_signal = verdict.signals[0]
    secondary = verdict.signals[1:]

    confirming = [s.detail for s in secondary if s.state == CONFIRMS]
    contradicting = [s.detail for s in secondary if s.state == CONTRADICTS]
    typos = [s.detail for s in secondary if s.state == LIKELY_TYPO]
    missing = [s.name for s in secondary if s.state == NO_DATA]

    sentences: list[str] = []

    # 1. Conclusion, up front.
    sentences.append(f"{verdict.classification.capitalize()} (prioridad {verdict.priority}).")

    # 2. The name: always the starting point, since it is what raised the alert.
    sentences.append(f"Nombre: {name_signal.detail}.")

    # 3. What supports the match, and what argues against it.
    # A colon keeps the sentence grammatical whether one item follows or several.
    if confirming:
        sentences.append(f"Coinciden: {_join(confirming)}.")
    if contradicting:
        connector = "Sin embargo, no coinciden" if confirming else "No coinciden"
        sentences.append(f"{connector}: {_join(contradicting)}.")

    # 4. Caveats worth a human's attention.
    if typos:
        sentences.append(f"Atención: {_join(typos)}.")
    if missing:
        sentences.append(f"Sin datos para comparar: {_join(missing)}.")
    if verdict.insufficient_data:
        sentences.append(
            "No hay identificadores secundarios para confirmar ni descartar: requiere revisión humana."
        )

    # 5. The decoys. Saying out loud that we saw them and chose not to use them is part of
    #    the audit trail — a reviewer must not think the agent simply missed them.
    if obs.engine_score is not None:
        sentences.append(
            f"El score del motor ({obs.engine_score}%) no se usa como criterio: "
            "mide parecido de nombre, no identidad."
        )
    if obs.internal_risk:
        sentences.append(
            f"El riesgo interno de la cuenta ({obs.internal_risk}) tampoco: "
            "califica a la cuenta, no a la coincidencia."
        )

    # 6. The rule, so any row can be traced back to the exact branch that produced it.
    sentences.append(f"[{verdict.rule}]")

    return " ".join(sentences)
