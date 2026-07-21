"""
The structured "form" the LLM fills in for each observation.

This is the boundary between the two halves of the pipeline: the LLM extracts
these raw, normalized fields from the prose; the deterministic classifier reads
them and decides. The LLM does NOT classify — it only reports what it reads.

Design notes:
- Optional/None everywhere a field may be absent ("sin documento informado").
- Dates are normalized to ISO by the LLM (YYYY-MM-DD, or just YYYY when only the
  year is known) — the one normalization the LLM does well on irregular input.
- `engine_score` and `internal_risk` are extracted only to be recorded and then
  deliberately IGNORED by the classifier — they are decoys (a 97% score can be a
  false positive). Capturing them lets us show we chose to ignore them.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Observation(BaseModel):
    # --- Client: the bank's account holder that got flagged ---
    client_name: str = Field(description="Full name of the bank client, as written.")
    client_doc_type: Optional[str] = Field(
        None, description="Client document type (DNI, Pasaporte, Cédula, CURP, ...) or null if none informed."
    )
    client_doc_number: Optional[str] = Field(
        None, description="Client document number as written, or null if none informed."
    )
    client_dob: Optional[str] = Field(
        None, description="Client date of birth in ISO YYYY-MM-DD, or YYYY if only the year is known, or null."
    )
    client_nationality: Optional[str] = Field(
        None, description="Client nationality / country, or null."
    )
    client_pob: Optional[str] = Field(
        None,
        description=(
            "Client PLACE OF BIRTH (city/region/country), or null. Only the birthplace — "
            "never the home address ('domicilio'), which is a different field."
        ),
    )

    # --- OFAC SDN subject that the client matched against ---
    ofac_name: str = Field(description="Primary name of the OFAC SDN subject (e.g. 'APELLIDO, Nombre').")
    ofac_aliases: List[str] = Field(
        default_factory=list, description="Aliases listed for the OFAC subject; empty list if none."
    )
    ofac_alias_weak: bool = Field(
        False, description="True if the match relies on an alias marked weak/débil («weak»)."
    )
    ofac_program: Optional[str] = Field(
        None, description="OFAC sanctions program code (e.g. SDNTK, VENEZUELA), or null."
    )
    ofac_dob: Optional[str] = Field(
        None, description="OFAC subject date of birth in ISO YYYY-MM-DD, or YYYY if only the year is known, or null."
    )
    ofac_nationality: Optional[str] = Field(
        None, description="OFAC subject nationality / country, or null."
    )
    ofac_pob: Optional[str] = Field(
        None, description="OFAC subject PLACE OF BIRTH (city/region/country), or null."
    )
    ofac_doc_type: Optional[str] = Field(None, description="OFAC subject document type, or null.")
    ofac_doc_number: Optional[str] = Field(None, description="OFAC subject document number as written, or null.")
    ofac_entity_type: str = Field(
        "person", description="Type of the OFAC entity: 'person', 'vessel', or 'company'."
    )

    # --- Decoys: recorded but IGNORED by the classifier ---
    engine_score: Optional[int] = Field(
        None, description="Screening engine match score as an integer percent, or null if not present."
    )
    internal_risk: Optional[str] = Field(
        None, description="Bank internal risk level if present (bajo/medio/alto), or null."
    )
