"""Build and serve the local screening-review page.

The page is one HTML file with the pipeline rows embedded in it. The server
binds to 127.0.0.1 only, so the decisions never leave the machine. Overrides
are written to a local overrides.json.
"""
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

_TEMPLATE = Path(__file__).with_name("review_template.html")
_TOKEN = "__SPON_PAYLOAD__"
_DECISIONS = ("DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW")
# The rules model holds a hit here instead of clearing it: name and date of
# birth agree, and only the country differs. See model_rules.decide_person.
_SAFETY = "country difference alone cannot clear"


def is_safety_net(decision, reason):
    return decision == "REVIEW" and _SAFETY in (reason or "")


def read_jsonl(path):
    if not path or not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def found_steps(joined):
    """Numbered 'how the customer was found' lines, from the join row."""
    if not joined:
        return []
    steps = []
    link = joined.get("link_type")
    value = joined.get("link_value")
    if link == "email":
        steps.append(f"email {value} → customers")
    elif link == "login_handle":
        steps.append(f"login {value} → customers")
    elif link == "account_ref":
        steps.append(f"account {value} → customers")
    else:
        steps.append("no account, login or email on the alert → name search")

    resolution = joined.get("resolution")
    fitting = list(joined.get("fitting_record_ids") or [])
    if resolution == "link_broken":
        steps.append("the link did not match a customer record")
    elif resolution == "linked_no_holder_fits":
        steps.append("no linked holder fit the screened details")
    elif not fitting:
        steps.append("no customer record fit the screened details")
    else:
        steps.append("screened details fit " + ", ".join(fitting))

    persons = joined.get("persons") or []
    if len(persons) == 1:
        ids = [r.get("record_id") for r in persons[0].get("records") or [] if r.get("record_id")]
        if len(ids) > 1:
            steps.append(
                "same phone and date of birth, or same document number → one person: " + ", ".join(ids)
            )
    elif len(persons) > 1:
        bits = []
        for person in persons:
            ids = [r.get("record_id") for r in person.get("records") or [] if r.get("record_id")]
            bits.append(", ".join(ids))
        steps.append(f"{len(persons)} different people fit: " + " · ".join(bits))
    return steps


def _screen_date(value):
    if not value:
        return ""
    text = str(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _screened_line(screened):
    if not screened:
        return ""
    name = screened.get("name") or "unknown"
    kind = screened.get("entity_type") or "unknown type"
    dob = screened.get("dob")
    dob_bit = f"DOB {dob}" if dob else "no date of birth"
    country = screened.get("country") or "no country"
    city = screened.get("city") or "no city"
    return f"Screened as {name} · {kind} · {dob_bit} · {country} · {city}"


def _hit_dob(birth_dates):
    if not birth_dates:
        return None
    order = []
    bucket = {}
    for item in birth_dates:
        src = item.get("source") or ""
        if src == "dobs field":
            label = "field"
        elif src == "profile text":
            label = "profile"
        elif str(src).startswith("SR-"):
            label = "web search"
        else:
            label = src or "record"
        if label not in bucket:
            bucket[label] = []
            order.append(label)
        dob = item.get("dob")
        if dob and dob not in bucket[label]:
            bucket[label].append(dob)
    parts = []
    for label in order:
        dates = bucket[label]
        if dates:
            parts.append(" or ".join(dates) + f" from {label}")
    return "; ".join(parts) or None


def _countries(entries):
    grouped = []
    index = {}
    for entry in entries or []:
        name = entry.get("country")
        if not name:
            continue
        if name not in index:
            index[name] = {"country": name, "sources": []}
            grouped.append(index[name])
        source = entry.get("source")
        if source and source not in index[name]["sources"]:
            index[name]["sources"].append(source)
    return grouped


def _person_view(joined_person, clean_person):
    records = []
    names = []
    if joined_person:
        for rec in joined_person.get("records") or []:
            if rec.get("record_id"):
                records.append(rec["record_id"])
            if rec.get("full_name"):
                names.append(rec["full_name"])
    clean_person = clean_person or {}
    if not records:
        records = list(clean_person.get("record_ids") or [])
    latest = clean_person.get("latest_check") or {}
    if latest.get("dob"):
        dob = latest.get("dob")
        dob_label = "verified"
        dob_ids = [latest["id"]] if latest.get("id") else []
    else:
        declared = [d for d in (clean_person.get("declared_dobs") or []) if d.get("dob")]
        dob = " or ".join(sorted({d["dob"] for d in declared})) if declared else None
        dob_label = "on record" if declared else ""
        dob_ids = sorted({d["source"] for d in declared if d.get("source")})
    return {
        "records": records,
        "names": names,
        "verified_name": latest.get("name") or None,
        "verified_name_id": latest.get("id") if latest.get("name") else None,
        "dob": dob or None,
        "dob_label": dob_label,
        "dob_ids": dob_ids,
        "countries": _countries(clean_person.get("countries")),
    }


def _listing(hit):
    category = hit.get("category") or "—"
    kind = hit.get("entity_type") or "—"
    score = hit.get("match_score")
    text = f"{category} · {kind}"
    if score is not None and score != "":
        text += f" · match score {score}"
    return text


def _index(rows):
    return {row.get("hit_id"): row for row in rows if row.get("hit_id")}


def _practice(label):
    if not label:
        return None
    codes = label.get("reason_codes") or []
    return {
        "decision": label.get("decision") or "",
        "reason_code": codes[0] if codes else "",
        "customer_record_ids": list(label.get("customer_record_ids") or []),
    }


def build_payload(data_dir, joined_path, clean_path, decisions_path):
    """Slim rows for the review page. Full profile text is not embedded."""
    decisions = read_jsonl(decisions_path)
    if not decisions:
        sys.exit(f"No decisions in {decisions_path}")
    joined = _index(read_jsonl(joined_path))
    cleaned = _index(read_jsonl(clean_path))
    labels = {}
    if data_dir and os.path.isdir(data_dir):
        labels = _index(read_jsonl(os.path.join(data_dir, "practice_labels.jsonl")))
    counts = {}
    for row in decisions:
        counts[row.get("alert_id")] = counts.get(row.get("alert_id"), 0) + 1

    hits = []
    for row in decisions:
        hit_id = row.get("hit_id")
        join_row = joined.get(hit_id) or {}
        clean_row = cleaned.get(hit_id) or {}
        clean_people = {p.get("person_id"): p for p in (clean_row.get("persons") or [])}
        persons = []
        for person in join_row.get("persons") or []:
            persons.append(_person_view(person, clean_people.get(person.get("person_id"))))
        if not persons:
            for person in clean_row.get("persons") or []:
                persons.append(_person_view(None, person))
        screened = clean_row.get("screened") or join_row.get("screened") or {}
        watch = clean_row.get("hit") or {}
        raw_hit = join_row.get("hit") or {}
        names = list(watch.get("names") or [])
        if not names and raw_hit.get("name"):
            names = [raw_hit["name"]]
        list_name = ""
        if persons and persons[0]["names"]:
            list_name = persons[0]["names"][0]
        if not list_name:
            list_name = screened.get("name") or (names[0] if names else hit_id)
        practice = _practice(labels.get(hit_id))
        evidence = list(row.get("evidence") or [])
        record_ids = [rid for person in persons for rid in person["records"]]
        extra_names = [n for person in persons for n in person["names"]]
        extra_names += [person["verified_name"] for person in persons if person.get("verified_name")]
        blob = " ".join(
            str(part)
            for part in [
                hit_id,
                row.get("alert_id"),
                row.get("reason_code"),
                row.get("decision"),
                row.get("customer_record_id"),
                list_name,
                screened.get("name"),
                watch.get("category"),
                " ".join(names),
                " ".join(extra_names),
                " ".join(record_ids),
                " ".join(evidence),
                " ".join(found_steps(join_row)),
            ]
            if part
        )
        hits.append(
            {
                "hit_id": hit_id,
                "alert_id": row.get("alert_id"),
                "decision": row.get("decision"),
                "reason_code": row.get("reason_code") or "",
                "customer_record_id": row.get("customer_record_id"),
                "reason": row.get("reason") or "",
                "evidence": evidence,
                "safety_net": is_safety_net(row.get("decision"), row.get("reason")),
                "list_name": list_name,
                "hit_name": names[0] if names else "",
                "category": watch.get("category") or "",
                "n_on_alert": counts.get(row.get("alert_id"), 1),
                "screened_on": _screen_date(clean_row.get("screened_at") or join_row.get("screened_at")),
                "found_steps": found_steps(join_row),
                "screened_line": _screened_line(screened),
                "persons": persons,
                "watchlist": {
                    "names": names,
                    "listing": _listing(watch) if watch else (raw_hit.get("entity_type") or "—"),
                    "dob": _hit_dob(watch.get("birth_dates")),
                    "countries": list(watch.get("countries") or []),
                    "earliest_report": watch.get("earliest_report") or None,
                    "deceased": watch.get("deceased_date") or None,
                },
                "practice": practice,
                "search": " ".join(blob.lower().split()),
            }
        )
    shown = data_dir if data_dir else "data folder not set"
    return {
        "meta": {
            "data_dir": shown,
            "built": time.strftime("%Y-%m-%d %H:%M"),
            "decisions": os.path.abspath(decisions_path) if decisions_path else "",
        },
        "hits": hits,
    }


def render_html(payload):
    template = _TEMPLATE.read_text(encoding="utf-8")
    if _TOKEN not in template:
        raise RuntimeError("review template is missing the payload slot")
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return template.replace(_TOKEN, blob)


def clean_overrides(obj, valid_ids):
    if not isinstance(obj, dict):
        raise ValueError("expected an object")
    if len(obj) > 20000:
        raise ValueError("too many overrides")
    cleaned = {}
    for key, value in obj.items():
        if not isinstance(key, str) or key not in valid_ids or len(key) > 80:
            continue
        if not isinstance(value, dict):
            raise ValueError("bad override")
        decision = value.get("decision")
        if decision not in _DECISIONS:
            raise ValueError("bad decision")
        note = value.get("note") or ""
        if not isinstance(note, str) or len(note) > 4000:
            raise ValueError("bad note")
        updated = value.get("updated")
        if not isinstance(updated, str) or len(updated) > 40:
            updated = time.strftime("%Y-%m-%dT%H:%M:%S")
        cleaned[key] = {"decision": decision, "note": note, "updated": updated}
    return cleaned


def _write_overrides(path, payload):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def make_handler(html, overrides_path, valid_ids):
    body = html.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            sys.stderr.write("review  " + (fmt % args) + "\n")

        def _send(self, code, content_type, payload):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", body)
                return
            if path == "/overrides.json":
                if os.path.exists(overrides_path):
                    with open(overrides_path, "rb") as fh:
                        data = fh.read()
                else:
                    data = b"{}\n"
                self._send(200, "application/json; charset=utf-8", data)
                return
            self._send(404, "text/plain; charset=utf-8", b"not found\n")

        def do_POST(self):
            path = urlparse(self.path).path
            if path != "/overrides":
                self._send(404, "text/plain; charset=utf-8", b"not found\n")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > 2_000_000:
                self._send(413, "text/plain; charset=utf-8", b"too large\n")
                return
            raw = self.rfile.read(length)
            try:
                obj = json.loads(raw.decode("utf-8"))
                cleaned = clean_overrides(obj, valid_ids)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send(400, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                return
            _write_overrides(overrides_path, cleaned)
            self._send(200, "application/json; charset=utf-8", b'{"ok":true}\n')

    return Handler


def start_server(html, overrides_path, valid_ids, port=0):
    """Listen on 127.0.0.1 and return (httpd, url). The caller stops httpd."""
    handler = make_handler(html, overrides_path, valid_ids)
    try:
        httpd = HTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        sys.exit(f"Could not listen on 127.0.0.1:{port} ({exc}). Try another --port.")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, bound = httpd.server_address
    return httpd, f"http://{host}:{bound}/"


def serve(html, overrides_path, valid_ids, port=8765, open_browser=False):
    httpd, url = start_server(html, overrides_path, valid_ids, port=port)
    print(f"Review UI  {url}")
    print("On this machine only. Nothing is uploaded. Ctrl+C to stop.")
    print(f"Overrides  {os.path.abspath(overrides_path)}")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        while True:
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.shutdown()
        httpd.server_close()
