"""
helpers.py - small cleaning tools shared by join.py, clean.py and features.py.

  * load_jsonl / load_dataset ... read the data files
  * norm_text / name_parts ...... make names comparable (case, accents, brackets, placeholders)
  * names_agree ................. the name rule from POLICY.md principle 8
  * parse_date .................. turn the many date formats into (year, month, day)
  * birth_years_from_text ....... find a date of birth hidden in a sentence ("aged 30 in November 1998")
Everything here is deterministic: same input -> same output.
The dev folder is SPON_DATA or the --data argument (default /workspace/spon-data/screening/dev).
"""
import json
import os
import re
import unicodedata

# ----------------------------------------------------------------------------- loading

DATA_DIR = os.environ.get("SPON_DATA", "/workspace/spon-data/screening/dev")


def load_jsonl(name, data_dir=None):
    """Read one .jsonl file into a list of dicts (one dict per line)."""
    if data_dir is None:
        data_dir = DATA_DIR
    with open(os.path.join(data_dir, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ----------------------------------------------------------------------------- text & names

def norm_text(text):
    """Lowercase, remove accents, remove anything in brackets, punctuation -> space."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\(.*?\)|\[.*?\]|\{.*?\}", " ", text)     # drop "(AKA)", "[PEP]" ...
    text = text.lower().replace("'", "").replace("\u2019", "")
    text = re.sub(r"[^\w\s]|_", " ", text)                    # punctuation -> space
    return re.sub(r"\s+", " ", text).strip()


# Placeholders are not real name parts (POLICY principle 8).
PLACEHOLDERS = {"na", "n", "a", "test", "unknown", "xxx", "none", "null", "nil", "tbc", "tba",
                "dummy", "noname", "fnu", "lnu", "nn", "xx", "x"}


def load_name_variants(data_dir=None):
    """Returns (part -> group number) for name variants, and the set of company legal forms."""
    if data_dir is None:
        data_dir = DATA_DIR
    with open(os.path.join(data_dir, "name_variants.json"), encoding="utf-8") as f:
        nv = json.load(f)
    group_of = {}
    for i, group in enumerate(nv.get("groups", [])):
        for part in group:
            group_of.setdefault(norm_text(part), set()).add(i)
    legal = set()
    for form in nv.get("company_legal_forms", nv.get("legal_forms", [])):
        legal.add(norm_text(form).replace(" ", ""))
        for p in norm_text(form).split():
            legal.add(p)
    return group_of, legal


def set_data_dir(path):
    """Point later reads at this dev folder (the directory that contains hits.jsonl)."""
    global DATA_DIR, VARIANT_GROUP, LEGAL_FORMS
    DATA_DIR = os.path.abspath(path)
    VARIANT_GROUP, LEGAL_FORMS = load_name_variants(DATA_DIR)
    return DATA_DIR


def current_data_dir():
    """The dev folder set_data_dir last chose, or SPON_DATA / the built-in default."""
    return DATA_DIR


def output_path(directory, name):
    """A path inside the working directory. '.' stays a plain relative name, as the scripts wrote it."""
    directory = directory or "."
    path = os.path.normpath(os.path.join(directory, name))
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    return path


try:
    VARIANT_GROUP, LEGAL_FORMS = load_name_variants()
except FileNotFoundError:
    # The dev folder is passed in at run time. Importing the package must not require it.
    VARIANT_GROUP, LEGAL_FORMS = {}, set()


def name_parts(name, is_company=False):
    """'Velasco MORILLO, Elvira (AKA)' -> ['velasco', 'morillo', 'elvira'].
    Drops single letters (initials), placeholders, digits, repeats, and company legal forms."""
    parts = []
    for p in norm_text(name).split():
        if len(p) < 2 or p.isdigit() or any(ch.isdigit() for ch in p) or p in PLACEHOLDERS:
            continue
        if is_company and p in LEGAL_FORMS:
            continue
        if p not in parts:
            parts.append(p)
    return parts


def edit_distance(a, b):
    """Classic Levenshtein distance (add / remove / change one letter = 1 edit)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def parts_match(a, b):
    """Two name parts match: identical, listed as variants, or a small typo (POLICY principle 8)."""
    if a == b:
        return True
    if VARIANT_GROUP.get(a, set()) & VARIANT_GROUP.get(b, set()):
        return True
    shorter = min(len(a), len(b))
    if shorter < 4:
        return False
    allowed = 1 if shorter <= 6 else 2
    if abs(len(a) - len(b)) > allowed:
        return False
    return edit_distance(a, b) <= allowed


def count_matching_parts(parts_a, parts_b):
    """How many parts of name A find a partner in name B (each part used once).
    Also handles 'abdulsalam' vs 'abdul salam' (written together or apart).
    Returns (matched_in_a, matched_in_b) counts."""
    used_b = set()
    matched_a = 0
    # 1) single part to single part
    leftover_a = []
    for pa in parts_a:
        hit = next((j for j, pb in enumerate(parts_b) if j not in used_b and parts_match(pa, pb)), None)
        if hit is None:
            leftover_a.append(pa)
        else:
            used_b.add(hit)
            matched_a += 1
    # 2) one part in A equals two neighbouring parts in B joined (or the other way round)
    for pa in list(leftover_a):
        for j in range(len(parts_b) - 1):
            if j in used_b or j + 1 in used_b:
                continue
            if parts_match(pa, parts_b[j] + parts_b[j + 1]):
                used_b.update({j, j + 1})
                matched_a += 1
                leftover_a.remove(pa)
                break
    leftover_b = [pb for j, pb in enumerate(parts_b) if j not in used_b]
    for pb in list(leftover_b):
        for i in range(len(leftover_a) - 1):
            if parts_match(pb, leftover_a[i] + leftover_a[i + 1]):
                matched_a += 2
                used_b.add(parts_b.index(pb))
                leftover_a = leftover_a[:i] + leftover_a[i + 2:]
                break
    return matched_a, len(used_b)


def names_agree(name_a, name_b, company=False):
    """POLICY principle 8: names agree when at least two parts match,
    or every part of the shorter name matches.  Returns (agree: bool, matched_parts: int)."""
    pa, pb = name_parts(name_a, company), name_parts(name_b, company)
    if not pa or not pb:
        return False, 0
    ma, mb = count_matching_parts(pa, pb)
    matched = max(ma, mb)
    shorter_all = (ma == len(pa)) or (mb == len(pb))
    return (matched >= 2 or shorter_all), matched


def best_name_agreement(names_a, names_b, company=False):
    """Compare every name in list A with every name in list B.
    Returns (agree, best_matched_parts, name_a, name_b) for the best pair."""
    best = (False, 0, None, None)
    for a in names_a:
        for b in names_b:
            ok, m = names_agree(a, b, company)
            if (ok, m) > (best[0], best[1]):
                best = (ok, m, a, b)
    return best


# ----------------------------------------------------------------------------- dates

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
for _m, _i in list(MONTHS.items()):
    MONTHS[_m[:3]] = _i
MONTHS["sept"] = 9

_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def parse_date(text, slash="DMY"):
    """Turn a date written any common way into a (year, month, day) tuple.
    Missing parts are None:  '1968' -> (1968, None, None).  Unreadable -> None.
    slash='DMY' reads 05/03/1968 as 5 March (bank systems);  slash='MDY' as May 3 (US style);
    slash='AUTO' only trusts the day/month when one part is > 12, else keeps the year only."""
    if text is None:
        return None
    t = str(text).strip().lower().rstrip(".")
    if not t:
        return None
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", t)
    if m:
        return _ok(int(m[1]), m[2] and int(m[2]), m[3] and int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if slash == "MDY" or (slash == "AUTO" and b > 12):
            return _ok(y, a, b)
        if slash == "DMY" or (slash == "AUTO" and a > 12):
            return _ok(y, b, a)
        return _ok(y, None, None)                      # AUTO and both <= 12: day/month unknown
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? (?:of )?" + _MON + r",? (\d{4})", t)
    if m:
        return _ok(int(m[3]), MONTHS[m[2][:3]], int(m[1]))
    m = re.fullmatch(_MON + r" (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})", t)
    if m:
        return _ok(int(m[3]), MONTHS[m[1][:3]], int(m[2]))
    m = re.fullmatch(_MON + r",? (\d{4})", t)
    if m:
        return _ok(int(m[2]), MONTHS[m[1][:3]], None)
    return None


def _ok(y, mth, d):
    if not (1800 <= y <= 2100):
        return None
    if mth is not None and not 1 <= mth <= 12:
        return None
    if d is not None and not 1 <= d <= 31:
        return None
    return (y, mth, d)


# a regex that FINDS dates inside sentences
DATE_IN_TEXT = re.compile(
    r"\b(\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)? (?:of )?" + _MON + r",? \d{4}"
    r"|" + _MON + r" \d{1,2}(?:st|nd|rd|th)?,? \d{4}"
    r"|" + _MON + r",? \d{4})\b", re.IGNORECASE)


def dates_in_text(text, slash="DMY"):
    """Every date found in a sentence, as [(matched_text, (y, m, d)), ...]."""
    out = []
    for m in DATE_IN_TEXT.finditer(text or ""):
        d = parse_date(m.group(0), slash)
        if d:
            out.append((m.group(0), d))
    return out


def date_str(d):
    """(1968, 3, None) -> '1968-03' ; for printing / CSV."""
    if not d:
        return ""
    y, m, dd = d
    return f"{y:04d}" + (f"-{m:02d}" if m else "") + (f"-{dd:02d}" if (m and dd) else "")


def str_date(s):
    """Inverse of date_str: '1968-03' -> (1968, 3, None)."""
    return parse_date(s) if s else None


# Age phrases: "aged 30", "a 30-year-old", "was 42 years old", "at the age of 43", "then 37", "at 24", "Name, 36,"
AGE_PATTERNS = [
    r"\baged (\d{1,2})\b",
    r"\b(\d{1,2})[- ]years?[- ]old\b",
    r"\bage of (\d{1,2})\b",
    r"\bat age (\d{1,2})\b",
    r"\b(\d{1,2}) years of age\b",
    r"\bthen (\d{1,2})\b",
    r"\bat (\d{1,2}),",
    r"\bwho was (\d{1,2})\b",
    r", (\d{1,2}),",
    r"\bage (\d{1,2})\b",
    r"\((\d{1,2})\)",
    # "X was 46.", "was 27 at the time", "was 25 when taken into custody" (the number must be followed by
    # an end of clause or an age word, so "was 28 years in prison" or "was 5 million" do not count)
    r"\b(?:was|is|were|turned|had turned) (\d{1,2})(?=\s*(?:[.,;)]|$|when\b|at\b|upon\b|during\b|in\b|years? old|years? of age))",
    r"\b(?:turned|reached|reaching) (\d{1,2})\b",
]


def ages_in_sentence(sentence):
    ages = []
    for pat in AGE_PATTERNS:
        for m in re.finditer(pat, sentence, re.IGNORECASE):
            a = int(m.group(1))
            if 10 <= a <= 110 and a not in ages:
                ages.append(a)
    return ages


def birth_years_from_age(age, event_year):
    """Someone aged 45 in March 2019 was born in 1973 or 1974 (POLICY principle 5)."""
    return [event_year - age - 1, event_year - age]


def birth_info_from_text(paragraph, slash="AUTO"):
    """Look for a date of birth written inside a hit's profile text.
    Returns (list of possible birth dates as (y,m,d) tuples, list of the sentences used)."""
    found, used = [], []
    if not paragraph:
        return found, used
    for sentence in re.split(r"(?<=[.!?])\s+|\n", paragraph):
        s = sentence.strip()
        if not s:
            continue
        # 1) explicit: "born on 17 July 1939", "born in 1952", "DOB: 6/20/1955", "Date of Birth: January 12, 1968"
        m = re.search(r"\b(?:born(?: on| in)?|DOB:?|date of birth:?|d\.o\.b\.?:?)\s+(.{4,25})", s, re.IGNORECASE)
        if m:
            tail = m.group(1)
            ds = dates_in_text(tail, slash)
            if ds:
                found.append(ds[0][1]); used.append(s); continue
            y = re.match(r"(\d{4})\b", tail)
            if y and _ok(int(y.group(1)), None, None):
                found.append((int(y.group(1)), None, None)); used.append(s); continue
        # 2) age at a date: "aged 30 ... in November 1998"
        ages = ages_in_sentence(s)
        if ages:
            ds = dates_in_text(s, slash)
            years = [d[0] for _, d in ds]
            if not years:
                years = [int(y) for y in re.findall(r"\b(1[89]\d\d|20\d\d)\b", s)]
            if years and len(ages) == 1:
                for by in birth_years_from_age(ages[0], years[0]):
                    found.append((by, None, None))
                used.append(s)
    # remove repeats, keep order
    uniq = []
    for d in found:
        if d not in uniq:
            uniq.append(d)
    return uniq, used


def first_paragraph(text):
    """The profile's first paragraph = text before the first blank line."""
    if not text:
        return ""
    return re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]


# "According to <source>; September 10, 2025: ..." - the ONLY wording that counts as a dated report.
DATED_REPORT = re.compile(r"^According to [^\n;]*; ((?i:" + _MON + r") \d{1,2}, \d{4}):", re.MULTILINE)


def dated_reports(profile_notes):
    """All report dates from lines of the exact form 'According to ...; Month D, YYYY: ...'."""
    out = []
    for m in DATED_REPORT.finditer(profile_notes or ""):
        d = parse_date(m.group(1))
        if d:
            out.append(d)
    return sorted(out)


def digits_only(phone):
    return re.sub(r"\D", "", phone or "")
