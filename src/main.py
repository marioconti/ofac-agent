"""
The command-line entry point: orchestrates the pipeline and reports as it goes.

    python -m src.main input/observaciones-ejemplo.pdf

Design notes:
- One observation at a time, sequentially. The live log is the deliverable's progress
  indicator, so ordered output matters more here than raw throughput; at ~2s per case
  a full 80-case run takes a few minutes.
- A failure on one observation must never end the run. The regulator's report is
  supplied by a third party and we cannot assume it is well formed. Anything that
  breaks extraction is logged, written to the CSV as an explicit error row, and the
  run continues — the analyst still gets the other 79 cases.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from .classifier import classify
from .cost import RunCost, format_duration
from .extractor import DEFAULT_MODEL, extract_one, make_model
from .justifier import justify
from .loader import load_observations

# Column order follows how an analyst reads the file: the decision first, the evidence
# that supports it next, and the raw source data last.
CSV_COLUMNS = [
    "n_observacion",
    "clasificacion",
    "prioridad",
    "justificacion",
    "datos_insuficientes",
    "senales_detectadas",
    "regla_aplicada",
    "coincidencia_nombre",
    "cliente_nombre",
    "cliente_documento",
    "cliente_fecha_nac",
    "cliente_nacionalidad",
    "cliente_lugar_nac",
    "ofac_nombre",
    "ofac_alias",
    "ofac_programa",
    "ofac_fecha_nac",
    "ofac_nacionalidad",
    "ofac_documento",
    "ofac_lugar_nac",
    "score_motor_no_usado",
    "riesgo_interno_no_usado",
]


def _document(doc_type: str | None, number: str | None) -> str:
    """'DNI' + '31.556.201' -> 'DNI 31.556.201'; empty when nothing was informed."""
    return " ".join(part for part in (doc_type, number) if part)


def _row(number: int, obs, verdict) -> dict:
    return {
        "n_observacion": number,
        "clasificacion": verdict.classification,
        "prioridad": verdict.priority,
        "justificacion": justify(obs, verdict),
        "datos_insuficientes": "sí" if verdict.insufficient_data else "no",
        "senales_detectadas": " | ".join(f"{s.name}: {s.state}" for s in verdict.signals),
        "regla_aplicada": verdict.rule,
        "coincidencia_nombre": verdict.name_strength,
        "cliente_nombre": obs.client_name,
        "cliente_documento": _document(obs.client_doc_type, obs.client_doc_number),
        "cliente_fecha_nac": obs.client_dob or "",
        "cliente_nacionalidad": obs.client_nationality or "",
        "cliente_lugar_nac": obs.client_pob or "",
        "ofac_nombre": obs.ofac_name,
        "ofac_alias": "; ".join(obs.ofac_aliases),
        "ofac_programa": obs.ofac_program or "",
        "ofac_fecha_nac": obs.ofac_dob or "",
        "ofac_nacionalidad": obs.ofac_nationality or "",
        "ofac_documento": _document(obs.ofac_doc_type, obs.ofac_doc_number),
        "ofac_lugar_nac": obs.ofac_pob or "",
        "score_motor_no_usado": obs.engine_score if obs.engine_score is not None else "",
        "riesgo_interno_no_usado": obs.internal_risk or "",
    }


def _error_row(number: int, message: str) -> dict:
    """A case we could not read. Recorded explicitly so nothing disappears silently."""
    row = {column: "" for column in CSV_COLUMNS}
    row["n_observacion"] = number
    row["clasificacion"] = "ERROR_DE_EXTRACCION"
    row["prioridad"] = "media"
    row["justificacion"] = (
        "No se pudieron extraer los datos de esta observación, por lo que el agente no la "
        f"clasificó. Requiere revisión manual. Detalle técnico: {message}"
    )
    row["datos_insuficientes"] = "sí"
    return row


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig writes the BOM Excel needs to show accents correctly on Windows.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _summary(rows: list[dict], run: RunCost, model_id: str) -> None:
    """The run summary — what a compliance lead wants to see first."""
    total = len(rows)
    real = [r for r in rows if r["clasificacion"] == "posible coincidencia real"]
    false_positive = [r for r in rows if r["clasificacion"] == "falso positivo"]
    errors = [r for r in rows if r["clasificacion"] == "ERROR_DE_EXTRACCION"]
    by_priority = {p: sum(1 for r in rows if r["prioridad"] == p) for p in ("alta", "media", "baja")}
    incomplete = sum(1 for r in rows if r["datos_insuficientes"] == "sí")

    print()
    print("=" * 62)
    print(f"  RESUMEN DE LA CORRIDA: {total} observaciones procesadas")
    print("=" * 62)
    print(f"  Falsos positivos ........ {len(false_positive):>3}")
    print(f"  Posibles reales ......... {len(real):>3}")
    if errors:
        print(f"  Errores de extracción ... {len(errors):>3}  (quedan para revisión manual)")
    print(f"  Prioridad alta .......... {by_priority['alta']:>3}   <- revisar primero")
    print(f"  Prioridad media ......... {by_priority['media']:>3}")
    print(f"  Prioridad baja .......... {by_priority['baja']:>3}")
    print(f"  Con datos insuficientes . {incomplete:>3}")
    print("-" * 62)
    print(f"  Modelo .................. {model_id}")
    print(f"  Llamadas al modelo ...... {run.calls}")
    print(f"  Tokens .................. {run.input_tokens:,} entrada / {run.output_tokens:,} salida")
    if run.is_priced:
        print(f"  Costo total ............. USD {run.total_cost:.4f}")
    else:
        print(f"  Costo total ............. sin tarifa cargada para «{model_id}»")
    print(f"  Duración ................ {format_duration(run.elapsed)}")
    print("=" * 62)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clasifica y prioriza las observaciones OFAC de un informe del regulador.",
    )
    parser.add_argument("documento", help="Ruta al informe (PDF) con las observaciones.")
    parser.add_argument("-o", "--output", default="output/resultado.csv", help="Ruta del CSV de salida.")
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL, help="Modelo de Anthropic a usar.")
    parser.add_argument(
        "-l", "--limit", type=int, default=None,
        help="Procesar solo las primeras N observaciones (útil para probar sin gastar la corrida completa).",
    )
    args = parser.parse_args(argv)

    # The report, the CSV and the console output are all in Spanish; force UTF-8 so the
    # Windows console does not mangle the accents.
    sys.stdout.reconfigure(encoding="utf-8")

    source = Path(args.documento)
    if not source.exists():
        print(f"ERROR: no se encontró el documento «{source}».")
        return 1

    try:
        observations = load_observations(source)
    except Exception as error:  # unreadable or unsupported document
        print(f"ERROR: no se pudo leer el documento: {error}")
        return 1

    if not observations:
        print(
            "ERROR: no se encontró ninguna observación en el documento. "
            "Se esperaba un informe con casos numerados (Obs. 1, Observación 2, Ítem 3, Caso 4...)."
        )
        return 1

    if args.limit:
        observations = observations[: args.limit]

    print(f"Documento: {source}")
    print(f"Observaciones detectadas: {len(observations)}")
    print(f"Modelo: {args.model}\n")

    model = make_model(args.model)
    run = RunCost(model_id=args.model)
    run.start()
    rows: list[dict] = []
    total = len(observations)

    for index, (number, raw_text) in enumerate(observations, start=1):
        case_start = time.perf_counter()
        try:
            observation, metrics = extract_one(raw_text, model)
            usage = metrics.accumulated_usage
            call_cost = run.add(usage["inputTokens"], usage["outputTokens"])
            verdict = classify(observation)
            rows.append(_row(number, observation, verdict))
            elapsed = time.perf_counter() - case_start
            print(
                f"[{index:>2}/{total}] Obs. {number:<3} {observation.client_name[:34]:<34} "
                f"→ {verdict.classification.upper():<26} ({verdict.priority:<5}) "
                f"· {verdict.rule.split(' ·')[0]:<4} · {elapsed:4.1f}s · USD {call_cost:.4f}"
            )
        except Exception as error:
            # One bad observation must not take the run down with it.
            elapsed = time.perf_counter() - case_start
            rows.append(_error_row(number, f"{type(error).__name__}: {error}"))
            print(
                f"[{index:>2}/{total}] Obs. {number:<3} → ERROR DE EXTRACCIÓN "
                f"({type(error).__name__}) · {elapsed:4.1f}s · se continúa"
            )

    output = Path(args.output)
    _write_csv(output, rows)
    _summary(rows, run, args.model)
    print(f"\nCSV generado en: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
