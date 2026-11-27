# Same Person or Not?

A bank must check its customers against watchlists: sanctions lists, politically exposed persons, and people named in adverse media or enforcement records. Its screening system matches names loosely, so it flags many possible hits. Most of those hits are different people who happen to share a similar name. This project is about entity resolution: working out who the customer really is, who the listed person really is, and whether they are the same person, so that clear false positives can be closed and genuine or uncertain matches can be left for a human to review. A decision is not enough on its own: every one must be explained, with the real grounds and the evidence that led to it, so a human can see why.

## The task

For every watchlist hit, the system must choose one of three decisions:

- **`DIFFERENT_ENTITY`** — the evidence shows this is a different person or company, so the hit can be cleared as a false positive.
- **`SAME_ENTITY`** — the evidence shows the hit is the customer.
- **`REVIEW`** — the evidence is insufficient or contradictory, so a human should decide.

Scoring is per hit. An alert closes only when every hit in it is `DIFFERENT_ENTITY`.

## Every decision must be explained

A label alone is not enough. For every hit, the output must include:

- **`reason_code`** — the main ground for the decision, taken from the table in `POLICY.md` (for example `DOB_MISMATCH`). The code must fit the case.
- **`evidence`** — the IDs of the records that actually decided it, exactly as they appear in the files, and not everything that was looked at.
- **`customer_record_id`** — the customer record the alert was resolved to, `AMBIGUOUS` if more than one person fits, or `null`.
- **`reason`** — two to four sentences naming the decisive facts, stating the real grounds with this hit's own facts.

Explanations must be honest about what is missing or unknown. A missing field is not a mismatch, and gaps must not be filled in.

Reasons are 25% of the decision score on both the unseen set and the development set. For finalists, the judges read the README and talk about how evidence is represented, and whether the explanations are honest about what is missing.

For example, the brief gives this comparison: a customer, Mohammed Ali, born 14 March 1988 in London, is matched to a watchlist hit, Mohamed Ali, born 1952 in Cairo. The right decision is `DIFFERENT_ENTITY`, because they were born 36 years apart. A good explanation would use a fitting reason code such as `DOB_MISMATCH` and a short reason that states those facts — not a generic comment about names being similar.

## Why it's hard

Neither side of the comparison arrives clean.

On the **customer** side, an alert only shows the person as they were screened, sometimes with a nickname or a typo. Their real details are spread across the bank's internal systems — customer records, accounts, identity checks, and support notes — and those systems do not share one key. One person can have more than one customer record. Family members can share a phone number or address and still be different people.

On the **watchlist** side, a useful fact such as a date of birth is often missing from a structured field. It may be buried in profile notes, or only findable in web search results for the name, most of which are about namesakes.

## Key rules

These constraints come from the hackathon brief:

- **Identity is not policy.** The only question is whether the two records describe the same person. Whether the listed offence matters, or whether the bank would accept the customer anyway, is out of scope.
- **Unsafe clearances are the worst mistake.** Clearing a real match (calling it `DIFFERENT_ENTITY` when the right answer is `SAME_ENTITY` or `REVIEW`) is far costlier than sending a hit to review. When in doubt, review is the safe choice — but reviewing everything resolves nothing and scores zero.
- **Results must be reproducible.** The same input should produce the same decision and reason code from run to run. The official evaluation runs the system five times on an unseen set and scores consistency.
- **Do not commit the dataset or API keys.** The data is for event participants only and must not be added to this repository.
- **Unknown stays unknown.** A missing field is not a mismatch, and neither is the missing part of a partial date. Do not fill gaps in.
- **Verified beats declared.** A passed identity check is more reliable than what the customer typed in. A rejected check is not evidence.
- **Build for the principles, not for one folder of files.** The system is tested on unseen data with new customers, new hits, and free text worded differently.

## Scoring

The system is run five times on an unseen set of about 550 hits, and once on the development set. The final score is out of 100:

| Part | Weight | What counts |
| --- | --- | --- |
| Unseen set | 80% | Decisions 75%, reasons 25% |
| Development set | 10% | Decisions 75%, reasons 25% |
| Reproducibility | 10% | The same decision and reason code in all five runs, scaled by the unseen score |

Each decision has a cost (lower is better):

| Right answer | You said `DIFFERENT_ENTITY` | You said `SAME_ENTITY` | You said `REVIEW` |
| --- | --- | --- | --- |
| `DIFFERENT_ENTITY` | 0 | 3 | 3 |
| `SAME_ENTITY` | 60 (unsafe clearance) | 0 | 2 |
| `REVIEW` | 60 (unsafe clearance) | 2 | 0 |

The decision score is the share of cost saved compared with sending every hit to review. Sending everything to review scores 0, and so does clearing everything (scores below 0 count as 0). Some hits are not scored because their answer depends on information that is not in the files; they should still be answered.

For every correct decision, the reason is also scored (25% of each set's score), as set out in "Every decision must be explained" above.

The evaluation also reports unsafe clearances, the share of false positives cleared, clearance precision, same-entity recall, and review rate.

## Data

The dataset is provided to event participants only and is **not** in this repository. Do not commit the development data, practice labels, or any derived extracts.

Participants receive a development set (about 440 alerts and 820 hits, plus a system of record of about 72,000 customer records and the bank's other systems) without answers, and 50 practice labels so a system can be checked while it is built. Official scoring is mainly on a separate unseen set from the same bank.

## Run it locally

Nothing in this pipeline uploads data. Point it at the dev folder on your machine (the folder that contains `hits.jsonl`, `alerts.jsonl`, `customers.jsonl`, and the rest). `validate.py` and `POLICY.md` live one level above that. For example:

```bash
export SPON_DATA="/Users/jennl/Downloads/screening/dev"
export SPON_VALIDATE="/Users/jennl/Downloads/screening"   # only needed for scoring
```

Do not copy that folder into the repo. `.gitignore` already blocks data folders, `output/`, jsonl and csv outputs, `overrides.json`, `review.html`, virtualenvs, and caches. The only jsonl in git is the small synthetic fixture under `tests/fixtures/dev`.

### Pipeline

From the repo root:

```bash
python -m spon run --data "$SPON_DATA"
```

That runs the four steps in order and writes, in the current directory (or `--workdir` / `SPON_OUT`):

| File | What it is |
| --- | --- |
| `joined.jsonl`, `joined.csv` | one row per hit, customer facts beside watchlist facts |
| `clean.jsonl`, `clean.csv` | dates, countries, names, and notes made comparable |
| `features.csv` | comparison columns, plus the practice label where the dev folder has one |
| `output/dev.jsonl` | the rules model's decision for every hit |
| `rules_decisions.csv` | the same decisions, one line per hit, for a spreadsheet |

`output/dev.jsonl` has one JSON object per hit: `hit_id`, `alert_id`, `decision`, `reason_code`, `customer_record_id`, `reason`, `evidence`.

The same steps one at a time:

```bash
python -m spon join --data "$SPON_DATA"
python -m spon clean
python -m spon features --data "$SPON_DATA"
python -m spon rules
```

The rules are the if-then list in `spon/model_rules.py`, taken from `POLICY.md`. Practice labels are not read there. They are a held-out check. A missing `practice_labels.jsonl` leaves the label columns in `features.csv` blank, so the same command can run on a folder that has no answers.

The official check is the organisers' script, which is not part of this repo:

```bash
python3 "$SPON_VALIDATE/validate.py" \
  --data "$SPON_DATA" \
  --output output/dev.jsonl \
  --score "$SPON_DATA/practice_labels.jsonl"
```

`python -m spon score` prints the same cost table for the rules file and for `tree_decisions.csv`. It imports `COST` from `validate.py` (pass `--validate` or set `SPON_VALIDATE`; otherwise it uses the parent of the data folder). The tree model (`model_tree.py`) is not in this repo, so score stops if `tree_decisions.csv` is missing. Scoring needs `pandas` (`python -m pip install pandas`). The gather, clean, features, and rules steps use only the standard library.

### Review UI

One command builds the decisions (if you pass `--build`) and serves a page on this machine only:

```bash
python -m spon review --data "$SPON_DATA" --build
```

Open the URL it prints (`http://127.0.0.1:8765` unless you pass `--port`). Add `--open` to launch a browser. The server binds to `127.0.0.1` and does not fetch anything from the network.

The page is the screening queue: totals, a search box, filters, the hit list, and a detail pane for the selected hit (the decision and reason, the evidence ids, how the customer was found, and the customer record beside the watchlist hit). "Held by the safety net" counts hits the rules refused to clear because the name and date of birth agree and only the country differs.

**My overrides** changes a decision and stores a note in `overrides.json` next to the other output (gitignored). The totals stay on the model's decisions. Pass `--html review.html` to also write a self-contained file; that file contains the decisions, so do not commit it or send it anywhere.

To click through the UI with no real customers:

```bash
python -m spon review --data tests/fixtures/dev --workdir /tmp/spon-review --build --open
```

### Tests

```bash
python -m pip install pytest
python -m pytest
```

The tests use `tests/fixtures/dev` only.

## Status

The runnable system is the rules pipeline above, plus the local review page. A separate tree model is not included.

