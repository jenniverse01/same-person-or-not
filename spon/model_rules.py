"""
model_rules.py - MODEL 1: a list of if-then rules written straight from POLICY.md.

How it thinks (in order, first rule that fires wins):
  1. No customer found                      -> REVIEW  (INSUFFICIENT_DATA)
  2. Look for a CONTRADICTION (POLICY 6)    -> DIFFERENT_ENTITY
       person vs company, died before screening, customer too young at the earliest report,
       birth dates clash, no shared country, verified legal name does not agree
       (but: name + DOB agree and only the country differs -> REVIEW, as POLICY 6 says)
  3. Look for AGREEMENT (POLICY 7)          -> SAME_ENTITY
       person: name + DOB agree (+ country = NAME_DOB_LOCATION_MATCH, else NAME_DOB_MATCH)
       company: name + country agree (NAME_LOCATION_MATCH)
  4. Anything else                          -> REVIEW  (INSUFFICIENT_DATA)
If 2+ different customers fit the alert, each one is decided; same answer for all -> keep it,
otherwise REVIEW (AMBIGUOUS_CUSTOMER_RECORD).

The practice labels are NOT read here: they are a held-out test set.
Input : clean.jsonl (features are recomputed per candidate customer with features.py's function)
Output: output/dev.jsonl (one line per hit, organisers' format) and rules_decisions.csv
Run:  python -m spon rules
"""
import csv
import json
import os

try:
    from .features import features_for_person
except ImportError:
    from features import features_for_person
try:
    from .helpers import name_parts, output_path
except ImportError:
    from helpers import name_parts, output_path

IN_JSONL = "clean.jsonl"
OUT_JSONL = os.path.join("output", "dev.jsonl")
OUT_CSV = "rules_decisions.csv"


def sorted_ids(ids):
    return sorted({i for i in ids if i})


def country_sources(person):
    """IDs of the records that tie the customer to their countries."""
    return [c["source"] for c in person["countries"]]


def dob_evidence(f):
    return f["cust_dob_source"].split()


def hit_dob_text(hit):
    ds = [b["dob"] for b in hit["birth_dates"]]
    return " or ".join(ds)


def hit_dob_where(hit):
    src = hit["birth_dates"][0]["source"] if hit["birth_dates"] else ""
    if src.startswith("SR-"):
        return "the hit's web search results put its birth year at"
    if src == "profile text":
        return "the hit's profile notes put its birth year at"
    return "the hit's listed date of birth is"


def hit_sr_ids(hit):
    return [b["source"] for b in hit["birth_dates"] if b["source"].startswith("SR-")]


def decide_person(person, hit, screened_at, hit_id):
    """Apply the rules to ONE candidate customer. Returns (decision, code, reason, evidence)."""
    f = features_for_person(person, hit, screened_at)
    recs = person["record_ids"]
    latest = person.get("latest_check") or {}
    company = hit["entity_type"] == "Company"
    hit_name = hit["names"][0] if hit["names"] else "the hit"
    cust_countries = f["cust_countries"].replace(" | ", ", ")
    hit_countries = ", ".join(sorted(hit["countries"]))

    # names: the verified legal name (latest approved ID check) outranks the bank record (POLICY 4)
    if latest.get("name"):
        name_ok = f["name_agree_verified"] is True
        name_usable = len(name_parts(latest["name"], company)) >= 2 or company
    else:
        name_ok = f["name_agree_declared"] is True
        name_usable = f["cust_name_real_parts"] >= 2 or company

    # ---------------- contradictions -> DIFFERENT_ENTITY
    if f["type_mismatch"]:
        return ("DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH",
                f"The customer is a {person['entity_type'].lower()} but the hit {hit_name} is a {hit['entity_type'].lower()}.",
                sorted_ids(recs))
    if hit["deceased_date"] and hit["deceased_date"] < screened_at:
        return ("DIFFERENT_ENTITY", "DECEASED",
                f"The hit's profile says {hit_name} died on {hit['deceased_date']}, before the customer was screened on {screened_at}.",
                sorted_ids(recs + [f"{hit_id}#deceased_date"]))
    if f["too_young_at_report"] is True:
        if company:
            why = f"The customer company was set up on {f['cust_dob']}, after the hit's earliest dated report on {hit['earliest_report']}."
        else:
            why = (f"The customer was born on {f['cust_dob']} ({f['cust_dob_source']}), so they were at most "
                   f"{f['cust_max_age_at_report']} at the hit's earliest dated report on {hit['earliest_report']}.")
        return ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY", why, sorted_ids(dob_evidence(f)))
    if f["dob_status"] == "conflict":
        return ("DIFFERENT_ENTITY", "DOB_MISMATCH",
                f"The customer's date of birth is {f['cust_dob']} ({f['cust_dob_source']}) but {hit_dob_where(hit)} {hit_dob_text(hit)}. "
                f"Every birth date the hit gives is contradicted.",
                sorted_ids(dob_evidence(f) + hit_sr_ids(hit)))
    if f["country_status"] == "no_overlap":
        if name_ok and f["dob_status"] == "agree":
            return ("REVIEW", "INSUFFICIENT_DATA",
                    f"The name and date of birth agree with {hit_name}, but the customer is linked to {cust_countries} "
                    f"and the hit to {hit_countries}. A country difference alone cannot clear a name and DOB match.",
                    sorted_ids(recs + dob_evidence(f)))
        return ("DIFFERENT_ENTITY", "LOCATION_MISMATCH",
                f"The customer is linked only to {cust_countries} but the hit is linked only to {hit_countries}.",
                sorted_ids(recs + country_sources(person)))
    if latest.get("name") and name_usable and f["name_agree_verified"] is False:
        return ("DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED",
                f"The customer's verified name is {latest['name']} ({latest['id']}), which does not agree with any of the hit's names, e.g. {hit_name}.",
                [latest["id"]])

    # ---------------- agreement -> SAME_ENTITY
    if name_ok and name_usable:
        if not company and f["dob_status"] == "agree":
            dob_txt = (f"The customer's date of birth {f['cust_dob']} ({f['cust_dob_source']}) agrees with the hit's {hit_dob_text(hit)}. "
                       f"The customer's name agrees with the hit's name {hit_name}.")
            ev = sorted_ids(recs + dob_evidence(f) + hit_sr_ids(hit))
            if f["country_status"] == "overlap":
                return ("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH",
                        dob_txt + f" Both are linked to {f['country_overlap'].replace(' | ', ', ')}.", ev)
            return ("SAME_ENTITY", "NAME_DOB_MATCH", dob_txt + " Nothing contradicts the match.", ev)
        if company and f["country_status"] == "overlap":
            return ("SAME_ENTITY", "NAME_LOCATION_MATCH",
                    f"The customer's name agrees with the hit's name {hit_name}, and both are linked to "
                    f"{f['country_overlap'].replace(' | ', ', ')}. Nothing contradicts the match.",
                    sorted_ids(recs + ([latest["id"]] if latest.get("id") else [])))

    # ---------------- nothing settles it -> REVIEW
    bits = []
    if f["country_status"] == "overlap":
        bits.append(f"Both the customer and the hit are linked to {f['country_overlap'].replace(' | ', ', ')}.")
    bits.append(f"The customer's name {'agrees' if name_ok else 'cannot be confirmed'} with the hit's name {hit_name}.")
    if f["dob_status"].startswith("missing"):
        bits.append("The date of birth cannot be compared, so the hit can be neither cleared nor confirmed.")
    else:
        bits.append("Nothing contradicts the hit, but there is not enough agreement to confirm it.")
    return ("REVIEW", "INSUFFICIENT_DATA", " ".join(bits),
            sorted_ids(recs + ([latest["id"]] if latest.get("id") else [])))


def decide_hit(r):
    hit = r["hit"]
    if not r["persons"]:
        return {"decision": "REVIEW", "reason_code": "INSUFFICIENT_DATA", "customer_record_id": None,
                "reason": "No customer record could be found for this alert, so the hit cannot be compared.",
                "evidence": []}
    results = [decide_person(p, hit, r["screened_at"], r["hit_id"]) for p in r["persons"]]
    if len(results) == 1:
        d, code, reason, ev = results[0]
        return {"decision": d, "reason_code": code, "customer_record_id": r["customer_record_id"],
                "reason": reason, "evidence": ev}
    # several different people fit the alert (POLICY 3)
    decisions = {x[0] for x in results}
    all_ids = sorted_ids(i for p in r["persons"] for i in p["record_ids"])
    if len(decisions) == 1:
        d, code, reason, ev = results[0]
        return {"decision": d, "reason_code": code, "customer_record_id": "AMBIGUOUS",
                "reason": f"{len(results)} different customers fit this alert and every one leads to the same answer. " + reason,
                "evidence": sorted_ids(all_ids + [e for x in results for e in x[3]])}
    return {"decision": "REVIEW", "reason_code": "AMBIGUOUS_CUSTOMER_RECORD", "customer_record_id": "AMBIGUOUS",
            "reason": f"{len(results)} different customers fit this alert ({', '.join(all_ids)}) and they lead to different answers, "
                      f"so a person must decide which one was screened.",
            "evidence": all_ids}


def main(in_jsonl=None, out_jsonl=None, out_csv=None):
    in_path = IN_JSONL if in_jsonl is None else in_jsonl
    out_json = OUT_JSONL if out_jsonl is None else out_jsonl
    out_csv_path = OUT_CSV if out_csv is None else out_csv
    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
    out = []
    with open(in_path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            ans = decide_hit(r)
            out.append({"hit_id": r["hit_id"], "alert_id": r["alert_id"], **ans})
    with open(out_json, "w", encoding="utf-8") as fh:
        for o in out:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    with open(out_csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["hit_id", "decision", "reason_code", "customer_record_id"])
        for o in out:
            w.writerow([o["hit_id"], o["decision"], o["reason_code"], o["customer_record_id"]])
    from collections import Counter
    print(f"{len(out)} decisions written to {out_json}")
    print("decisions:", dict(Counter(o["decision"] for o in out)))
    print("reason codes:", dict(Counter(o["reason_code"] for o in out)))


def _cli(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Rules model: POLICY.md -> output/dev.jsonl")
    p.add_argument("--in", dest="in_jsonl", default=None)
    p.add_argument("--workdir", default=os.environ.get("SPON_OUT") or ".")
    args = p.parse_args(argv)
    work = args.workdir
    in_jsonl = args.in_jsonl or output_path(work, "clean.jsonl")
    main(
        in_jsonl=in_jsonl,
        out_jsonl=output_path(work, os.path.join("output", "dev.jsonl")),
        out_csv=output_path(work, "rules_decisions.csv"),
    )


if __name__ == "__main__":
    _cli()
