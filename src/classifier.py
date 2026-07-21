"""
Stage 3 of the pipeline: the decision. NO LLM here, on purpose.

The extractor turned prose into a filled-in form; this module reads that form and
decides. It works in two steps, mirroring how a compliance analyst works:

    Step A  compare the client against the OFAC subject, identifier by identifier,
            producing a list of SIGNALS (each one confirms, contradicts, or has no data)
    Step B  apply an ordered, explicit decision tree over those signals

Why rules and not the LLM: the classification is what a compliance officer has to sign
in front of the regulator. Rules are auditable ("these identifiers contradict"),
reproducible (same input, same output, always) and can be defended line by line. An
LLM verdict is none of those things.

Two values are deliberately NOT used: `engine_score` and `internal_risk`. The screening
engine's score is a name-similarity number that knows nothing about the identifiers, and
the internal risk level describes the ACCOUNT, not the strength of the match. The sample
document proves the point: obs. 45 scores 98% and is a false positive, obs. 60 scores 81%
and is a real match. We record both values in the CSV and ignore them when deciding.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .schema import Observation

# --- Signal states -----------------------------------------------------------------
CONFIRMS = "confirma"
CONTRADICTS = "contradice"
NO_DATA = "sin dato"
LIKELY_TYPO = "posible error de tipeo"

# Not every identifier carries the same weight. A date of birth or a document number
# is highly discriminating: two people with the same full name almost never share
# either by chance, so a clear mismatch on one is strong evidence of a homonym.
# Nationality and birthplace only NARROW the field — half a country shares a
# nationality — so on their own they neither confirm nor rule out a match. The tree
# below counts strong and supporting signals separately for exactly this reason.
STRONG_SIGNALS = {"fecha de nacimiento", "documento"}
SUPPORTING_SIGNALS = {"nacionalidad", "lugar de nacimiento"}

# --- Name match strength -----------------------------------------------------------
NAME_EXACT = "exacto"          # both full names match, token for token
NAME_CONTAINED = "contenido"   # one name sits fully inside the other ("Oscar Zuleta" in "ZULETA TROCHEZ, Jose Oscar")
NAME_PARTIAL = "parcial"       # some tokens match, neither name contains the other
NAME_WEAK = "débil"            # at most one token in common (typically just the surname)

# --- Outputs -----------------------------------------------------------------------
FALSE_POSITIVE = "falso positivo"
POSSIBLE_MATCH = "posible coincidencia real"
LOW, MEDIUM, HIGH = "baja", "media", "alta"

# Sanction programs whose cost of a miss is highest: terrorism and narco-trafficking.
# Severity NEVER flips the classification — it only raises priority when there is
# genuine doubt. Once the identifiers have ruled the match out, a severe program does
# not justify sending noise back to the analyst's queue.
SEVERE_PROGRAMS = ("SDGT", "SDNTK", "SDNT", "FTO", "NPWMD")
SEVERE_KEYWORDS = ("terroris", "narcotr", "kingpin")

# Nationalities arrive either as a country or as an adjective; normalize the few forms
# this kind of report uses. Unknown values fall through unchanged, so a country we have
# never seen still compares correctly against itself.
_DEMONYMS = {
    "ARGENTINO": "ARGENTINA", "ARGENTINA": "ARGENTINA",
    "COLOMBIANO": "COLOMBIA", "COLOMBIANA": "COLOMBIA",
    "MEXICANO": "MEXICO", "MEXICANA": "MEXICO",
    "VENEZOLANO": "VENEZUELA", "VENEZOLANA": "VENEZUELA",
    "PANAMENO": "PANAMA", "PANAMENA": "PANAMA",
    "PAKISTANI": "PAKISTAN", "AFGANO": "AFGANISTAN", "AFGANA": "AFGANISTAN",
    "BOLIVIANO": "BOLIVIA", "BOLIVIANA": "BOLIVIA",
    "PERUANO": "PERU", "PERUANA": "PERU",
    "BRASILENO": "BRASIL", "BRASILENA": "BRASIL",
    "CHILENO": "CHILE", "CHILENA": "CHILE",
    "ESPANOL": "ESPANA", "ESPANOLA": "ESPANA",
}


@dataclass
class Signal:
    """One identifier compared between client and OFAC subject."""

    name: str      # "fecha de nacimiento"
    state: str     # CONFIRMS / CONTRADICTS / NO_DATA / LIKELY_TYPO
    detail: str    # "1988-11-19 vs 1970-08-12" — the evidence, for the justification


@dataclass
class Verdict:
    classification: str
    priority: str
    signals: list[Signal] = field(default_factory=list)
    rule: str = ""                    # which rule fired — traceability for the audit trail
    insufficient_data: bool = False   # no secondary identifier available to decide with
    name_strength: str = ""


# --- Normalization helpers ----------------------------------------------------------

def _strip_accents(text: str) -> str:
    """'Antón' -> 'Anton'. The same person is written with and without accents across
    the report, so every comparison happens on the accent-free form."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return _strip_accents(text).upper().strip()


def _name_tokens(name: str | None) -> list[str]:
    """Split a name into comparable words, dropping punctuation and particles.

    OFAC writes 'ZULETA TROCHEZ, Jose Oscar' and the bank writes 'Jose Oscar Zuleta
    Trochez'. Comparing token SETS makes the order irrelevant, which is what we want.
    """
    cleaned = re.sub(r"[^A-Z\s]", " ", _normalize(name))
    return [t for t in cleaned.split() if len(t) > 1 and t not in {"DE", "DEL", "LA", "LOS", "Y"}]


def _tokens_match(a: str, b: str) -> bool:
    """Two name words are the same word, allowing for transliteration variants.

    'BALOCH' vs 'BALUCH' is one name transliterated two ways, not two names. We accept a
    high-similarity pair only for words of 5+ characters, so short words like 'JOSE' and
    'JOSA' are never conflated.
    """
    if a == b:
        return True
    if min(len(a), len(b)) >= 5:
        return SequenceMatcher(None, a, b).ratio() >= 0.80
    return False


def _digits_and_letters(value: str | None) -> str:
    """Documents are written as '31.556.201', '31556201' or 'V-10794553'. Strip the
    formatting so only the identifier itself is compared. Letters are kept because a
    Mexican CURP contains them."""
    return re.sub(r"[^A-Z0-9]", "", _normalize(value))


def _year(date: str | None) -> str:
    match = re.search(r"(1[89]\d{2}|20\d{2})", date or "")
    return match.group(1) if match else ""


def _is_severe(program: str | None) -> bool:
    normalized = _normalize(program)
    if any(code in normalized for code in SEVERE_PROGRAMS):
        return True
    return any(word in normalized.lower() for word in SEVERE_KEYWORDS)


# --- Step A: compare each identifier -------------------------------------------------

def compare_names(client_name: str | None, ofac_name: str | None) -> tuple[str, str]:
    """Return (strength, human-readable detail)."""
    client = _name_tokens(client_name)
    ofac = _name_tokens(ofac_name)
    if not client or not ofac:
        return NAME_WEAK, "nombre no disponible en alguno de los dos registros"

    matched_client = [t for t in client if any(_tokens_match(t, o) for o in ofac)]
    matched_ofac = [t for t in ofac if any(_tokens_match(t, c) for c in client)]
    shared = len(matched_client)
    detail = f"{shared} de {len(client)} palabras del nombre del cliente coinciden con el registro OFAC"

    if len(matched_client) == len(client) and len(matched_ofac) == len(ofac):
        return NAME_EXACT, "el nombre completo coincide"
    if len(matched_client) == len(client) or len(matched_ofac) == len(ofac):
        return NAME_CONTAINED, f"un nombre está contenido en el otro ({detail})"
    if shared >= 2:
        return NAME_PARTIAL, detail
    return NAME_WEAK, detail


def compare_dates(client_dob: str | None, ofac_dob: str | None) -> Signal:
    """Compare dates of birth at whatever precision both sides offer.

    The OFAC entry often carries only a year ('1971 (aprox.)'), so comparing full dates
    would throw away a usable signal. We compare years first; only when both sides have a
    full date do we demand the day and month to agree.
    """
    if not client_dob or not ofac_dob:
        return Signal("fecha de nacimiento", NO_DATA, "falta la fecha en alguno de los dos registros")

    client_year, ofac_year = _year(client_dob), _year(ofac_dob)
    if not client_year or not ofac_year:
        return Signal("fecha de nacimiento", NO_DATA, "fecha no interpretable")

    evidence = f"{client_dob} vs {ofac_dob}"
    if client_year != ofac_year:
        return Signal("fecha de nacimiento", CONTRADICTS, f"años distintos ({evidence})")

    client_full = len(client_dob) >= 10 and len(ofac_dob) >= 10
    if client_full and client_dob[:10] != ofac_dob[:10]:
        return Signal("fecha de nacimiento", CONTRADICTS, f"mismo año pero distinto día ({evidence})")
    if client_full:
        return Signal("fecha de nacimiento", CONFIRMS, f"fecha exacta ({client_dob})")
    return Signal("fecha de nacimiento", CONFIRMS, f"coincide el año ({client_year}; la lista no informa el día)")


def compare_nationality(client_nat: str | None, ofac_nat: str | None) -> Signal:
    if not client_nat or not ofac_nat:
        return Signal("nacionalidad", NO_DATA, "falta la nacionalidad en alguno de los dos registros")
    client = _DEMONYMS.get(_normalize(client_nat), _normalize(client_nat))
    ofac = _DEMONYMS.get(_normalize(ofac_nat), _normalize(ofac_nat))
    evidence = f"{client_nat} vs {ofac_nat}"
    if client == ofac:
        return Signal("nacionalidad", CONFIRMS, f"misma nacionalidad ({client_nat})")
    return Signal("nacionalidad", CONTRADICTS, f"nacionalidades distintas ({evidence})")


def compare_documents(
    client_type: str | None, client_number: str | None,
    ofac_type: str | None, ofac_number: str | None,
) -> Signal:
    """Compare identity documents by exact equality of the identifier.

    Equality is required — a fuzzy match on a document number would be indefensible. But
    there is one case worth separating: when both numbers are the SAME DIGITS IN A
    DIFFERENT ORDER (obs. 34: 01633018 vs 10633018), the likeliest explanation is a
    transcription error in the file, not a different person. We refuse to call that a
    match, and we also refuse to count it as a contradiction: we flag it so a human sees
    it. This is exactly the call an analyst makes by hand.
    """
    client = _digits_and_letters(client_number)
    ofac = _digits_and_letters(ofac_number)
    if not client or not ofac:
        return Signal("documento", NO_DATA, "la lista o el legajo no informan número de documento")

    evidence = f"{client_type or 'documento'} {client_number} vs {ofac_type or 'documento'} {ofac_number}"
    if client == ofac:
        return Signal("documento", CONFIRMS, f"mismo número de documento ({client_number})")
    if len(client) == len(ofac) and sorted(client) == sorted(ofac):
        return Signal("documento", LIKELY_TYPO, f"mismos dígitos en distinto orden, probable error de transcripción ({evidence})")
    return Signal("documento", CONTRADICTS, f"documentos distintos ({evidence})")


def compare_birthplaces(client_pob: str | None, ofac_pob: str | None) -> Signal:
    """Birthplaces are free text ('Corinto, Cauca, Colombia'). Compare on shared words so
    that a city written with more or less administrative detail still matches."""
    if not client_pob or not ofac_pob:
        return Signal("lugar de nacimiento", NO_DATA, "falta el lugar de nacimiento en alguno de los dos registros")
    client = set(_name_tokens(client_pob))
    ofac = set(_name_tokens(ofac_pob))
    if not client or not ofac:
        return Signal("lugar de nacimiento", NO_DATA, "lugar no interpretable")
    evidence = f"{client_pob} vs {ofac_pob}"
    if client & ofac:
        return Signal("lugar de nacimiento", CONFIRMS, f"mismo lugar de nacimiento ({client_pob})")
    return Signal("lugar de nacimiento", CONTRADICTS, f"lugares de nacimiento distintos ({evidence})")


def build_signals(obs: Observation) -> list[Signal]:
    """Step A: every identifier we can compare, in the order an analyst would read them."""
    return [
        compare_dates(obs.client_dob, obs.ofac_dob),
        compare_nationality(obs.client_nationality, obs.ofac_nationality),
        compare_documents(obs.client_doc_type, obs.client_doc_number, obs.ofac_doc_type, obs.ofac_doc_number),
        compare_birthplaces(obs.client_pob, obs.ofac_pob),
    ]


# --- Step B: the decision tree --------------------------------------------------------

def classify(obs: Observation) -> Verdict:
    """Turn the extracted form into a classification, a priority and the evidence.

    The rules are ordered and mutually exclusive: the first one that applies decides, and
    its number is recorded in the verdict so any row of the CSV can be traced back to the
    exact rule that produced it.
    """
    signals = build_signals(obs)
    name_strength, name_detail = compare_names(obs.client_name, obs.ofac_name)
    strong_name = name_strength in (NAME_EXACT, NAME_CONTAINED)
    signals.insert(0, Signal("nombre", CONFIRMS if strong_name else CONTRADICTS, name_detail))

    # Only the secondary identifiers vote. The name is what raised the alert in the first
    # place, so counting it as evidence would be counting the question as the answer.
    # Strong and supporting identifiers are tallied separately (see STRONG_SIGNALS): a
    # matching nationality cannot rescue a mismatched date of birth.
    secondary = signals[1:]
    strong_confirms = [s for s in secondary if s.name in STRONG_SIGNALS and s.state == CONFIRMS]
    strong_contradicts = [s for s in secondary if s.name in STRONG_SIGNALS and s.state == CONTRADICTS]
    support_confirms = [s for s in secondary if s.name in SUPPORTING_SIGNALS and s.state == CONFIRMS]
    document_matches = any(s.name == "documento" and s.state == CONFIRMS for s in secondary)
    severe = _is_severe(obs.ofac_program)

    def verdict(classification, priority, rule, insufficient=False):
        return Verdict(classification, priority, signals, rule, insufficient, name_strength)

    # 1. The client is a person; if the OFAC entry is a vessel or a company it cannot be
    #    the same party. OFAC's own FAQ 5 asks this question first.
    if _normalize(obs.ofac_entity_type) not in ("PERSON", "PERSONA", ""):
        return verdict(FALSE_POSITIVE, LOW, "R1 · el registro OFAC no es una persona física")

    # 2. A match resting only on an alias OFAC itself marks as weak, with nothing else
    #    confirming it, is the textbook false positive.
    if obs.ofac_alias_weak and not strong_confirms:
        return verdict(FALSE_POSITIVE, LOW, "R2 · el match se apoya solo en un alias débil")

    # 3. Same document number: the single most discriminating identifier there is.
    if document_matches:
        return verdict(POSSIBLE_MATCH, HIGH, "R3 · coincide el número de documento")

    # 4. A strong identifier clearly contradicts and none confirms: a homonym. The name
    #    matched, but a discriminating identifier (date of birth or document) says it is a
    #    different person. A shared nationality does NOT rescue this — it is weak evidence
    #    and half a country carries it. Program severity does not raise it either: once
    #    the identifiers have ruled the match out, escalating would feed the analyst's
    #    queue the very noise this agent exists to remove.
    if strong_contradicts and not strong_confirms:
        return verdict(FALSE_POSITIVE, LOW, "R4 · un identificador fuerte contradice el match (homónimo)")

    # 5. Two or more strong identifiers agree, none contradicts.
    if len(strong_confirms) >= 2:
        return verdict(POSSIBLE_MATCH, HIGH, "R5 · coinciden varios identificadores fuertes")

    # 6. One strong identifier confirms and none contradicts. A single strong match (e.g.
    #    the date of birth) is a real lead but not conclusive on its own, so it warrants
    #    review at MEDIUM. It rises to HIGH only for a severe program (terrorism, narco),
    #    where the cost of missing a true match justifies the urgency. A matching
    #    nationality does NOT raise it — it is weak support, not grounds to jump the queue.
    if strong_confirms:
        priority = HIGH if severe else MEDIUM
        return verdict(POSSIBLE_MATCH, priority, "R6 · coincide un identificador fuerte")

    # From here on there are NO strong identifiers either way — only the name and, at
    # most, supporting signals. The name is all the weight we have.

    # 7. Strong name with no strong identifier to verify against. We cannot confirm or
    #    rule out, so we escalate for human review instead of inventing certainty.
    if strong_name:
        priority = HIGH if severe else MEDIUM
        return verdict(POSSIBLE_MATCH, priority,
                       "R7 · nombre fuerte sin identificadores para verificar", insufficient=True)

    # 8. Partial name backed only by a supporting signal (same nationality). Too weak to
    #    escalate — a common surname plus a shared country is the routine false positive.
    if name_strength == NAME_PARTIAL:
        return verdict(FALSE_POSITIVE, LOW, "R8 · nombre parcial, sin identificadores que confirmen")

    # 9. The name barely overlaps at all (a single shared token) and nothing supports it.
    return verdict(FALSE_POSITIVE, LOW, "R9 · el nombre casi no coincide y no hay identificadores")
