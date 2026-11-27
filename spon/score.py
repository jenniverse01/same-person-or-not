"""
score.py - final scoring on the 50 held-out practice hits ONLY (run after both models).
Uses the organisers' COST table from validate.py (clearing a real match = 60 points).
"""
import os
import sys

try:
    from .helpers import load_jsonl, set_data_dir
except ImportError:
    from helpers import load_jsonl, set_data_dir


def main(data_dir=None, validate_dir=None, rules_csv="rules_decisions.csv", tree_csv="tree_decisions.csv"):
    """Score the 50 practice hits. Same table as the original score.py."""
    import pandas as pd
    if data_dir:
        set_data_dir(data_dir)
    if not validate_dir:
        validate_dir = os.environ.get("SPON_VALIDATE")
    if not validate_dir:
        data = data_dir or os.environ.get("SPON_DATA")
        if data:
            validate_dir = os.path.dirname(os.path.abspath(data))
        else:
            validate_dir = "/workspace/spon-data/screening"
    if validate_dir not in sys.path:
        sys.path.insert(0, validate_dir)
    try:
        from validate import COST  # the official cost table
    except ImportError as exc:
        sys.exit(
            "Could not import COST from validate.py in %s.\n"
            "Pass --validate or set SPON_VALIDATE to the folder that contains validate.py "
            "(one level above the dev data).\n%s" % (validate_dir, exc)
        )
    if not os.path.exists(rules_csv):
        sys.exit("Missing %s. Run: python -m spon rules" % rules_csv)
    if not os.path.exists(tree_csv):
        sys.exit(
            "Missing %s. score.py compares the rules model with the tree model; "
            "tree_decisions.csv is produced by model_tree.py, which is not in this repo."
            % tree_csv
        )
    D = ["DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"]

    labels = {r["hit_id"]: r for r in load_jsonl("practice_labels.jsonl")}

    rules = pd.read_csv(rules_csv).set_index("hit_id")

    tree = pd.read_csv(tree_csv).set_index("hit_id")



    for name, pred in (("RULES", rules["decision"]), ("TREE", tree["tree_decision"])):

        truth = pd.Series({h: l["decision"] for h, l in labels.items()})

        p = pred.loc[truth.index]

        cost = sum(COST[t][q] for t, q in zip(truth, p))

        base = sum(COST[t]["REVIEW"] for t in truth)

        unsafe = sum(1 for t, q in zip(truth, p) if t != "DIFFERENT_ENTITY" and q == "DIFFERENT_ENTITY")

        print(f"===== {name}: accuracy {(p == truth).mean():.0%} ({(p == truth).sum()}/50), cost {cost} "

              f"(all-REVIEW baseline {base}), decision score {100 * max(0, 1 - cost / base):.1f}, unsafe clearances {unsafe}")

        print(pd.crosstab(truth.rename("true answer"), p.rename("model said")).reindex(index=D, columns=D, fill_value=0))

        for h in truth.index[p != truth]:

            print(f"  wrong: {h} true {truth[h]} {labels[h]['reason_codes']} -> said {p[h]} (cost {COST[truth[h]][p[h]]})")


def _cli(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Score rules and tree on the practice hits")
    p.add_argument("--data", default=os.environ.get("SPON_DATA"))
    p.add_argument("--validate", default=os.environ.get("SPON_VALIDATE"))
    p.add_argument("--rules", default="rules_decisions.csv")
    p.add_argument("--tree", default="tree_decisions.csv")
    p.add_argument("--workdir", default=os.environ.get("SPON_OUT") or ".")
    args = p.parse_args(argv)
    if not args.data:
        sys.exit("Pass --data DIR or set SPON_DATA to the dev folder.")
    work = args.workdir
    rules_csv = args.rules if args.rules != "rules_decisions.csv" else os.path.normpath(os.path.join(work, "rules_decisions.csv"))
    tree_csv = args.tree if args.tree != "tree_decisions.csv" else os.path.normpath(os.path.join(work, "tree_decisions.csv"))
    main(data_dir=args.data, validate_dir=args.validate, rules_csv=rules_csv, tree_csv=tree_csv)


if __name__ == "__main__":
    _cli()
