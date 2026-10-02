"""Explicit owner commands. Startup, migration and seed never spend money."""
from __future__ import annotations

import argparse
import getpass
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .auth import Account, create_account, disable_account
from .db import session_scope
from .seeding import run_seed


def _owner(username: str) -> str:
    with session_scope() as session:
        user = session.scalar(select(Account).where(Account.username == username.lower(), Account.role == "owner", Account.disabled.is_(False)))
        if user is None:
            raise ValueError("Specify an enabled owner account")
        return user.id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    create = commands.add_parser("account-create")
    create.add_argument("username")
    create.add_argument("--role", choices=["owner", "reviewer"], required=True)
    create.add_argument("--display-name")
    disable = commands.add_parser("account-disable")
    disable.add_argument("username")
    publish = commands.add_parser("corpus-publish")
    publish.add_argument("corpus_id")
    publish.add_argument("--cutoff", required=True)
    publish.add_argument("--owner", required=True)
    publish.add_argument("--workspace", default="public-demo", help="Explicit evidence boundary; defaults to synthetic public demo only")
    index = commands.add_parser("corpus-index")
    index.add_argument("corpus_id")
    index.add_argument("--owner", required=True)
    commands.add_parser("usage")
    schema = commands.add_parser("export-openapi")
    schema.add_argument("--output", default="openapi.json")
    demo = commands.add_parser("export-demo")
    demo.add_argument("--output", default="../frontend/src/data")
    commands.add_parser("dataset-verify")
    evaluation = commands.add_parser("eval-openai")
    evaluation.add_argument("--owner", required=True)
    evaluation.add_argument("--stage", choices=["smoke", "pilot", "locked"], default="smoke")
    evaluation.add_argument("--retrieval-mode", choices=["evidence_only", "hybrid"], default="evidence_only")
    evaluation.add_argument("--corpus")
    evaluation.add_argument("--output")
    transfer = commands.add_parser("allowance-transfer")
    transfer.add_argument("--owner", required=True)
    transfer.add_argument("source", choices=["development", "evaluation", "reviewer", "buffer"])
    transfer.add_argument("destination", choices=["development", "evaluation", "reviewer", "buffer"])
    transfer.add_argument("amount", type=float)
    args = parser.parse_args()
    result: Any
    if args.command == "seed":
        result = run_seed()
    elif args.command == "account-create":
        password = getpass.getpass("Password (at least 12 characters): ")
        if password != getpass.getpass("Repeat password: "):
            raise ValueError("Passwords differ")
        result = create_account(args.username, password, args.role, args.display_name)
    elif args.command == "account-disable":
        disable_account(args.username)
        result = {"disabled": args.username}
    elif args.command == "corpus-publish":
        from .retrieval import publish_corpus
        _owner(args.owner)
        cutoff = datetime.fromisoformat(args.cutoff)
        if cutoff.tzinfo is None:
            raise ValueError("Cutoff requires timezone")
        with session_scope() as session:
            result = publish_corpus(session, args.corpus_id, cutoff, workspace_id=args.workspace)
    elif args.command == "corpus-index":
        from .retrieval import index_corpus
        result = index_corpus(args.corpus_id, _owner(args.owner))
    elif args.command == "usage":
        from .spending import usage_view
        with session_scope() as session:
            result = usage_view(session)
    elif args.command == "eval-openai":
        from .incident_model_eval import run
        output = Path(args.output or f"evaluation/openai-{args.stage}.json")
        result = run(output, _owner(args.owner), args.stage, args.retrieval_mode, args.corpus)
    elif args.command == "allowance-transfer":
        from .spending import move_allowance
        _owner(args.owner)
        with session_scope() as session:
            result = move_allowance(session, args.source, args.destination, args.amount)
    elif args.command == "export-openapi":
        from .api import app
        Path(args.output).write_text(json.dumps(app.openapi(), indent=2) + "\n")
        result = {"written": args.output}
    elif args.command == "export-demo":
        from .release_tools import export_demo
        result = export_demo(Path(args.output))
    else:
        from .dataset_evaluation import evaluate_dataset
        result = evaluate_dataset()
    print(json.dumps(result, indent=2, default=str))
    if args.command == "eval-openai" and result.get("status") != "MEASURED_STRUCTURAL_ONLY":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
