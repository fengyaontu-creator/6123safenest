from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.intake_agent import (
    extract_rental_info_from_query,
    missing_required_fields,
    parse_model_extraction,
)


def test_extracts_required_fields_from_freeform_query():
    data = extract_rental_info_from_query(
        "Please assess 123 Jurong West, rent SGD 2000, contract data/sample_contract.pdf."
    )

    assert data["address"] == "123 Jurong West"
    assert data["rent"] == 2000
    assert data["contract_path"] == "data/sample_contract.pdf"
    assert missing_required_fields(data) == []


def test_extracts_bedrooms_and_dollar_rent():
    data = extract_rental_info_from_query(
        "Review property at 50 Clementi Ave 3, 2 bedrooms, $3,200, contract docs/ta.pdf"
    )

    assert data["address"] == "50 Clementi Ave 3"
    assert data["bedrooms"] == 2
    assert data["rent"] == 3200
    assert data["contract_path"] == "docs/ta.pdf"


def test_reports_missing_after_partial_extraction():
    data = extract_rental_info_from_query("Check 123 Jurong West with rent 2000")

    assert data["address"] == "123 Jurong West"
    assert data["rent"] == 2000
    assert missing_required_fields(data) == ["contract_path"]


def test_parses_model_extraction_json_fence():
    data = parse_model_extraction(
        """```json
        {"address": "123 Jurong West", "rent": "2000", "contract_path": "data/sample_contract.pdf", "bedrooms": 2}
        ```"""
    )

    assert data == {
        "address": "123 Jurong West",
        "rent": 2000.0,
        "contract_path": "data/sample_contract.pdf",
        "bedrooms": 2,
    }
