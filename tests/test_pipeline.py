"""End-to-end rules on the synthetic fixture. No real screening data."""
import json

EXPECTED = {
    "H-1001": ("DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED", "CUS-1001"),
    "H-1002": ("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH", "CUS-2001"),
    "H-1003": ("REVIEW", "INSUFFICIENT_DATA", "CUS-3001"),
    "H-1004": ("DIFFERENT_ENTITY", "DOB_MISMATCH", "CUS-4001"),
    "H-1005": ("REVIEW", "INSUFFICIENT_DATA", "CUS-5001"),
    "H-1006": ("REVIEW", "INSUFFICIENT_DATA", None),
    "H-1007": ("SAME_ENTITY", "NAME_LOCATION_MATCH", "CUS-7001"),
    "H-1008": ("DIFFERENT_ENTITY", "LOCATION_MISMATCH", "CUS-8001"),
    "H-1009": ("DIFFERENT_ENTITY", "DECEASED", "CUS-9001"),
    "H-1010": ("REVIEW", "AMBIGUOUS_CUSTOMER_RECORD", "AMBIGUOUS"),
    "H-1011": ("DIFFERENT_ENTITY", "DOB_MISMATCH", "CUS-1001"),
}


def _rows(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_decisions_match_the_rules(workdir):
    rows = _rows(workdir / "output" / "dev.jsonl")
    assert [row["hit_id"] for row in rows] == list(EXPECTED)
    for row in rows:
        decision, code, customer = EXPECTED[row["hit_id"]]
        assert row["decision"] == decision
        assert row["reason_code"] == code
        assert row["customer_record_id"] == customer
        assert set(row) == {
            "hit_id",
            "alert_id",
            "decision",
            "reason_code",
            "customer_record_id",
            "reason",
            "evidence",
        }
        assert isinstance(row["evidence"], list)
        assert row["reason"]


def test_specific_evidence(workdir):
    by_id = {row["hit_id"]: row for row in _rows(workdir / "output" / "dev.jsonl")}
    assert by_id["H-1001"]["evidence"] == ["KYC-1001"]
    assert "Amara Boateng" in by_id["H-1001"]["reason"]
    assert by_id["H-1006"]["evidence"] == []
    assert "No customer record could be found" in by_id["H-1006"]["reason"]
    assert "country difference alone cannot clear" in by_id["H-1005"]["reason"]
    assert by_id["H-1009"]["evidence"] == ["CUS-9001", "H-1009#deceased_date"]


def test_same_input_same_output(workdir, data_dir, tmp_path):
    from spon.cli import run_pipeline

    other = tmp_path / "again"
    run_pipeline(str(data_dir), str(other))
    first = (workdir / "output" / "dev.jsonl").read_bytes()
    second = (other / "output" / "dev.jsonl").read_bytes()
    assert first == second


def test_features_carry_practice_labels(workdir):
    text = (workdir / "features.csv").read_text(encoding="utf-8")
    assert "label_decision" in text.splitlines()[0]
    assert "SAME_ENTITY" in text
    assert "H-1004" in text
