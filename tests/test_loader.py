"""
Robustness tests for stage 1 (segmentation) — no API, no cost.

    python -m tests.test_loader

The agent has to run on the evaluator's machine against a DIFFERENT report of the
same kind. These tests feed the segmenter the messy shapes a real report throws at
it — rotating labels, a non-80 count, gaps in the numbering, blank input — and assert
it degrades gracefully instead of crashing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.loader import split_observations  # noqa: E402

CASES = [
    (
        "Las cinco etiquetas que rotan en el informe real",
        "Obs. 1 — cliente A. Observación 2: cliente B. Ítem 3. cliente C. "
        "Caso 4 — cliente D. Observación N.º 5. cliente E.",
        [1, 2, 3, 4, 5],
    ),
    (
        "Un informe con menos observaciones que el ejemplo (no asumir 80)",
        "Obs. 1 — cliente A. Observación 2: cliente B.",
        [1, 2],
    ),
    (
        "Numeración con huecos (falta la 2) — se respeta lo que hay",
        "Obs. 1 — cliente A. Ítem 3. cliente C.",
        [1, 3],
    ),
    (
        "Números de dos y tres dígitos",
        "Caso 79 — cliente A. Observación N.º 100. cliente B.",
        [79, 100],
    ),
    (
        "Documento sin ninguna observación reconocible → lista vacía, sin romper",
        "Este es un informe sin el formato esperado, solo prosa suelta.",
        [],
    ),
    (
        "Documento vacío → lista vacía, sin romper",
        "",
        [],
    ),
]


def run() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    failures = 0
    for label, text, expected_numbers in CASES:
        result = split_observations(text)
        numbers = [n for n, _ in result]
        ok = numbers == expected_numbers
        # Every returned observation must carry non-empty text.
        ok = ok and all(raw.strip() for _, raw in result)
        if not ok:
            failures += 1
        print(f"{'PASA' if ok else 'FALLA'}  {label}")
        if not ok:
            print(f"      esperado {expected_numbers}, obtenido {numbers}")

    print("-" * 62)
    print("Todos los casos pasaron." if not failures else f"{failures} caso(s) fallaron.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
