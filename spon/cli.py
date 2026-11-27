"""Command line for the pipeline and the local review UI.

    python -m spon run --data /path/to/dev
    python -m spon review --data /path/to/dev --build
"""
import argparse
import os
import sys

from . import clean, features, join, model_rules, review, score
from .helpers import output_path

REQUIRED = (
    "alerts.jsonl",
    "hits.jsonl",
    "customers.jsonl",
    "accounts.jsonl",
    "onboarding.jsonl",
    "kyc_checks.jsonl",
    "notes.jsonl",
    "search_results.jsonl",
    "name_variants.json",
)


def require_data(path):
    """The dev folder the participant already has on disk. Never a path inside this repo's data."""
    if not path:
        sys.exit("Pass --data DIR or set SPON_DATA to the dev folder that contains hits.jsonl.")
    if not os.path.isdir(path):
        sys.exit(f"Data folder not found: {path}")
    missing = [name for name in REQUIRED if not os.path.exists(os.path.join(path, name))]
    if missing:
        sys.exit(f"{path} is missing {', '.join(missing)}")
    return os.path.abspath(path)


def run_pipeline(data, workdir):
    print(f"data:    {data}")
    print(f"workdir: {os.path.abspath(workdir)}")
    join.run(data_dir=data, out_dir=workdir)
    clean.run(in_jsonl=output_path(workdir, "joined.jsonl"), out_dir=workdir)
    features.main(
        in_jsonl=output_path(workdir, "clean.jsonl"),
        out_csv=output_path(workdir, "features.csv"),
        data_dir=data,
    )
    decisions = output_path(workdir, os.path.join("output", "dev.jsonl"))
    model_rules.main(
        in_jsonl=output_path(workdir, "clean.jsonl"),
        out_jsonl=decisions,
        out_csv=output_path(workdir, "rules_decisions.csv"),
    )
    return decisions


def _add_data(parser):
    parser.add_argument("--data", default=os.environ.get("SPON_DATA"), help="dev folder (or set SPON_DATA)")
    parser.add_argument(
        "--workdir",
        default=os.environ.get("SPON_OUT") or ".",
        help="where joined/clean/features/output are written (default: current directory, or SPON_OUT)",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="spon",
        description="Same Person or Not — local pipeline and review UI. Data stays on this machine.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="join, clean, features, then the rules model")
    _add_data(p)

    p = sub.add_parser("join", help="step 1: one row per hit")
    _add_data(p)

    p = sub.add_parser("clean", help="step 2: comparable dates, countries, names")
    p.add_argument("--in", dest="in_jsonl", default=None)
    p.add_argument("--workdir", default=os.environ.get("SPON_OUT") or ".")

    p = sub.add_parser("features", help="step 3: comparison columns")
    _add_data(p)

    p = sub.add_parser("rules", help="rules model -> output/dev.jsonl")
    p.add_argument("--in", dest="in_jsonl", default=None)
    p.add_argument("--workdir", default=os.environ.get("SPON_OUT") or ".")

    p = sub.add_parser("score", help="score rules and tree on the practice hits (needs validate.py)")
    _add_data(p)
    p.add_argument("--validate", default=os.environ.get("SPON_VALIDATE"), help="folder that contains validate.py")
    p.add_argument("--rules", default=None, help="rules_decisions.csv")
    p.add_argument("--tree", default=None, help="tree_decisions.csv")

    p = sub.add_parser("review", help="open the local review UI")
    _add_data(p)
    p.add_argument("--build", action="store_true", help="run the pipeline first, then open the UI")
    p.add_argument("--html", default=None, help="also write a self-contained HTML file")
    p.add_argument("--no-serve", action="store_true", help="do not start the local server")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="open the page in a browser")
    p.add_argument("--joined", default=None)
    p.add_argument("--clean", default=None)
    p.add_argument("--decisions", default=None)
    p.add_argument("--overrides", default=None)

    args = parser.parse_args(argv)
    if args.cmd == "run":
        run_pipeline(require_data(args.data), args.workdir)
        return
    if args.cmd == "join":
        data = require_data(args.data)
        print(f"data:    {data}")
        join.run(data_dir=data, out_dir=args.workdir)
        return
    if args.cmd == "clean":
        clean.run(in_jsonl=args.in_jsonl, out_dir=args.workdir)
        return
    if args.cmd == "features":
        data = require_data(args.data)
        features.main(
            in_jsonl=output_path(args.workdir, "clean.jsonl"),
            out_csv=output_path(args.workdir, "features.csv"),
            data_dir=data,
        )
        return
    if args.cmd == "rules":
        model_rules.main(
            in_jsonl=args.in_jsonl or output_path(args.workdir, "clean.jsonl"),
            out_jsonl=output_path(args.workdir, os.path.join("output", "dev.jsonl")),
            out_csv=output_path(args.workdir, "rules_decisions.csv"),
        )
        return
    if args.cmd == "score":
        data = require_data(args.data)
        work = args.workdir
        score.main(
            data_dir=data,
            validate_dir=args.validate,
            rules_csv=args.rules or output_path(work, "rules_decisions.csv"),
            tree_csv=args.tree or output_path(work, "tree_decisions.csv"),
        )
        return
    if args.cmd == "review":
        _review(args)
        return
    parser.error(f"unknown command {args.cmd}")


def _review(args):
    work = args.workdir
    if args.build:
        run_pipeline(require_data(args.data), work)
    data = ""
    if args.data:
        data = os.path.abspath(args.data) if os.path.isdir(args.data) else args.data
        if not os.path.isdir(args.data):
            print(f"warning: data folder not found: {args.data}", file=sys.stderr)
    decisions = args.decisions or output_path(work, os.path.join("output", "dev.jsonl"))
    joined = args.joined or output_path(work, "joined.jsonl")
    cleaned = args.clean or output_path(work, "clean.jsonl")
    overrides = args.overrides or output_path(work, "overrides.json")
    if not os.path.exists(decisions):
        sys.exit(
            f"No decisions at {decisions}.\n"
            "Run:  python -m spon review --data DIR --build"
        )
    payload = review.build_payload(data, joined, cleaned, decisions)
    html = review.render_html(payload)
    if args.html:
        folder = os.path.dirname(os.path.abspath(args.html))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"wrote {args.html}")
        print("That file contains the decisions. Do not commit it or send it anywhere.")
    if args.no_serve:
        if not args.html:
            sys.exit("Pass --html FILE, or leave the server on (drop --no-serve).")
        return
    ids = {hit["hit_id"] for hit in payload["hits"]}
    review.serve(html, overrides, ids, port=args.port, open_browser=args.open)
