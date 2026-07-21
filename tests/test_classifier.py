"""
Tests for the decision logic. No API key, no network, no cost — run them freely:

    python -m tests.test_classifier

The first nine cases are real observations from the sample report, transcribed by
hand. They are the reference set used to measure the classifier across iterations:
if a change to the rules breaks one of these, we see it immediately instead of
discovering it in the CSV. The rest are synthetic edge cases.

Deliberately included: the two decoy cases. Obs. 45 scores 98% and is a false
positive; obs. 60 scores 81% and is a real match. A classifier that trusted the
engine score would get both exactly backwards.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.classifier import FALSE_POSITIVE, HIGH, LOW, MEDIUM, POSSIBLE_MATCH, classify  # noqa: E402
from src.justifier import justify  # noqa: E402
from src.schema import Observation  # noqa: E402

GOLD_SET = [
    # --- Real observations from the sample report -------------------------------------
    (
        "Obs. 5 · trampa del score: 97% pero el cliente es otra persona",
        Observation(
            client_name="Pedro David Gallón Henao",
            client_doc_type="DNI", client_doc_number="31.556.201",
            client_dob="1988-11-19", client_nationality="Argentina",
            ofac_name="GALLON HENAO, Pedro David", ofac_program="SDNTK",
            ofac_dob="1970-08-12", ofac_nationality="Colombia", ofac_pob="Medellín, Colombia",
            ofac_doc_type="Cédula de Ciudadanía (Colombia)", ofac_doc_number="98551360",
            engine_score=97,
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        "Obs. 11 · mismo número de cédula → coincidencia real",
        Observation(
            client_name="Jonathan Álvarez Escobar",
            client_doc_type="Cédula de Ciudadanía (Colombia)", client_doc_number="1017136706",
            client_dob="1986-09-10", client_nationality="Colombia", client_pob="Tuluá, Valle, Colombia",
            ofac_name="ALVAREZ ESCOBAR, Jonathan", ofac_aliases=["Primo"], ofac_program="SDNTK",
            ofac_dob="1986-09-10", ofac_nationality="Colombia", ofac_pob="Tuluá, Valle, Colombia",
            ofac_doc_type="Cédula de Ciudadanía (Colombia)", ofac_doc_number="1017136706",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        "Obs. 20 · 97% y nombre transliterado, pero país y edad no dan",
        Observation(
            client_name="Abdul Rashid Baloch",
            client_doc_type="Pasaporte", client_doc_number="BX1122334",
            client_dob="1990-01-01", client_nationality="Pakistán",
            ofac_name="RASHID BALUCH, Abdul",
            ofac_aliases=["Abdul Rashid", "Hafiz Abdul Rashid", "Mullah Abdul Rashid"],
            ofac_program="SDGT", ofac_dob="1971",
            ofac_nationality="Afganistán", ofac_pob="Dishu District, Helmand, Afganistán",
            engine_score=97,
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        "Obs. 23 · todo coincide (y el riesgo interno «bajo» es un señuelo)",
        Observation(
            client_name="Jesús Rafael Villamizar Gómez",
            client_doc_type="Cédula de Identidad (Venezuela)", client_doc_number="V-10794553",
            client_dob="1971-12-21", client_nationality="Venezuela",
            ofac_name="VILLAMIZAR GOMEZ, Jesus Rafael", ofac_program="VENEZUELA",
            ofac_dob="1971-12-21", ofac_nationality="Venezuela", ofac_pob="Caracas, Venezuela",
            ofac_doc_type="Cédula de Identidad (Venezuela)", ofac_doc_number="V-10794553",
            internal_risk="bajo",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        "Obs. 34 · documento con dígitos transpuestos, todo lo demás coincide",
        Observation(
            client_name="Jose Oscar Zuleta Trochez",
            client_doc_type="Cédula de Ciudadanía (Colombia)", client_doc_number="01633018",
            client_dob="1976-08-31", client_nationality="Colombia", client_pob="Corinto, Cauca, Colombia",
            ofac_name="ZULETA TROCHEZ, Jose Oscar", ofac_program="SDNTK",
            ofac_dob="1976-08-31", ofac_nationality="Colombia", ofac_pob="Corinto, Cauca, Colombia",
            ofac_doc_type="Cédula de Ciudadanía (Colombia)", ofac_doc_number="10633018",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        "Obs. 45 · score 98% — el falso positivo mejor disfrazado del informe",
        Observation(
            client_name="Oscar Zuleta",
            client_doc_type="DNI", client_doc_number="22.667.881",
            client_dob="1972-09-27", client_nationality="Argentina",
            ofac_name="ZULETA TROCHEZ, Jose Oscar", ofac_program="SDNTK",
            ofac_dob="1976-08-31", ofac_nationality="Colombia", ofac_pob="Corinto, Cauca, Colombia",
            ofac_doc_type="Cédula de Ciudadanía (Colombia)", ofac_doc_number="10633018",
            engine_score=98,
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        "Obs. 60 · score 81% pero CURP idéntico — coincidencia real",
        Observation(
            client_name="Fernando Zagal Antón",
            client_doc_type="CURP (México)", client_doc_number="ZAAF821014HJCGNR07",
            client_dob="1982-10-14", client_nationality="México", client_pob="Puerto Vallarta, Jalisco, México",
            ofac_name="ZAGAL ANTON, Fernando", ofac_program="SDNTK",
            ofac_dob="1982-10-14", ofac_nationality="México", ofac_pob="Puerto Vallarta, Jalisco, México",
            ofac_doc_type="CURP (México)", ofac_doc_number="ZAAF821014HJCGNR07",
            engine_score=81,
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        "Obs. 9 · nombre parcial y tres identificadores que contradicen",
        Observation(
            client_name="Fernando Antón Ruiz",
            client_doc_type="DNI", client_doc_number="31.220.117",
            client_dob="1986-03-19", client_nationality="Argentina",
            ofac_name="ZAGAL ANTON, Fernando", ofac_program="SDNTK",
            ofac_dob="1982-10-14", ofac_nationality="México", ofac_pob="Puerto Vallarta, Jalisco, México",
            ofac_doc_type="CURP (México)", ofac_doc_number="ZAAF821014HJCGNR07",
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        "Obs. 72 · nombre corto contenido en el del sancionado, nada más coincide",
        Observation(
            client_name="Roberto Carretero",
            client_doc_type="DNI", client_doc_number="20.118.774",
            client_dob="1968-11-03", client_nationality="Argentina",
            ofac_name="CARRETERO NAPOLITANO, Roberto", ofac_program="VENEZUELA",
            ofac_dob="1976-08-20", ofac_nationality="Panamá", ofac_pob="Panamá",
            ofac_doc_type="Cédula (Panamá)", ofac_doc_number="3701218",
            engine_score=80,
        ),
        FALSE_POSITIVE, LOW,
    ),

    # --- Synthetic edge cases ---------------------------------------------------------
    (
        "Borde · el registro OFAC es un buque, el cliente es una persona",
        Observation(
            client_name="Marina Delgado", client_nationality="Argentina",
            ofac_name="MARINA DELGADO", ofac_entity_type="vessel", ofac_program="VENEZUELA",
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        "Borde · nombre exacto y ningún identificador para verificar",
        Observation(
            client_name="Carlos Alberto Jarquín Jarquín",
            ofac_name="JARQUIN JARQUIN, Carlos Alberto", ofac_program="VENEZUELA",
        ),
        POSSIBLE_MATCH, MEDIUM,
    ),
    (
        "Borde · nombre exacto, sin identificadores, programa severo → sube a alta",
        Observation(
            client_name="Carlos Alberto Jarquín Jarquín",
            ofac_name="JARQUIN JARQUIN, Carlos Alberto", ofac_program="SDGT",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        "Borde · el match se apoya solo en un alias débil",
        Observation(
            client_name="Roberto Gómez",
            ofac_name="OTRO SUJETO, Ramiro", ofac_aliases=["Roberto"], ofac_alias_weak=True,
            ofac_program="SDNTK",
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        "Borde · solo el apellido coincide y no hay más datos",
        Observation(
            client_name="Lucía Henao",
            ofac_name="GALLON HENAO, Pedro David", ofac_program="SDNTK",
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        "Borde · fecha de nacimiento solo con año en la lista, y coincide",
        Observation(
            client_name="Ana María Suárez Peña",
            client_dob="1980-04-22", client_nationality="Colombia",
            ofac_name="SUAREZ PENA, Ana Maria", ofac_dob="1980", ofac_nationality="Colombia",
            ofac_program="SDNTK",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        # One strong identifier (date of birth) confirms, no document to clinch it, and
        # the program is not severe → a genuine lead, but MEDIUM rather than HIGH.
        "Borde · coincide la fecha de nacimiento, sin documento, programa no severo → media",
        Observation(
            client_name="Marta Elena Ríos Prieto",
            client_dob="1979-02-14", client_nationality="Venezuela",
            ofac_name="RIOS PRIETO, Marta Elena", ofac_dob="1979-02-14", ofac_nationality="Venezuela",
            ofac_program="VENEZUELA",
        ),
        POSSIBLE_MATCH, MEDIUM,
    ),
    (
        # Same full name and same nationality, but the date of birth is 15 years off.
        # Nationality is a weak, supporting signal (half of Colombia shares it); the
        # date of birth is a strong one. A strong contradiction with only weak support
        # is the textbook homonym → false positive, not a case worth an analyst's time.
        "Borde · nombre y nacionalidad coinciden pero la fecha discrepa 15 años → homónimo",
        Observation(
            client_name="Diego Ramírez Soto",
            client_dob="1990-05-05", client_nationality="Colombia",
            ofac_name="RAMIREZ SOTO, Diego", ofac_dob="1975-01-01", ofac_nationality="Colombia",
            ofac_program="SDNTK",
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        # Everything lines up: name, document, date, nationality, birthplace. The clearest
        # possible real match — no ambiguity, top priority.
        "Borde · coincidencia total (nombre, documento, fecha, nacionalidad, lugar) → real alta",
        Observation(
            client_name="Andrés Felipe Salazar Ruiz",
            client_doc_type="Cédula de Ciudadanía (Colombia)", client_doc_number="79123456",
            client_dob="1983-06-15", client_nationality="Colombia", client_pob="Cali, Valle, Colombia",
            ofac_name="SALAZAR RUIZ, Andres Felipe", ofac_program="SDNTK",
            ofac_dob="1983-06-15", ofac_nationality="Colombia", ofac_pob="Cali, Valle, Colombia",
            ofac_doc_type="Cédula de Ciudadanía (Colombia)", ofac_doc_number="79123456",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        # The OFAC entry is a company, the client is a person → they cannot be the same party.
        "Borde · el registro OFAC es una empresa, el cliente es una persona → falso positivo",
        Observation(
            client_name="Comercial Andina",
            client_nationality="Argentina",
            ofac_name="COMERCIAL ANDINA S.A.", ofac_entity_type="company", ofac_program="SDNTK",
        ),
        FALSE_POSITIVE, LOW,
    ),
    (
        # Same document number, but a non-severe program. The document is decisive on its
        # own — program severity does not change that the parties are the same person.
        "Borde · documento idéntico aunque el programa no sea severo → real alta",
        Observation(
            client_name="Lorena Beatriz Ponce",
            client_doc_type="Cédula de Identidad (Venezuela)", client_doc_number="V-14556677",
            client_dob="1984-09-09", client_nationality="Venezuela",
            ofac_name="PONCE, Lorena Beatriz", ofac_program="VENEZUELA",
            ofac_dob="1984-09-09", ofac_nationality="Venezuela",
            ofac_doc_type="Cédula de Identidad (Venezuela)", ofac_doc_number="V-14556677",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        # A transliterated surname (Baloch vs Baluch) with the date of birth and nationality
        # both confirming → the name still matches, and a strong identifier backs it.
        "Borde · apellido transliterado (Baloch/Baluch) con fecha y nacionalidad que confirman",
        Observation(
            client_name="Karim Baloch",
            client_dob="1979-07-07", client_nationality="Pakistán",
            ofac_name="BALUCH, Karim", ofac_program="SDGT",
            ofac_dob="1979-07-07", ofac_nationality="Pakistán",
        ),
        POSSIBLE_MATCH, HIGH,
    ),
    (
        # Only the client's name is on file, and it barely overlaps (one shared token) with a
        # common surname. Nothing to escalate.
        "Borde · un solo apellido común coincide, sin ningún otro dato → falso positivo",
        Observation(
            client_name="Sofía Flores",
            ofac_name="CAMPO FLORES, Efrain Antonio", ofac_program="SDNTK",
        ),
        FALSE_POSITIVE, LOW,
    ),
]


def run() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    failures = 0

    print(f"Casos de referencia: {len(GOLD_SET)}\n")
    for label, observation, expected_class, expected_priority in GOLD_SET:
        verdict = classify(observation)
        ok = verdict.classification == expected_class and verdict.priority == expected_priority
        if not ok:
            failures += 1
        print(f"{'PASA' if ok else 'FALLA'}  {label}")
        print(f"      → {verdict.classification} ({verdict.priority})  [{verdict.rule}]")
        if not ok:
            print(f"      ✗ se esperaba: {expected_class} ({expected_priority})")
        print()

    # The justification must always be readable prose, never an empty cell.
    for label, observation, _, _ in GOLD_SET:
        text = justify(observation, classify(observation))
        if len(text) < 40:
            print(f"FALLA  justificación demasiado corta en: {label}")
            failures += 1

    print("-" * 62)
    if failures:
        print(f"{failures} caso(s) fallaron.")
    else:
        print(f"Todos los casos pasaron ({len(GOLD_SET)}/{len(GOLD_SET)}).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
