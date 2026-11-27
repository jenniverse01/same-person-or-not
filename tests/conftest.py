"""Shared fixture: run the pipeline once on the synthetic dev folder."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "fixtures" / "dev"


@pytest.fixture(scope="session")
def data_dir():
    return DATA


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    work = tmp_path_factory.mktemp("spon")
    from spon.cli import run_pipeline

    run_pipeline(str(DATA), str(work))
    return work
