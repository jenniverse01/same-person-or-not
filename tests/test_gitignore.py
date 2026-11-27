"""Generated screening output stays untracked. The synthetic fixture does not."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ignored(rel):
    proc = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT, check=False)
    return proc.returncode == 0


def test_outputs_are_ignored_and_fixtures_are_not():
    assert _ignored("output/dev.jsonl")
    assert _ignored("joined.jsonl")
    assert _ignored("joined.csv")
    assert _ignored("clean.jsonl")
    assert _ignored("features.csv")
    assert _ignored("rules_decisions.csv")
    assert _ignored("overrides.json")
    assert _ignored("review.html")
    assert not _ignored("tests/fixtures/dev/hits.jsonl")
    assert not _ignored("tests/fixtures/dev/alerts.jsonl")
    assert not _ignored("tests/fixtures/dev/practice_labels.jsonl")
    assert not _ignored("tests/fixtures/dev/name_variants.json")
    assert not _ignored("spon/review_template.html")
