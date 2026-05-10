"""Risk agent — CEA salesperson verification and rental scam screening (D).

Two-tier verification strategy:
  1. Live API  – data.gov.sg (via tools/csv_lookup.py)
  2. Local CSV  – data/cea_agents.csv (offline fallback)
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from agents import AgentInput, AgentOutput, INTERNAL_JSON_OUTPUT_INSTRUCTION, afc_limiter
from config import settings
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)


def _enrich_records_with_expiry(records: list[dict[str, Any]]) -> None:
    """Add ``_is_expired`` and ``_days_to_expiry`` to each record in-place."""
    today = date.today()
    for rec in records:
        end_str = rec.get("registration_end_date", "").strip()
        try:
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
            rec["_is_expired"] = end_date < today
            rec["_days_to_expiry"] = (end_date - today).days
        except (ValueError, TypeError):
            rec["_is_expired"] = None
            rec["_days_to_expiry"] = None


# ---------------------------------------------------------------------------
# Step 1 – Local CSV lookup
# ---------------------------------------------------------------------------

def lookup_cea_local(query_type: str, query_value: str) -> dict[str, Any]:
    """Search the bundled ``cea_agents.csv`` for a salesperson.

    Args:
        query_type: ``"reg_no"`` (exact) or ``"name"`` (substring, case-insensitive).
        query_value: The registration number or salesperson name to look up.

    Returns:
        ``{"found": bool, "records": list[dict], "source": "local_csv", "message"?: str}``.
        Each record is augmented with ``_is_expired`` and ``_days_to_expiry``.
    """
    csv_path: Path = settings.cea_agents_path
    if not csv_path.exists():
        logger.warning("CEA agents CSV not found at %s", csv_path)
        return {
            "found": False,
            "records": [],
            "source": "local_csv",
            "message": f"Local CSV file not found: {csv_path}",
        }

    records: list[dict[str, Any]] = []
    query_norm = query_value.strip().lower()

    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if query_type == "reg_no":
                if row.get("registration_no", "").strip().lower() == query_norm:
                    records.append(dict(row))
                    break  # registration_no is unique per person
            elif query_type == "name":
                name = row.get("salesperson_name", "").strip().lower()
                # substring match in either direction (handles partial / parenthesised names)
                if query_norm in name or name in query_norm:
                    records.append(dict(row))
            else:
                return {
                    "found": False,
                    "records": [],
                    "source": "local_csv",
                    "message": f"Unsupported query_type: {query_type}",
                }

    if not records:
        return {
            "found": False,
            "records": [],
            "source": "local_csv",
            "message": f"No match for {query_type} '{query_value}' in local CSV.",
        }

    # Enrich with expiry checks
    _enrich_records_with_expiry(records)

    return {"found": True, "records": records, "source": "local_csv"}


# ---------------------------------------------------------------------------
# Step 2 – Combined verification (API → CSV fallback)
# ---------------------------------------------------------------------------

def verify_cea_agent(
    query_type: str,
    query_value: str,
    *,
    timeout: int = 10,
) -> dict[str, Any]:
    """Verify a CEA agent through the **live data.gov.sg API**, falling back to
    the local CSV when the API is unreachable or returns an error.

    Args:
        query_type: ``"reg_no"`` or ``"name"``.
        query_value: The value to search.
        timeout: HTTP timeout in seconds (passed through to ``requests.get``).

    Returns:
        A dict with keys ``status``, ``records``, ``source``, and ``message``.
        ``source`` is one of ``"api"``, ``"local_csv"``, or ``"local_csv_fallback"``.
    """
    # 2a. Try live API -------------------------------------------------------
    try:
        from tools.csv_lookup import verify_cea_agent_status

        result = verify_cea_agent_status(query_type, query_value)

        if result.get("status") == "verified":
            result["source"] = "api"
            _enrich_records_with_expiry(result.get("records", []))
            return result

        if result.get("status") == "risk":
            # API explicitly says no match → cross-check with local CSV
            local = lookup_cea_local(query_type, query_value)
            if local["found"]:
                local["api_note"] = "API returned no results, but a local CSV match exists."
                return local
            result["source"] = "api"
            return result

        # status == "error" or unexpected
        logger.warning("data.gov.sg API error: %s", result.get("message"))
    except Exception as exc:
        logger.warning("data.gov.sg API call failed (%s); falling back to local CSV.", exc)

    # 2b. Fallback to local CSV ----------------------------------------------
    local = lookup_cea_local(query_type, query_value)
    if local["found"]:
        local["source"] = "local_csv_fallback"
        local["api_note"] = "Live API was unavailable; result is from cached local data."
    else:
        local["source"] = "local_csv_fallback"
    return local


# ---------------------------------------------------------------------------
# Step 3 – Risk scoring
# ---------------------------------------------------------------------------

def _score_risk(verification: dict[str, Any]) -> dict[str, Any]:
    """Derive a 0–100 risk score from a verification result.

    Scoring dimensions (100 pts total):
        - Registration status       60 pts  — is the agent registered?
        - Registration validity     25 pts  — is the registration current?
        - Data source reliability   15 pts  — how trustworthy is the data?

    Missing points are explained with a reason AND a recommendation so the
    user knows what went wrong and how to fix it.

    Returns:
        ``{"score": float, "risk_level": str, "reasons": list[str]}``
    """
    score = 0.0
    reasons: list[str] = []
    source = verification.get("source", "unknown")
    records: list[dict[str, Any]] = verification.get("records", [])

    # --- Registration status (60 pts) ---------------------------------------
    if verification.get("status") == "verified" or verification.get("found"):
        score += 60
        reasons.append("CEA registration confirmed (+60 pts).")
    else:
        reasons.append(
            "CEA registration NOT FOUND (+0/60 pts). "
            "The agent's name or registration number does not appear in the "
            "official CEA database. Action: ask the agent for their CEA "
            "registration number and re-check, or verify at cea.gov.sg."
        )

    # --- Registration validity (25 pts) -------------------------------------
    if records:
        best = records[0]
        expired = best.get("_is_expired")
        days_left = best.get("_days_to_expiry")

        if expired is True:
            reasons.append(
                f"Registration EXPIRED on {best.get('registration_end_date')} "
                f"(+0/25 pts). The agent is no longer legally authorised. "
                f"Action: do NOT sign or pay until the agent renews their "
                f"CEA registration."
            )
        elif expired is False and days_left is not None:
            if days_left <= 90:
                score += 10
                reasons.append(
                    f"Registration expires in {days_left} days on "
                    f"{best.get('registration_end_date')} (+10/25 pts). "
                    f"Action: confirm the agent will renew before the "
                    f"tenancy start date."
                )
            else:
                score += 25
                reasons.append(
                    f"Registration valid until {best.get('registration_end_date')} "
                    f"(+25/25 pts)."
                )
        else:
            reasons.append(
                f"Could not determine registration expiry (+0/25 pts). "
                f"Action: manually verify the expiry date on the CEA "
                f"public register at cea.gov.sg."
            )
    else:
        reasons.append(
            "No registration record to check expiry (+0/25 pts). "
            "Action: confirm the agent is registered before proceeding."
        )

    # --- Data source reliability (15 pts) -----------------------------------
    if source == "api":
        score += 15
        reasons.append(
            "Data sourced from live data.gov.sg API — most reliable (+15/15 pts)."
        )
    elif source in ("local_csv", "local_csv_fallback"):
        score += 8
        reasons.append(
            f"Data sourced from local CSV cache — may be outdated (+8/15 pts). "
            f"Action: re-run when data.gov.sg API is reachable for the most "
            f"current result."
        )
    else:
        reasons.append(
            f"Data source unknown — unverified (+0/15 pts). "
            f"Action: manually verify via cea.gov.sg."
        )

    # --- Map to risk level --------------------------------------------------
    if score >= 70:
        risk_level = "low"
    elif score >= 45:
        risk_level = "medium"
    else:
        risk_level = "high"

    return {"score": score, "risk_level": risk_level, "reasons": reasons}


# ---------------------------------------------------------------------------
# Step 4 – Risk tips / recommendations
# ---------------------------------------------------------------------------

def _risk_tips(
    verification: dict[str, Any],
    address: str | None = None,
) -> list[str]:
    """Generate actionable recommendations from a verification result."""
    tips: list[str] = []
    records: list[dict[str, Any]] = verification.get("records", [])
    source = verification.get("source", "unknown")
    found = verification.get("found") or verification.get("status") == "verified"

    if not found:
        tips.append(
            "STOP: The salesperson / agent is NOT registered with CEA. "
            "Do NOT transfer any deposit or sign the contract until you verify "
            "their identity through official channels (https://www.cea.gov.sg)."
        )
    else:
        tips.append("CEA registration found — proceed with standard due diligence.")

    if source in ("local_csv", "local_csv_fallback"):
        tips.append(
            "Verification used cached local data. For the most up‑to‑date status, "
            "re‑run when the data.gov.sg API is available."
        )

    if records:
        rec = records[0]
        if rec.get("_is_expired"):
            tips.append(
                f"Registration expired on {rec.get('registration_end_date')}. "
                "The agent is no longer legally authorised to handle property transactions."
            )
        elif rec.get("_days_to_expiry") is not None and rec["_days_to_expiry"] <= 90:
            tips.append(
                f"Registration expires in {rec['_days_to_expiry']} days. "
                "Confirm renewal before signing a tenancy agreement."
            )

        estate_agent = rec.get("estate_agent_name", "").strip()
        license_no = rec.get("estate_agent_license_no", "").strip()
        if estate_agent:
            tips.append(f"Agent is registered under: {estate_agent} (licence {license_no}).")

    if address:
        tips.append(
            "Cross‑check that the address on the contract matches the viewing location "
            "and that the landlord's identity is verifiable."
        )

    if not tips:
        tips.append("No specific risk flags detected. Always verify in person before paying.")

    return tips


# ---------------------------------------------------------------------------
# Step 5 – Deterministic assessment (CLI / offline / tests)
# ---------------------------------------------------------------------------

def assess_risk(
    input_data: AgentInput | dict[str, Any],
    *,
    agent_name: str | None = None,
    agent_reg_no: str | None = None,
) -> AgentOutput:
    """Run the full risk screening and return a structured ``AgentOutput``.

    If *agent_name* or *agent_reg_no* is provided, a CEA verification is
    performed.  Otherwise the agent falls back to general address‑based
    scam-screening heuristics.

    Args:
        input_data: ``AgentInput`` or compatible dict.
        agent_name: Optional salesperson name to verify.
        agent_reg_no: Optional CEA registration number to verify.
    """
    request = input_data if isinstance(input_data, AgentInput) else AgentInput(**input_data)
    address = request.address or ""
    evidence: list[str] = []
    data: dict[str, Any] = {"address": address}

    # --- Determine what to verify -------------------------------------------
    verification: dict[str, Any] | None = None
    source_mode: str = "unknown"  # "direct" | "contract" | "unknown"

    if agent_reg_no:
        verification = verify_cea_agent("reg_no", agent_reg_no)
        source_mode = "direct"
    elif agent_name:
        verification = verify_cea_agent("name", agent_name)
        source_mode = "direct"
    elif request.contract_text:
        extracted = _extract_agent_name_from_text(request.contract_text)
        if extracted:
            agent_name = extracted
            verification = verify_cea_agent("name", agent_name)
            source_mode = "contract"

    # --- Build output -------------------------------------------------------
    if verification is not None:
        score_result = _score_risk(verification)
        score = score_result["score"]
        risk_level = score_result["risk_level"]
        score_reasons = score_result["reasons"]
        recommendations = _risk_tips(verification, address)

        identity = agent_name or agent_reg_no or "agent"

        # --- Findings: concise for direct input, detailed for contract ------
        findings: list[str] = []
        is_clean = (verification.get("found") or verification.get("status") == "verified")

        if is_clean:
            if source_mode == "direct":
                # Direct input, verified: one-liner only
                if score == 100.0:
                    findings.append(f"CEA check for {identity}: verified, no issues found.")
                else:
                    findings.append(f"CEA check for {identity}: verified.")
                    # Verified but not perfect (e.g. CSV source, near expiry)
                    for reason in score_reasons:
                        if not reason.startswith("CEA registration confirmed"):
                            findings.append(reason)
            else:
                # Contract extraction or unknown source: detailed
                findings.append(f"CEA check for {identity}: verified.")
                _skip = {"CEA registration confirmed.", "Data source: live data.gov.sg API.", "Data source: local CSV"}
                for reason in score_reasons:
                    if not any(reason.startswith(s) for s in _skip):
                        findings.append(reason)
        else:
            findings.append(f"CEA check for {identity}: NOT FOUND in registry.")
            for reason in score_reasons:
                findings.append(reason)

        # --- Evidence: one-liner --------------------------------------------
        evidence: list[str] = []
        rec = (verification.get("records") or [None])[0]
        if rec:
            evidence.append(
                f"CEA registry lookup via {verification.get('source', 'unknown')}: "
                f"{rec.get('registration_no', 'N/A')}, "
                f"valid until {rec.get('registration_end_date', 'N/A')}"
            )
        else:
            evidence.append(
                f"CEA registry lookup via {verification.get('source', 'unknown')}: "
                f"no records found."
            )

        # --- Data: essential fields only ------------------------------------
        data["verification_source"] = verification.get("source")
        if rec:
            data["registration_no"] = rec.get("registration_no")
            data["registration_end_date"] = rec.get("registration_end_date")
            data["estate_agent_name"] = rec.get("estate_agent_name")

        return AgentOutput(
            agent_name="risk_agent",
            summary=f"CEA verification for {identity}: {'PASSED' if risk_level == 'low' else 'FLAGGED'}.",
            risk_level=risk_level,
            score=score,
            findings=findings,
            evidence=evidence,
            recommendations=recommendations,
            data=data,
        )

    # --- No agent to verify → classify the scenario -------------------------
    findings: list[str] = []
    recommendations: list[str] = []

    # Check if user explicitly said there's no agent (direct landlord deal)
    _no_agent_hints = [
        r"direct\s+(landlord|owner)", r"no\s+agent", r"without\s+agent",
        r"直接\s*(找|和|跟|与)?\s*房东", r"没有\s*(中介|代理|经纪)",
        r"无\s*中介", r"private\s+landlord", r"owner\s+(directly|himself)",
        r"landlord\s+(direct|directly)", r"房东\s*(直接|本人)",
    ]
    user_text = ""
    if request.contract_text:
        user_text = request.contract_text
    elif request.address:
        user_text = request.address
    is_direct_landlord = any(
        re.search(hint, user_text, re.IGNORECASE) for hint in _no_agent_hints
    )

    if is_direct_landlord:
        findings.append(
            "Direct landlord deal detected — no salesperson/agent involved. "
            "CEA agent verification is not applicable."
        )
        recommendations.append(
            "When renting directly from a landlord, verify the landlord's "
            "identity against the property ownership records (e.g. via SLA "
            "or IRAS property tax statement). Confirm the bank account name "
            "matches the landlord's NRIC name before transferring any deposit."
        )
        recommendations.append(
            "Ensure the tenancy agreement includes clear maintenance "
            "responsibilities, inventory lists, and stamp duty obligations "
            "— these are often problematic in direct rental deals."
        )
        return AgentOutput(
            agent_name="risk_agent",
            summary="Direct landlord deal — no CEA agent involvement. Verify landlord identity independently.",
            risk_level="medium",
            score=None,
            findings=findings,
            evidence=[],
            recommendations=recommendations,
            data={
                "address": address,
                "landlord_mode": "direct",
                "contract_path_provided": bool(request.contract_path),
                "contract_text_provided": bool(request.contract_text),
            },
        )

    if address:
        findings.append(f"Rental address: {address}.")

    if request.contract_path:
        findings.append("Contract PDF path provided. Ensure the PDF has been opened and reviewed. If this is a scanned image or password-protected file, the agent name may not have been extractable.")
        recommendations.append("Check that the contract PDF is a text-based document (not a scanned image). Scanned PDFs require OCR and may cause agent name extraction to fail.")
    elif request.contract_text:
        findings.append("Contract text is available, but no agent name or CEA registration number could be found. The contract may not contain explicit agent identity fields, or the format may be non-standard.")
        recommendations.append("Manually review the contract for agent details (look for 'Agent:', 'Salesperson:', 'CEA Reg No:', or 'RxxxxxxX' patterns). If found, provide them to the Risk Agent directly.")
    else:
        findings.append("No contract provided — agent identity cannot be verified.")
        recommendations.append(
            "Upload or provide a path to the rental contract PDF so the Risk Agent "
            "can scan it for agent identity clues."
        )

    if not address:
        findings.append("No address provided — limited screening possible.")

    recommendations.append(
        "Alternatively, provide the agent's CEA registration number manually "
        "via --agent-name or --agent-reg-no to skip contract scanning."
    )

    return AgentOutput(
        agent_name="risk_agent",
        summary="Risk screening: no CEA agent identified for verification.",
        risk_level="unknown",
        score=None,
        findings=findings,
        evidence=[],
        recommendations=recommendations,
        data={
            "address": address,
            "contract_path_provided": bool(request.contract_path),
            "contract_text_provided": bool(request.contract_text),
            "agent_queried": agent_name or agent_reg_no,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_agent_name_from_text(text: str) -> str | None:
    """Heuristic extraction of a CEA agent name from contract or free‑form text.

    Looks for patterns like:
        - "Agent: John Tan (R123456A)"
        - "CEA Reg No: R123456A"
        - "Salesperson: ..."
    """
    if not text:
        return None

    # Try explicit "Agent:" / "Salesperson:" labels first
    label_patterns = [
        r"(?:Agent|Salesperson|CEA\s*Agent|Estate\s*Agent)\s*[:：]\s*([^\n]{3,60})",
    ]
    for pattern in label_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            # Filter out obviously bogus captures
            if len(candidate) >= 3 and not candidate.lower().startswith(("ce", "reg")):
                return candidate

    # Fallback: look for a CEA registration number and capture nearby name
    reg_match = re.search(r"R\d{5,6}[A-Z]", text)
    if reg_match:
        # Grab up to 60 chars before the reg number as potential name context
        before = text[: reg_match.start()]
        before_words = before.split()[-6:]  # last ~6 words
        if before_words:
            return " ".join(before_words).strip(" ,;:")

    return None


# ---------------------------------------------------------------------------
# Step 6 – ADK LlmAgent
# ---------------------------------------------------------------------------

def compute_risk_score(
    status: str,
    source: str,
    registration_end_date: str = "",
) -> dict[str, Any]:
    """Compute a precise risk score and classify registration status.

    Call this AFTER ``verify_cea_agent`` returns.  Pass the top-level fields
    from the verification result dict.

    Args:
        status: ``"verified"`` if the agent was found, ``"risk"`` if not.
        source: ``"api"``, ``"local_csv"``, or ``"local_csv_fallback"``.
        registration_end_date: YYYY-MM-DD string from the first record (may be empty).

    Returns:
        ``{"score": float, "risk_level": str, "registration_status": str,
          "status_label": str, "reasons": list[str]}``

        registration_status values:
          - ``"active"`` — registered, not expired, > 90 days remaining
          - ``"expiring_soon"`` — registered, ≤ 90 days remaining
          - ``"expired"`` — registration has lapsed
          - ``"not_found"`` — not in CEA registry
    """
    verification = {
        "status": status,
        "source": source,
        "records": (
            [{"registration_end_date": registration_end_date}]
            if registration_end_date
            else []
        ),
    }
    _enrich_records_with_expiry(verification["records"])
    result = _score_risk(verification)

    # --- Classify registration status -----------------------------------
    if status != "verified" and not verification.get("found"):
        reg_status = "not_found"
        status_label = "未注册 (Not Registered)"
    elif verification["records"]:
        rec = verification["records"][0]
        if rec.get("_is_expired"):
            reg_status = "expired"
            status_label = "已过期 (Expired)"
        elif rec.get("_days_to_expiry") is not None and rec["_days_to_expiry"] <= 90:
            reg_status = "expiring_soon"
            status_label = f"即将过期 (Expiring in {rec['_days_to_expiry']} days)"
        else:
            reg_status = "active"
            status_label = "有效 (Active)"
    else:
        reg_status = "active"
        status_label = "有效 (Active)"

    return {
        "score": result["score"],
        "risk_level": result["risk_level"],
        "registration_status": reg_status,
        "status_label": status_label,
        "reasons": result["reasons"],
    }


def generate_risk_tips(
    status: str,
    source: str,
    registration_end_date: str = "",
    estate_agent_name: str = "",
    estate_agent_license_no: str = "",
    contract_company_name: str = "",
    address: str = "",
) -> list[str]:
    """Generate actionable risk recommendations from verification fields.

    Call this AFTER ``compute_risk_score``.  Pass the same fields from the
    verification result dict.  If you found a company name in the contract,
    pass it as ``contract_company_name`` for a cross-check recommendation.

    Returns:
        A list of recommendation strings.
    """
    record: dict[str, Any] = {}
    if registration_end_date:
        record["registration_end_date"] = registration_end_date
    if estate_agent_name:
        record["estate_agent_name"] = estate_agent_name
    if estate_agent_license_no:
        record["estate_agent_license_no"] = estate_agent_license_no

    verification: dict[str, Any] = {
        "found": status == "verified",
        "status": status,
        "source": source,
        "records": [record] if record else [],
    }
    _enrich_records_with_expiry(verification["records"])
    tips = _risk_tips(verification, address if address else None)

    # --- Company cross-check recommendation ---------------------------------
    if estate_agent_name and contract_company_name:
        cea_company = estate_agent_name.strip().lower()
        contract_company = contract_company_name.strip().lower()
        if cea_company == contract_company:
            tips.append(
                f"✅ Company match: contract party '{contract_company_name}' "
                f"matches CEA record '{estate_agent_name}'."
            )
        else:
            tips.append(
                f"⚠️ COMPANY MISMATCH: The contract lists '{contract_company_name}' "
                f"but CEA records show the agent is registered under "
                f"'{estate_agent_name}' (licence {estate_agent_license_no}). "
                f"Verify who you are signing with before proceeding."
            )
    elif estate_agent_name and not contract_company_name:
        tips.append(
            f"ℹ️ The agent is registered under '{estate_agent_name}' "
            f"(licence {estate_agent_license_no}). Cross-check that the company "
            f"name on the contract matches this CEA record."
        )
    elif contract_company_name and not estate_agent_name:
        tips.append(
            f"⚠️ Contract mentions '{contract_company_name}' but no CEA company "
            f"record was found for this agent. Verify independently."
        )

    return tips


def _extract_agent_reg_no_from_text(text: str) -> str | None:
    match = re.search(r"R\d{5,6}[A-Z]|P\d{5,6}[A-Z]", text or "", re.IGNORECASE)
    return match.group(0).upper() if match else None


def _extract_company_name_from_text(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"(?:Estate\s+Agent|Agency|Company)\s*[:\-]\s*([^\n]{3,80})",
        r"(?:represented\s+by)\s+([A-Za-z0-9 &.,'-]{3,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip(" ,.;")
    return ""


def run_risk_assessment(
    address: str = "",
    agent_name: str = "",
    agent_reg_no: str = "",
    contract_text: str = "",
) -> dict[str, Any]:
    """Run CEA verification, scoring, and risk tips in one ADK tool call."""

    query_type = ""
    query_value = ""
    source_mode = "unknown"

    if agent_reg_no:
        query_type = "reg_no"
        query_value = agent_reg_no
        source_mode = "direct"
    elif agent_name:
        query_type = "name"
        query_value = agent_name
        source_mode = "direct"
    elif contract_text:
        extracted_reg_no = _extract_agent_reg_no_from_text(contract_text)
        extracted_name = _extract_agent_name_from_text(contract_text)
        if extracted_reg_no:
            query_type = "reg_no"
            query_value = extracted_reg_no
            source_mode = "contract"
        elif extracted_name:
            query_type = "name"
            query_value = extracted_name
            source_mode = "contract"

    if not query_type or not query_value:
        return {
            "status": "partial_result",
            "risk_level": "unknown",
            "score": None,
            "identity": "",
            "source_mode": source_mode,
            "findings": ["No agent name or CEA registration number found."],
            "recommendations": [
                "Ask for the agent's full name and CEA registration number, then verify it before paying."
            ],
            "evidence": [],
        }

    verification = verify_cea_agent(query_type, query_value)
    status = verification.get("status") or (
        "verified" if verification.get("found") else "risk"
    )
    source = verification.get("source", "unknown")
    record = (verification.get("records") or [{}])[0]
    score_result = compute_risk_score(
        status,
        source,
        str(record.get("registration_end_date", "")),
    )
    contract_company_name = _extract_company_name_from_text(contract_text)
    recommendations = generate_risk_tips(
        status,
        source,
        str(record.get("registration_end_date", "")),
        str(record.get("estate_agent_name", "")),
        str(record.get("estate_agent_license_no", "")),
        contract_company_name,
        address,
    )

    return {
        "status": "ok",
        "identity": query_value,
        "query_type": query_type,
        "source_mode": source_mode,
        "verification": verification,
        "score": score_result["score"],
        "risk_level": score_result["risk_level"],
        "registration_status": score_result["registration_status"],
        "status_label": score_result["status_label"],
        "findings": score_result["reasons"],
        "recommendations": recommendations,
        "evidence": [
            (
                f"CEA registry lookup via {source}: "
                f"{record.get('registration_no', 'N/A')}, "
                f"valid until {record.get('registration_end_date', 'N/A')}"
            )
            if record
            else f"CEA registry lookup via {source}: no records found."
        ],
        "contract_company_name": contract_company_name,
    }


_RISK_AGENT_LEGACY_INSTRUCTION = """\
You screen Singapore rental leads for scam and compliance risks.

Workflow (follow this order exactly):
1. Look for agent identity clues in the contract text (e.g. "Agent:", "Salesperson:",
   "CEA Reg No:", "RxxxxxxX" patterns). When you find a name or registration number,
   call ``verify_cea_agent`` with query_type "name" or "reg_no".
2. Take the "status" and "source" from the verification result.  Find the
   "registration_end_date", "estate_agent_name", and "estate_agent_license_no"
   from the first record (if any).  Call ``compute_risk_score`` with these values.
3. Look for a company / agency name in the contract text (e.g. after "Estate Agent:",
   "Agency:", or the letterhead).  Call ``generate_risk_tips`` with the same
   verification fields PLUS the ``contract_company_name`` if found — this enables
   a company cross-check recommendation.
4. Assemble the final JSON AgentOutput using the values returned by the tools.
   Do NOT invent your own score, risk_level, or recommendations.

In the final JSON AgentOutput:
- If the user directly provided an agent name or reg no (``agent_name`` /
  ``agent_reg_no`` is set): keep the report *concise*.
  - ``summary``: one-liner with status_label and score.
  - ``findings``: if score == 100, a single "verified, no issues found".
    Otherwise list only the deductions and their reasons.
- If you found the agent by searching the contract text (``contract_text``):
  keep the report *detailed*.
  - ``summary``: one sentence covering status_label, risk_level and score.
  - ``findings``: include status_label, then all reasons from compute_risk_score.
  - ``recommendations``: use the exact list from generate_risk_tips.
  - ``evidence``: include the CEA record details for traceability.

Available data from session state:
  Rental address: {address?}
  Monthly rent (SGD): {rent?}
  Number of bedrooms: {bedrooms?}
  Agent name (if provided by user): {agent_name?}
  Agent CEA reg no (if provided by user): {agent_reg_no?}
  Contract file name: {contract_file_name?}
  Extracted contract text: {contract_text?}

If the user has already provided an agent name or CEA registration number (see
``agent_name`` / ``agent_reg_no`` above), use it directly — no need to search
the contract text.  If both a name and contract text are available, verify
the name first, then also check the contract for additional agent details.

If no agent name can be found, output risk_level "unknown", score null, and
general scam-screening recommendations.  Do not call the tools in that case.

Output a concise JSON AgentOutput. The ``risk_level`` must be one of:
"low", "medium", "high", or "unknown".  ``score`` must be a float 0-100 or null.
"""


RISK_AGENT_INSTRUCTION = """\
You screen Singapore rental leads for scam and compliance risks.

Call the run_risk_assessment tool once with the available address, agent name,
agent CEA registration number, and contract text from session state. The tool
performs identity extraction, CEA verification, risk scoring, and recommendation
generation in one call. Use the tool result directly.
Do NOT invent your own score, risk_level, or recommendations.
After the tool returns, produce one JSON AgentOutput and stop.
Do not call any tool a second time.

In the final JSON AgentOutput:
- If the user directly provided an agent name or reg no (agent_name /
  agent_reg_no is set): keep the report concise.
- If the agent was found by searching contract_text: keep the report detailed.
- Use the tool result's score, risk_level, findings, evidence, and
  recommendations directly.

Available data from session state:
  Rental address: {address?}
  Monthly rent (SGD): {rent?}
  Number of bedrooms: {bedrooms?}
  Agent name (if provided by user): {agent_name?}
  Agent CEA reg no (if provided by user): {agent_reg_no?}
  Contract file name: {contract_file_name?}
  Extracted contract text: {contract_text?}

If no agent identity can be found, output risk_level "unknown", score null, and
general scam-screening recommendations based on the run_risk_assessment result.

Output a concise JSON AgentOutput. The risk_level must be one of:
"low", "medium", "high", or "unknown". The score must be a float 0-100 or null.
"""


def create_risk_agent(model: str = settings.specialist_model) -> LlmAgent:
    return LlmAgent(
        name="risk_agent",
        model=model,
        instruction=RISK_AGENT_INSTRUCTION + "\n" + INTERNAL_JSON_OUTPUT_INSTRUCTION,
        tools=[FunctionTool(run_risk_assessment)],
        generate_content_config=afc_limiter(2),
        output_key="risk_output",
    )


risk_agent = create_risk_agent()


__all__ = [
    "assess_risk",
    "create_risk_agent",
    "lookup_cea_local",
    "risk_agent",
    "run_risk_assessment",
    "verify_cea_agent",
]
