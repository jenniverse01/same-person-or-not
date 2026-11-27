"""
join.py - STEP 1: GATHER.  Turn the 9 separate files into ONE row per hit.

For every hit we answer two questions and put the answers side by side:
  * Who is the bank's customer?   (alert -> account / login / email / name search -> customer records
                                   -> the person's other records -> ID checks -> support notes)
  * Who is the watchlist person?  (the hit's own fields + web search results for the same name)

Nothing is decided here.  We only collect the raw facts and remember WHERE each fact came from
(its record ID), so later steps can cite it.

Outputs
  joined.jsonl   full detail, one JSON object per hit (used by clean.py)
  joined.csv     the same rows flattened, easy to open in Excel

Run:  python -m spon join --data DIR
"""
import collections
import csv
import json

try:
    from .helpers import (load_jsonl, names_agree, name_parts, parse_date, norm_text,
                         digits_only, parts_match, set_data_dir, output_path)
except ImportError:
    from helpers import (load_jsonl, names_agree, name_parts, parse_date, norm_text,
                         digits_only, parts_match, set_data_dir, output_path)
try:
    from .countries import canonical_country
except ImportError:
    from countries import canonical_country


def run(data_dir=None, out_dir="."):
    """Gather one row per hit. Same work as running the original join.py."""
    if data_dir:
        set_data_dir(data_dir)
    OUT_JSONL = output_path(out_dir, "joined.jsonl")
    OUT_CSV = output_path(out_dir, "joined.csv")

    # ----------------------------------------------------------------------------- 1. load every file
    print("loading files ...")
    alerts = load_jsonl("alerts.jsonl")
    hits = load_jsonl("hits.jsonl")
    customers = load_jsonl("customers.jsonl")
    accounts = load_jsonl("accounts.jsonl")
    onboarding = load_jsonl("onboarding.jsonl")
    kyc_checks = load_jsonl("kyc_checks.jsonl")
    notes = load_jsonl("notes.jsonl")
    search_results = load_jsonl("search_results.jsonl")

    alert_by_id = {a["alert_id"]: a for a in alerts}
    cust_by_id = {c["record_id"]: c for c in customers}

    # lookup tables ("indexes") so we can jump from one file to the next quickly
    holders_of_account = collections.defaultdict(list)       # account_id   -> [customer_id, ...]
    accounts_of_customer = collections.defaultdict(list)     # customer_id  -> [account row, ...]
    customers_of_login = collections.defaultdict(list)       # login handle -> [customer_id, ...]
    for a in accounts:
        holders_of_account[a["account_id"]].append(a["customer_id"])
        accounts_of_customer[a["customer_id"]].append(a)
        if a.get("login_handle"):
            customers_of_login[a["login_handle"].lower()].append(a["customer_id"])

    customers_of_email = collections.defaultdict(list)       # email -> [customer_id, ...]
    for c in customers:
        if c.get("email"):
            customers_of_email[c["email"].lower()].append(c["record_id"])

    onboarding_by_account = collections.defaultdict(list)     # account_id  -> [onboarding row]
    onboarding_by_customer = collections.defaultdict(list)    # customer_id -> [onboarding row]
    for o in onboarding:
        onboarding_by_account[o["account_id"]].append(o)
        onboarding_by_customer[o["customer_id"]].append(o)

    checks_by_applicant = collections.defaultdict(list)       # kyc applicant -> [check rows]
    for k in kyc_checks:
        checks_by_applicant[k["applicant_id"]].append(k)

    notes_by_email = collections.defaultdict(list)            # email -> [note rows]
    for n in notes:
        notes_by_email[(n.get("requester_email") or "").lower()].append(n)

    search_by_query = collections.defaultdict(list)           # 'clara moreau' (sorted words) -> [results]
    for s in search_results:
        search_by_query[" ".join(sorted(norm_text(s["query"]).split()))].append(s)


    # ----------------------------------------------------------------------------- 2. "one person, one picture"
    # POLICY principle 3: records that share a phone AND the same full date of birth are one person;
    # so are records whose APPROVED ID checks carry the same document number. Linked records chain together.
    print("grouping customer records into people ...")
    parent = {c["record_id"]: c["record_id"] for c in customers}


    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x


    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)   # deterministic: smaller ID becomes the group name


    def checks_of_customer(cid):
        """All KYC checks for one customer record: customer -> onboarding (by customer or account) -> applicant -> checks."""
        apps = []
        for o in onboarding_by_customer.get(cid, []):
            apps.append(o["kyc_applicant_id"])
        for acc in accounts_of_customer.get(cid, []):
            for o in onboarding_by_account.get(acc["account_id"], []):
                # joint accounts: only the onboarding row of THIS holder, never the co-holder's ID check
                if o.get("customer_id") in (None, cid):
                    apps.append(o["kyc_applicant_id"])
        out, seen = [], set()
        for app in apps:
            for k in checks_by_applicant.get(app, []):
                if k["check_id"] not in seen:
                    seen.add(k["check_id"])
                    out.append(k)
        return out


    # (a) same phone + same full date of birth
    by_phone_dob = collections.defaultdict(list)
    for c in customers:
        d = parse_date(c.get("dob"))
        ph = digits_only(c.get("phone"))
        if ph and d and None not in d:
            by_phone_dob[(ph, d)].append(c["record_id"])
    for group in by_phone_dob.values():
        for other in group[1:]:
            union(group[0], other)

    # (b) same document number on approved checks
    by_document = collections.defaultdict(set)
    for c in customers:
        for k in checks_of_customer(c["record_id"]):
            if k.get("result") == "approved" and k.get("document_number"):
                by_document[k["document_number"].strip().upper()].add(c["record_id"])
    for group in by_document.values():
        group = sorted(group)
        for other in group[1:]:
            union(group[0], other)

    members = collections.defaultdict(list)                   # person id -> [record ids]
    for rid in sorted(parent):
        members[find(rid)].append(rid)


    def person_records(rid):
        return members[find(rid)]


    # ----------------------------------------------------------------------------- 3. does a record fit what was screened?
    def record_fits(rec, screened):
        """POLICY principle 2: the name agrees, the DOB is equal in every part both give,
        the screened country is the residence or nationality, the screened city is in city/address.
        A field missing on either side does not count against the record (unknown stays unknown)."""
        is_company = screened.get("entity_type") == "Company"
        rec_names = [rec.get("full_name"), rec.get("preferred_name"), rec.get("login_name")]
        if not any(names_agree(screened["name"], n, is_company)[0] for n in rec_names if n):
            return False
        sd, rd = parse_date(screened.get("dob")), parse_date(rec.get("dob"))
        if sd and rd:
            for a, b in zip(sd, rd):
                if a is not None and b is not None and a != b:
                    return False
        if screened.get("country"):
            sc = canonical_country(screened["country"])
            rc = {canonical_country(rec.get("residence_country")), canonical_country(rec.get("nationality"))} - {None}
            if sc and rc and sc not in rc:
                return False
        if screened.get("city"):
            city = norm_text(screened["city"].split(",")[0])
            where = norm_text(rec.get("city")) + " " + norm_text(rec.get("address"))
            if city and where.strip() and city not in where:
                return False
        return True


    # name-part index for searching 72k records quickly: part -> record ids
    part_index = collections.defaultdict(set)
    for c in customers:
        for n in (c.get("full_name"), c.get("preferred_name"), c.get("login_name")):
            for p in name_parts(n, c.get("entity_type") == "Company"):
                part_index[p].add(c["record_id"])
    vocab_by_len = collections.defaultdict(list)
    for p in part_index:
        vocab_by_len[len(p)].append(p)


    def search_customers(screened):
        """No link on the alert: look for records whose name is close, then keep those that fit."""
        candidates = set()
        for sp in name_parts(screened["name"], screened.get("entity_type") == "Company"):
            for L in range(len(sp) - 2, len(sp) + 3):
                for vp in vocab_by_len.get(L, []):
                    if parts_match(sp, vp):
                        candidates |= part_index[vp]
        return sorted(r for r in candidates if record_fits(cust_by_id[r], screened))


    # ----------------------------------------------------------------------------- 4. resolve each alert to people
    def resolve_alert(alert):
        """Returns (link_type, link_value, linked_record_ids, fitting_record_ids, persons, method)."""
        screened = alert["customer"]
        if alert.get("account_ref"):
            link_type, value = "account_ref", alert["account_ref"]
            linked = sorted(set(holders_of_account.get(value, [])))
        elif alert.get("login_handle"):
            link_type, value = "login_handle", alert["login_handle"]
            linked = sorted(set(customers_of_login.get(value.lower(), [])))
        elif alert.get("email"):
            link_type, value = "email", alert["email"]
            linked = sorted(set(customers_of_email.get(value.lower(), [])))
        else:
            link_type, value, linked = "none", None, []

        if link_type != "none":
            linked_people = sorted({find(r) for r in linked})
            if len(linked_people) <= 1:
                fitting, method = linked, ("linked" if linked else "link_broken")
            else:
                # e.g. a joint account: the screened name / DOB pick the holder
                fitting = [r for r in linked if record_fits(cust_by_id[r], screened)]
                method = "linked_picked_by_screened_details"
                if not fitting:
                    fitting, method = linked, "linked_no_holder_fits"
        else:
            fitting = search_customers(screened)
            method = "name_search"
        persons = []
        for pid in sorted({find(r) for r in fitting}):
            main = sorted(r for r in fitting if find(r) == pid)[0]  # the record we reached first
            persons.append({"person_id": pid, "main_record": main, "records": members[pid]})
        return link_type, value, linked, fitting, persons, method


    # ----------------------------------------------------------------------------- 5. gather each person's facts
    def gather_person(person):
        """Collect everything the bank knows about one person, each fact with its source ID."""
        recs = [cust_by_id[r] for r in person["records"]]
        accs, checks, person_notes, emails = [], [], [], []
        for r in recs:
            accs += [a["account_id"] for a in accounts_of_customer.get(r["record_id"], [])]
            checks += checks_of_customer(r["record_id"])
            if r.get("email") and r["email"].lower() not in emails:
                emails.append(r["email"].lower())
        for e in emails:
            person_notes += notes_by_email.get(e, [])
        keep = ("record_id", "entity_type", "full_name", "preferred_name", "login_name", "dob",
                "nationality", "residence_country", "city", "address", "email", "phone", "status", "onboarded_at")
        return {
            "person_id": person["person_id"],
            "main_record": person["main_record"],
            "records": [{k: r.get(k) for k in keep} for r in recs],
            "account_ids": sorted(set(accs)),
            "kyc_checks": sorted(checks, key=lambda k: (k.get("checked_at") or "", k["check_id"])),
            "notes": sorted(person_notes, key=lambda n: (n.get("created_at") or "", n["note_id"])),
        }


    # ----------------------------------------------------------------------------- 6. the watchlist side
    def hit_search_results(hit):
        """Web results whose query is the same words as one of the hit's names (relevance is judged in clean.py)."""
        names = [hit.get("name")] + [a for a in hit.get("aliases", [])]
        keys = {" ".join(sorted(norm_text(n).split())) for n in names if n}
        out = []
        for k in sorted(keys):
            out += search_by_query.get(k, [])
        return out


    # ----------------------------------------------------------------------------- 7. build one row per hit
    print("joining hits ...")
    rows = []
    resolved_cache = {}
    for hit in sorted(hits, key=lambda h: h["hit_id"]):
        alert = alert_by_id[hit["alert_id"]]
        if alert["alert_id"] not in resolved_cache:
            resolved_cache[alert["alert_id"]] = resolve_alert(alert)
        link_type, value, linked, fitting, persons, method = resolved_cache[alert["alert_id"]]
        if not persons:
            chosen = None
        elif len(persons) == 1:
            chosen = persons[0]["main_record"]
        else:
            chosen = "AMBIGUOUS"
        rows.append({
            "hit_id": hit["hit_id"],
            "alert_id": alert["alert_id"],
            "screened_at": alert.get("screened_at"),
            "screened": alert["customer"],
            "link_type": link_type,
            "link_value": value,
            "linked_record_ids": linked,
            "fitting_record_ids": fitting,
            "resolution": method,
            "n_candidate_records": len(fitting),
            "n_candidate_persons": len(persons),
            "customer_record_id": chosen,
            "persons": [gather_person(p) for p in persons],
            "hit": hit,
            "search_results": hit_search_results(hit),
        })

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


    # flat CSV for eyeballing: customer columns (first person) next to watchlist columns
    def j(xs):
        return " | ".join(str(x) for x in xs if x not in (None, ""))


    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hit_id", "alert_id", "link_type", "link_value", "resolution", "n_candidate_records",
                    "n_candidate_persons", "customer_record_id", "person_record_ids",
                    "screened_name", "screened_dob", "screened_country", "screened_city",
                    "cust_names", "cust_dobs", "cust_residence", "cust_nationality", "cust_cities",
                    "cust_account_ids", "cust_kyc_check_ids", "cust_note_ids",
                    "hit_entity_type", "hit_name", "hit_aliases", "hit_dobs", "hit_countries",
                    "hit_nationality", "hit_addresses", "hit_place_of_birth", "hit_categories",
                    "hit_deceased_date", "hit_profile_first_200", "search_result_ids"])
        for r in rows:
            p = r["persons"][0] if r["persons"] else {"records": [], "account_ids": [], "kyc_checks": [], "notes": []}
            recs, h, s = p["records"], r["hit"], r["screened"]
            w.writerow([
                r["hit_id"], r["alert_id"], r["link_type"], r["link_value"], r["resolution"],
                r["n_candidate_records"], r["n_candidate_persons"], r["customer_record_id"],
                j(x["record_id"] for x in recs),
                s.get("name"), s.get("dob"), s.get("country"), s.get("city"),
                j(sorted({x["full_name"] for x in recs if x["full_name"]})),
                j(sorted({x["dob"] for x in recs if x["dob"]})),
                j(sorted({x["residence_country"] for x in recs if x["residence_country"]})),
                j(sorted({x["nationality"] for x in recs if x["nationality"]})),
                j(sorted({x["city"] for x in recs if x["city"]})),
                j(p["account_ids"]), j(k["check_id"] for k in p["kyc_checks"]), j(n["note_id"] for n in p["notes"]),
                h.get("entity_type"), h.get("name"), j(h.get("aliases", [])), j(h.get("dobs", [])),
                j(h.get("countries", [])), j(h.get("nationality", [])), j(h.get("addresses", [])),
                h.get("place_of_birth"), j(h.get("categories", [])), h.get("deceased_date"),
                (h.get("profile_notes") or "")[:200].replace("\n", " "),
                j(x["result_id"] for x in r["search_results"]),
            ])

    # ----------------------------------------------------------------------------- 8. quick summary
    c = collections.Counter(r["resolution"] for r in rows)
    print(f"{len(rows)} hit rows written to {OUT_JSONL} and {OUT_CSV}")
    print("how the customer was found:", dict(c))
    print("hits with exactly one customer:", sum(r["n_candidate_persons"] == 1 for r in rows))
    print("hits with no customer found:   ", sum(r["n_candidate_persons"] == 0 for r in rows))
    print("hits with 2+ possible people:  ", sum(r["n_candidate_persons"] > 1 for r in rows))


def main(argv=None):
    import argparse
    import os
    import sys
    p = argparse.ArgumentParser(description="Step 1: one row per hit")
    p.add_argument("--data", default=os.environ.get("SPON_DATA"))
    p.add_argument("--out", default=os.environ.get("SPON_OUT") or ".")
    args = p.parse_args(argv)
    if not args.data:
        sys.exit("Pass --data DIR or set SPON_DATA to the dev folder.")
    run(data_dir=args.data, out_dir=args.out)


if __name__ == "__main__":
    main()
