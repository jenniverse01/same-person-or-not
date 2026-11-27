"""The review page is built only from pipeline output and the synthetic fixture."""
import json
import os
import shutil
import subprocess
import urllib.request

import pytest

from spon.review import build_payload, is_safety_net, render_html, start_server

BANNED = (
    "Samuel Bernard",
    "Usman Bernard",
    "CUS-531107",
    "CUS-548476",
    "KYC-F80647",
    "H-328BAE",
    "A-6F3461",
    "Adewale",
    "samuel.bernard",
    "/Users/jennl",
    "/workspace/spon-data",
)


def _payload(data_dir, workdir):
    return build_payload(
        str(data_dir),
        str(workdir / "joined.jsonl"),
        str(workdir / "clean.jsonl"),
        str(workdir / "output" / "dev.jsonl"),
    )


def test_payload_tells_the_lina_story(data_dir, workdir):
    payload = _payload(data_dir, workdir)
    hit = next(item for item in payload["hits"] if item["hit_id"] == "H-1001")
    assert hit["list_name"] == "Lina Okonkwo"
    assert hit["decision"] == "DIFFERENT_ENTITY"
    assert hit["found_steps"] == [
        "email lina.okonkwo@example.com → customers",
        "screened details fit CUS-1001",
        "same phone and date of birth, or same document number → one person: CUS-1001, CUS-1002",
    ]
    assert hit["screened_line"] == (
        "Screened as Lina Okonkwo · Individual · DOB 1991-08-08 · no country · no city"
    )
    person = hit["persons"][0]
    assert person["records"] == ["CUS-1001", "CUS-1002"]
    assert person["names"] == ["Lina Okonkwo", "Lina Okonkwo"]
    assert person["verified_name"] == "Amara Boateng"
    assert person["dob_label"] == "verified"
    assert person["countries"] == [{"country": "Ghana", "sources": ["CUS-1002", "KYC-1001"]}]
    assert hit["watchlist"]["listing"] == "PEP · Individual · match score 96"
    assert hit["n_on_alert"] == 1
    assert hit["safety_net"] is False
    safety = [item["hit_id"] for item in payload["hits"] if item["safety_net"]]
    assert safety == ["H-1005"]
    assert is_safety_net("REVIEW", "A country difference alone cannot clear a name and DOB match.")
    assert is_safety_net("DIFFERENT_ENTITY", "country difference alone cannot clear") is False


def test_ambiguous_and_deceased(data_dir, workdir):
    payload = _payload(data_dir, workdir)
    amb = next(item for item in payload["hits"] if item["hit_id"] == "H-1010")
    assert amb["customer_record_id"] == "AMBIGUOUS"
    assert len(amb["persons"]) == 2
    assert amb["found_steps"][-1].startswith("2 different people fit")
    dead = next(item for item in payload["hits"] if item["hit_id"] == "H-1009")
    assert dead["watchlist"]["deceased"] == "2019-05-01"
    assert dead["watchlist"]["earliest_report"] == "2010-09-10"


def test_html_is_local_and_has_no_real_records(data_dir, workdir):
    html = render_html(_payload(data_dir, workdir))
    assert "Screening review" in html
    assert "Lina Okonkwo" in html
    assert "How the customer was found" in html
    assert "My override" in html
    assert "held by the safety net" in html
    assert "http://" not in html
    assert "https://" not in html
    for banned in BANNED:
        assert banned not in html
    start = html.index('type="application/json">') + len('type="application/json">')
    end = html.index("</script>", start)
    json.loads(html[start:end])


def test_overrides_round_trip(data_dir, workdir, tmp_path):
    html = render_html(_payload(data_dir, workdir))
    overrides = tmp_path / "overrides.json"
    ids = {"H-1001", "H-1004"}
    httpd, url = start_server(html, str(overrides), ids, port=0)
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            page = res.read().decode("utf-8")
        assert "Screening review" in page
        body = json.dumps(
            {"H-1001": {"decision": "REVIEW", "note": "Checked the passport again.", "updated": "2026-11-27T01:00:00"}}
        ).encode()
        req = urllib.request.Request(url + "overrides", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as res:
            assert res.status == 200
        saved = json.loads(overrides.read_text(encoding="utf-8"))
        assert saved["H-1001"]["decision"] == "REVIEW"
        assert saved["H-1001"]["note"] == "Checked the passport again."
        with urllib.request.urlopen(url + "overrides.json", timeout=5) as res:
            assert json.loads(res.read().decode())["H-1001"]["decision"] == "REVIEW"
        bad = urllib.request.Request(
            url + "overrides",
            data=b'{"H-1001": {"decision": "CLEAR", "note": ""}}',
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad, timeout=5)
        assert caught.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_browser_shows_the_queue(data_dir, workdir, tmp_path):
    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
    if not chrome:
        pytest.skip("chrome is not installed")
    html = render_html(_payload(data_dir, workdir))
    httpd, url = start_server(html, str(tmp_path / "overrides.json"), {"H-1001"}, port=0)
    # Headless Chrome prints the DOM and then often fails to exit. Kill it once
    # the page has been written, and judge the test by that DOM.
    proc = subprocess.Popen(
        [
            chrome,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--dump-dom",
            url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        try:
            stdout, _stderr = proc.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _stderr = proc.communicate()
    finally:
        httpd.shutdown()
        httpd.server_close()
    dom = stdout or ""
    assert "Screening review" in dom
    assert "Lina Okonkwo" in dom
    assert "Amara Boateng" in dom
    assert "NAME_MISMATCH_VERIFIED" in dom
    assert "5/6" in dom
    assert "1 unsafe clears" in dom
    assert "held by the safety net" in dom
    assert "Cleared" in dom
    assert "Same entity" in dom
