"""
clean.py - STEP 2: CLEAN.  Make the facts from joined.jsonl comparable.

What "cleaning" means here:
  * Dates:     '05/03/1968', 'March 5, 1968', '5 March 1968' all become 1968-03-05.
               Partial dates stay partial: '1968' stays 1968 (we never invent the missing part).
  * Countries: 'GB', 'British', 'United Kingdom' all become 'United Kingdom'.
  * Names:     lower case, no accents, no brackets: 'MORILLO (AKA)' -> 'morillo'.
  * Free text: read the ID-check notes ("... verified ELENA LINDQVIST ... DOB 20 January 1996 ... passport from Spain")
               and the "lived and worked in Argentina from 2010 to 2020" notes;
               read the hit's profile text for a hidden date of birth ("aged 30 in November 1998" -> 1967 or 1968),
               and the web search results when the hit has no date of birth at all.
  * ID checks: keep only APPROVED ones (rejected / expired are not evidence) and find the most recent one.

Input : joined.jsonl (from join.py)
Output: clean.jsonl (full detail, used by features.py) and clean.csv (flat, for looking at)
Run:  python -m spon clean
"""
import csv
import json
import re

try:
    from .helpers import (parse_date, date_str, dates_in_text, norm_text, birth_info_from_text,
                         first_paragraph, dated_reports, ages_in_sentence, birth_years_from_age, output_path)
except ImportError:
    from helpers import (parse_date, date_str, dates_in_text, norm_text, birth_info_from_text,
                         first_paragraph, dated_reports, ages_in_sentence, birth_years_from_age, output_path)
try:
    from .countries import canonical_country, countries_in_text
except ImportError:
    from countries import canonical_country, countries_in_text

IN_JSONL, OUT_JSONL, OUT_CSV = "joined.jsonl", "clean.jsonl", "clean.csv"

# The phrase a web result must use to be about the same KIND of listing as the hit (POLICY principle 5)
LISTING_PHRASE = {
    "Sanctions": "a sanctioned individual",
    "PEP": "a politically exposed person",
    "Enforcement": "the subject of enforcement action",
    "Adverse Media": "named in adverse media",
    "SOE": "a state-owned enterprise official",
}
OTHER_LISTING = "named on a watchlist"
NOT_NAME_WORDS = {"ID", "DOB", "KYC", "AML", "UK", "US", "USA", "UAE", "EU"}


# ============================================================================ customer side
def parse_kyc_note(note):
    """An onboarding-team note that records an ID check, e.g.
    'Sumsub validated the identity of PHILIPPE MATHIEU (DOB 1971-11-04) on 2023-06-27, presenting a France national ID.'
    -> name 'PHILIPPE MATHIEU', dob (1971, 11, 4), document country 'France', check date 2023-06-27."""
    text = note.get("text") or ""
    # the verified name is written in CAPITALS
    tokens = re.findall(r"[^\W\d_][^\W\d_'\-]*(?:['\-][^\W\d_]+)*", text)
    name, run = None, []
    for t in tokens + ["end"]:
        if t.isupper() and len(t) > 1 and t not in NOT_NAME_WORDS:
            run.append(t)
        else:
            if run and name is None:
                name = " ".join(run)
            run = []
    # the date of birth is the date that is NOT the check date (the check date = the note's created_at)
    created = parse_date(note.get("created_at"))
    dates = [d for _, d in dates_in_text(text, "DMY") if d != created]
    dob = dates[0] if dates else None
    check_date = created
    # the document country: country words in the text, ignoring the person's name
    rest = text.replace(name, " ") if name else text
    ctry = countries_in_text(rest)
    return {"id": note["note_id"], "kind": "kyc_note", "date": date_str(check_date),
            "name": name, "dob": date_str(dob), "country": ctry[0] if ctry else None}


def residence_countries_from_note(note):
    """'Argentina is where the user lived and held a job during 2010 to 2020.' -> ['Argentina']"""
    text = note.get("text") or ""
    if re.search(r"\b(lived|living|resid|resident|home|based|employ|work)", text, re.IGNORECASE):
        return countries_in_text(text)
    return []


def clean_person(p):
    out = {"person_id": p["person_id"], "main_record": p["main_record"],
           "record_ids": [r["record_id"] for r in p["records"]],
           "entity_type": p["records"][0]["entity_type"] if p["records"] else None}

    # --- names written on the bank records (declared, not verified)
    names = []
    for r in p["records"]:
        for field in ("full_name", "preferred_name", "login_name"):
            if r.get(field):
                names.append({"value": r[field], "norm": norm_text(r[field]), "source": r["record_id"], "field": field})
    out["declared_names"] = names

    # --- declared dates of birth
    out["declared_dobs"] = [{"dob": date_str(parse_date(r["dob"], "DMY")), "raw": r["dob"], "source": r["record_id"]}
                            for r in p["records"] if parse_date(r.get("dob"), "DMY")]

    # --- countries tied to the customer (residence + nationality on every record)
    countries = []
    for r in p["records"]:
        for field in ("residence_country", "nationality"):
            c = canonical_country(r.get(field))
            if c:
                countries.append({"country": c, "source": r["record_id"], "kind": field})

    # --- identity checks: KYC provider checks + checks written up as notes. Approved only.
    checks, n_not_approved = [], 0
    for k in p["kyc_checks"]:
        if k.get("result") != "approved":
            n_not_approved += 1          # rejected / expired: not evidence
            continue
        checks.append({"id": k["check_id"], "kind": "kyc_check", "date": date_str(parse_date(k.get("checked_at"))),
                       "name": k.get("verified_name"), "dob": date_str(parse_date(k.get("verified_dob"), "DMY")),
                       "country": canonical_country(k.get("document_country"))})
    lived = []
    for n in p["notes"]:
        if n.get("channel") == "kyc":
            parsed = parse_kyc_note(n)
            if parsed["name"] or parsed["dob"]:
                checks.append(parsed)
        else:
            for c in residence_countries_from_note(n):
                lived.append({"country": c, "source": n["note_id"], "kind": "lived_there (note)"})
    checks.sort(key=lambda c: (c["date"] or "", c["id"]))
    out["approved_checks"] = checks
    out["n_rejected_or_expired_checks"] = n_not_approved
    latest = checks[-1] if checks else None
    out["latest_check"] = latest                       # "verified beats declared"
    for c in checks:
        if c["country"]:
            countries.append({"country": c["country"], "source": c["id"], "kind": "id_document"})
    countries += lived
    out["countries"] = countries
    return out


# ============================================================================ watchlist side
def hit_countries(h):
    """Countries tied to a hit: countries, nationality, citizenship, address (last part), place of birth."""
    out = []
    for field in ("countries", "nationality", "citizenship", "addresses"):
        for v in h.get(field) or []:
            c = canonical_country(v)
            if c and c not in out:
                out.append(c)
    if h.get("place_of_birth"):
        c = canonical_country(h["place_of_birth"])
        if c and c not in out:
            out.append(c)
    return out


def hit_names(h):
    names = [h.get("name"), h.get("best_matching_name")]
    if h.get("first_name") or h.get("last_name"):
        names.append(" ".join(x for x in (h.get("first_name"), h.get("middle_name"), h.get("last_name")) if x))
    names += h.get("aliases") or []
    uniq = []
    for n in names:
        if n and n not in uniq:
            uniq.append(n)
    return uniq


def listing_phrase(h):
    cat = h.get("primary_category") or ((h.get("categories") or [None])[0])
    return LISTING_PHRASE.get(cat, OTHER_LISTING)


def relevant_search_results(h, countries, results):
    """A web result is about THIS hit only if it uses the same listing phrase AND names a country tied to the hit."""
    phrase = listing_phrase(h)
    keep = []
    for s in results:
        snip = s.get("snippet") or ""
        if phrase in snip.lower() and set(countries_in_text(snip)) & set(countries):
            ages = ages_in_sentence(snip)
            ds = dates_in_text(snip)
            years = []
            if len(ages) == 1 and ds:
                years = birth_years_from_age(ages[0], ds[0][1][0])
            keep.append({"id": s["result_id"], "snippet": snip, "birth_years": years})
    return keep


def clean_hit(row):
    h = row["hit"]
    is_company = h.get("entity_type") == "Company"
    countries = hit_countries(h)
    births = []                                     # each: {"dob": "1968" / "1968-03-05", "source": ...}
    for d in h.get("dobs") or []:
        pd = parse_date(d, "AUTO")
        if pd:
            births.append({"dob": date_str(pd), "source": "dobs field"})
    para = first_paragraph(h.get("profile_notes"))
    text_sentences = []
    if not is_company:                              # companies: only the dobs field counts
        found, text_sentences = birth_info_from_text(para, "AUTO")
        for d in found:
            if not any(b["dob"] == date_str(d) for b in births):
                births.append({"dob": date_str(d), "source": "profile text"})
    sr = relevant_search_results(h, countries, row.get("search_results", []))
    if not births and not is_company:               # web search only when nothing else gives a DOB
        for s in sr:
            for y in s["birth_years"]:
                if not any(b["dob"] == str(y) for b in births):
                    births.append({"dob": str(y), "source": s["id"]})
    reports = dated_reports(h.get("profile_notes"))
    return {
        "hit_id": h["hit_id"], "entity_type": h.get("entity_type"), "names": hit_names(h),
        "names_norm": [norm_text(n) for n in hit_names(h)],
        "birth_dates": births, "dob_text_sentences": text_sentences,
        "countries": countries, "category": h.get("primary_category") or ((h.get("categories") or [None])[0]),
        "listing_phrase": listing_phrase(h),
        "relevant_search_results": [{"id": s["id"], "birth_years": s["birth_years"]} for s in sr],
        "earliest_report": date_str(reports[0]) if reports else "",
        "deceased_date": date_str(parse_date(h.get("deceased_date"), "AUTO")),
        "life_status": h.get("life_status"),
        "match_score": h.get("match_score"),
    }


# ============================================================================ run

def run(in_jsonl=None, out_dir="."):
    """Clean joined.jsonl into comparable fields. Same work as the original clean.py."""
    IN_JSONL = in_jsonl or output_path(out_dir, "joined.jsonl")
    OUT_JSONL = output_path(out_dir, "clean.jsonl")
    OUT_CSV = output_path(out_dir, "clean.csv")
    rows_out = []
    with open(IN_JSONL, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            s = row["screened"]
            rows_out.append({
                "hit_id": row["hit_id"], "alert_id": row["alert_id"], "screened_at": row["screened_at"],
                "screened": {"name": s.get("name"), "norm_name": norm_text(s.get("name")), "entity_type": s.get("entity_type"),
                             "dob": date_str(parse_date(s.get("dob"), "DMY")), "country": canonical_country(s.get("country")),
                             "city": s.get("city")},
                "link_type": row["link_type"], "resolution": row["resolution"],
                "n_candidate_records": row["n_candidate_records"], "n_candidate_persons": row["n_candidate_persons"],
                "customer_record_id": row["customer_record_id"],
                "persons": [clean_person(p) for p in row["persons"]],
                "hit": clean_hit(row),
            })

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in rows_out:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


    def j(xs):
        return " | ".join(str(x) for x in xs if x not in (None, ""))


    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hit_id", "customer_record_id", "cust_names_clean", "cust_dobs_declared", "cust_latest_check",
                    "cust_verified_name", "cust_verified_dob", "cust_countries",
                    "hit_names_clean", "hit_birth_dates", "hit_countries", "hit_earliest_report", "hit_deceased_date"])
        for r in rows_out:
            p = r["persons"][0] if r["persons"] else None
            lc = (p or {}).get("latest_check") or {}
            w.writerow([r["hit_id"], r["customer_record_id"],
                        j(sorted({n["norm"] for n in p["declared_names"]})) if p else "",
                        j(sorted({d["dob"] for d in p["declared_dobs"]})) if p else "",
                        lc.get("id"), lc.get("name"), lc.get("dob"),
                        j(sorted({c["country"] for c in p["countries"]})) if p else "",
                        j(r["hit"]["names_norm"]), j(f'{b["dob"]} ({b["source"]})' for b in r["hit"]["birth_dates"]),
                        j(r["hit"]["countries"]), r["hit"]["earliest_report"], r["hit"]["deceased_date"]])

    print(f"{len(rows_out)} rows written to {OUT_JSONL} and {OUT_CSV}")
    src = {}
    for r in rows_out:
        k = r["hit"]["birth_dates"][0]["source"] if r["hit"]["birth_dates"] else "none"
        k = "search result" if k.startswith("SR-") else k
        src[k] = src.get(k, 0) + 1
    print("where the hit's date of birth came from:", src)


def main(argv=None):
    import argparse
    import os
    p = argparse.ArgumentParser(description="Step 2: make facts comparable")
    p.add_argument("--in", dest="in_jsonl", default=None)
    p.add_argument("--out", default=os.environ.get("SPON_OUT") or ".")
    args = p.parse_args(argv)
    run(in_jsonl=args.in_jsonl, out_dir=args.out)


if __name__ == "__main__":
    main()
