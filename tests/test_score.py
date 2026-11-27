"""score.py still reads COST from validate.py. The tree model is not in this repo."""
import subprocess
import sys

import pytest

COST = '''
COST = {
    "DIFFERENT_ENTITY": {"DIFFERENT_ENTITY": 0, "SAME_ENTITY": 3, "REVIEW": 3},
    "SAME_ENTITY": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 0, "REVIEW": 2},
    "REVIEW": {"DIFFERENT_ENTITY": 60, "SAME_ENTITY": 2, "REVIEW": 0},
}
'''


def test_score_uses_validate_py(data_dir, workdir, tmp_path):
    pytest.importorskip("pandas")
    folder = tmp_path / "screening"
    folder.mkdir()
    (folder / "validate.py").write_text(COST, encoding="utf-8")
    rules = (workdir / "rules_decisions.csv").read_text(encoding="utf-8").splitlines()
    header, *body = rules
    tree = ["hit_id,tree_decision"]
    for line in body:
        hit_id, decision, _rest = line.split(",", 2)
        tree.append(f"{hit_id},{decision}")
    (workdir / "tree_decisions.csv").write_text("\n".join(tree) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable, "-m", "spon", "score",
            "--data", str(data_dir),
            "--validate", str(folder),
            "--workdir", str(workdir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "RULES" in proc.stdout
    assert "TREE" in proc.stdout
    assert "unsafe clearances 1" in proc.stdout


def test_score_stops_without_the_tree(data_dir, workdir, tmp_path):
    pytest.importorskip("pandas")
    folder = tmp_path / "screening"
    folder.mkdir()
    (folder / "validate.py").write_text(COST, encoding="utf-8")
    missing = tmp_path / "no-tree"
    missing.mkdir()
    proc = subprocess.run(
        [
            sys.executable, "-m", "spon", "score",
            "--data", str(data_dir),
            "--validate", str(folder),
            "--workdir", str(workdir),
            "--tree", str(missing / "tree_decisions.csv"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "tree_decisions.csv" in proc.stderr + proc.stdout
