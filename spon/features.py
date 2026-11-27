"""
features.py - STEP 3: FEATURES.  Compare the customer with the watchlist person and turn
each comparison into a simple column (a "feature") that a rule or a model can use later.

No decisions are made here - this only describes how alike / different the two people are.
For alerts where 2+ different customers fit (ambiguous), each feature is worked out for every
candidate; if they all give the same value we keep it, otherwise the value is "mixed".

Input : clean.jsonl (from clean.py) + practice_labels.jsonl (answers for 50 hits)
Output: features.csv (one row per hit)
Run:  python -m spon features --data DIR
"""
import csv
import os
import difflib
import json

try:
    from .helpers import best_name_agreement, current_data_dir, name_parts, str_date, load_jsonl, output_path, set_data_dir
except ImportError:
    from helpers import best_name_agreement, current_data_dir, name_parts, str_date, load_jsonl, output_path, set_data_dir

IN_JSONL, OUT_CSV = "clean.jsonl", "features.csv"


# ---------------------------------------------------------------------------- date of birth rules
def dob_agrees(c, h):
    """POLICY principle 7: same birth year and every part both give (month, day) is equal."""
    if c[0] != h[0]:
        return False
    for a, b in zip(c[1:], h[1:]):
        if a is not None and b is not None and a != b:
            return False
    return True


def dob_contradicts(c, h):
    """POLICY principle 6: birth years more than 1 apart, or same year but a different month (or day)."""
    if abs(c[0] - h[0]) > 1:
        return True
    if c[0] == h[0] and c[1] and h[1]:
        if c[1] != h[1]:
            return True
        if c[2] and h[2] and c[2] != h[2]:
            return True
    return False


def compare_dob(cust_dobs, hit_dobs):
    """Returns (status, year_gap).  status is one of:
    agree / conflict / close_but_unclear / missing_customer / missing_hit / missing_both"""
    if not cust_dobs and not hit_dobs:
        return "missing_both", None
    if not cust_dobs:
        return "missing_customer", None
    if not hit_dobs:
        return "missing_hit", None
    gap = min(abs(c[0] - h[0]) for c in cust_dobs for h in hit_dobs)
    if any(dob_agrees(c, h) for c in cust_dobs for h in hit_dobs):
        return "agree", gap
    # conflict only when EVERY birth date the hit gives is contradicted
    if all(dob_contradicts(c, h) for c in cust_dobs for h in hit_dobs):
        return "conflict", gap
    return "close_but_unclear", gap


# ---------------------------------------------------------------------------- one customer vs one hit
def name_similarity(names_a, names_b):
    """0..1 score: how alike the closest pair of names looks letter-by-letter (words sorted first)."""
    best = 0.0
    for a in names_a:
        for b in names_b:
            sa, sb = " ".join(sorted(name_parts(a))), " ".join(sorted(name_parts(b)))
            if sa and sb:
                best = max(best, difflib.SequenceMatcher(None, sa, sb).ratio())
    return round(best, 3)


def features_for_person(p, hit, screened_at):
    f = {}
    company = hit["entity_type"] == "Company"
    f["type_mismatch"] = p["entity_type"] is not None and p["entity_type"] != hit["entity_type"]

    # --- names
    cust_names = [n["value"] for n in p["declared_names"]]
    latest = p.get("latest_check") or {}
    agree, parts, cn, hn = best_name_agreement(cust_names, hit["names"], company)
    f["name_agree_declared"] = agree
    f["name_matched_parts"] = parts
    f["name_similarity"] = name_similarity(cust_names + ([latest["name"]] if latest.get("name") else []), hit["names"])
    f["cust_name_real_parts"] = max((len(name_parts(n, company)) for n in cust_names), default=0)
    if latest.get("name"):
        f["name_agree_verified"] = best_name_agreement([latest["name"]], hit["names"], company)[0]
    else:
        f["name_agree_verified"] = "no_verified_name"

    # --- date of birth: verified (latest approved check) beats declared (bank record)
    if latest.get("dob"):
        cust_dobs, f["cust_dob_source"] = [str_date(latest["dob"])], latest["id"]
    else:
        ds = sorted({d["dob"] for d in p["declared_dobs"]})
        cust_dobs = [str_date(d) for d in ds]
        f["cust_dob_source"] = " ".join(sorted({d["source"] for d in p["declared_dobs"]}))
    hit_dobs = [str_date(b["dob"]) for b in hit["birth_dates"]]
    f["dob_status"], f["dob_year_gap"] = compare_dob(cust_dobs, hit_dobs)
    f["cust_dob"] = " | ".join(sorted({d for d in ([latest.get("dob")] if latest.get("dob") else [d["dob"] for d in p["declared_dobs"]]) if d}))

    # --- countries
    cset = sorted({c["country"] for c in p["countries"]})
    hset = sorted(set(hit["countries"]))
    f["cust_countries"] = " | ".join(cset)
    if not cset or not hset:
        f["country_status"] = "missing_customer" if not cset and hset else ("missing_hit" if cset and not hset else "missing_both")
    else:
        common = sorted(set(cset) & set(hset))
        f["country_status"] = "overlap" if common else "no_overlap"
    f["country_overlap"] = " | ".join(sorted(set(cset) & set(hset)))
    f["cust_lived_abroad_note"] = any(c["kind"].startswith("lived") for c in p["countries"])

    # --- time: was the customer under 16 at the earliest dated report? (or a company not yet set up)
    f["too_young_at_report"] = "unknown"
    rep = str_date(hit["earliest_report"]) if hit["earliest_report"] else None
    if rep and cust_dobs:
        b = min(cust_dobs)
        if company:
            f["too_young_at_report"] = tuple(x or 0 for x in b) > tuple(x or 0 for x in rep)  # set up after the report
        else:
            # the oldest the customer could have been at the report date
            max_age = rep[0] - b[0]
            if b[1] and rep[1] and (rep[1], rep[2] or 31) < (b[1], b[2] or 1):
                max_age -= 1
            f["too_young_at_report"] = max_age < 16
            f["cust_max_age_at_report"] = max_age

    # --- evidence on file
    f["has_approved_check"] = bool(p["approved_checks"])
    f["latest_check_id"] = latest.get("id", "")
    f["n_rejected_or_expired_checks"] = p["n_rejected_or_expired_checks"]
    f["n_person_records"] = len(p["record_ids"])
    return f


def consensus(values):
    vals = [json.dumps(v, sort_keys=True) for v in values]
    return values[0] if len(set(vals)) == 1 else "mixed"


# ---------------------------------------------------------------------------- run
def main(in_jsonl=None, out_csv=None, data_dir=None):
    if data_dir:
        set_data_dir(data_dir)
    in_path = IN_JSONL if in_jsonl is None else in_jsonl
    out_path = OUT_CSV if out_csv is None else out_csv
    label_file = os.path.join(current_data_dir(), "practice_labels.jsonl")
    if os.path.exists(label_file):
        labels = {l["hit_id"]: l for l in load_jsonl("practice_labels.jsonl")}
    else:
        labels = {}
        print("no practice_labels.jsonl — label columns left blank")
    rows = []
    with open(in_path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            hit = r["hit"]
            row = {
                "hit_id": r["hit_id"], "alert_id": r["alert_id"],
                "link_type": r["link_type"], "resolution": r["resolution"],
                "customer_found": r["n_candidate_persons"] > 0,
                "ambiguous_customer": r["n_candidate_persons"] > 1,
                "n_candidate_records": r["n_candidate_records"], "n_candidate_persons": r["n_candidate_persons"],
                "customer_record_id": r["customer_record_id"],
                "screened_name": r["screened"]["name"],
                "cust_name": r["persons"][0]["declared_names"][0]["value"] if r["persons"] and r["persons"][0]["declared_names"] else "",
                "hit_name": hit["names"][0] if hit["names"] else "",
                "hit_entity_type": hit["entity_type"], "hit_category": hit["category"], "match_score": hit["match_score"],
                "hit_dob": " | ".join(b["dob"] for b in hit["birth_dates"]),
                "hit_dob_source": ("search result" if hit["birth_dates"][0]["source"].startswith("SR-")
                                   else hit["birth_dates"][0]["source"]) if hit["birth_dates"] else "none",
                "hit_dob_search_ids": " ".join(sorted({b["source"] for b in hit["birth_dates"] if b["source"].startswith("SR-")})),
                "hit_countries": " | ".join(hit["countries"]),
                "hit_n_countries": len(hit["countries"]),
                "hit_earliest_report": hit["earliest_report"],
                "hit_deceased_before_screening": bool(hit["deceased_date"]) and hit["deceased_date"] < r["screened_at"],
                "n_relevant_search_results": len(hit["relevant_search_results"]),
            }
            per_person = [features_for_person(p, hit, r["screened_at"]) for p in r["persons"]]
            keys = sorted({k for f in per_person for k in f})
            for k in keys:
                row[k] = consensus([f.get(k, "") for f in per_person]) if per_person else ""
            lab = labels.get(r["hit_id"])
            row["label_decision"] = lab["decision"] if lab else ""
            row["label_reason_code"] = lab["reason_codes"][0] if lab else ""
            row["label_customer_ids"] = " ".join(lab["customer_record_ids"]) if lab else ""
            rows.append(row)

    cols = list(rows[0].keys())
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"{len(rows)} rows x {len(cols)} columns written to {out_path}")


def _cli(argv=None):
    import argparse
    import sys
    p = argparse.ArgumentParser(description="Step 3: comparison columns per hit")
    p.add_argument("--data", default=os.environ.get("SPON_DATA"))
    p.add_argument("--in", dest="in_jsonl", default=None)
    p.add_argument("--out", dest="out_csv", default=None)
    p.add_argument("--workdir", default=os.environ.get("SPON_OUT") or ".")
    args = p.parse_args(argv)
    if not args.data:
        sys.exit("Pass --data DIR or set SPON_DATA to the dev folder.")
    work = args.workdir
    in_jsonl = args.in_jsonl or output_path(work, "clean.jsonl")
    out_csv = args.out_csv or output_path(work, "features.csv")
    main(in_jsonl=in_jsonl, out_csv=out_csv, data_dir=args.data)


if __name__ == "__main__":
    _cli()
