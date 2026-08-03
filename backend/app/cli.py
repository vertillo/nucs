"""Management CLI: ``python -m app.cli create-admin <username> <password>`` (spec 5.1)."""

from __future__ import annotations

import argparse
import getpass
import sys

from app.db import get_session_factory
from app.main import run_migrations
from app.security import MIN_PASSWORD_LENGTH, create_admin_user, password_policy_ok


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nucs-cli", description="nucs management commands")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="Create or replace the admin user")
    create.add_argument("username")
    create.add_argument("password", nargs="?", help="optional: prompted securely when omitted")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create-admin":
        return _create_admin(args.username, args.password)
    return 2  # pragma: no cover - argparse enforces a valid command


def _create_admin(username: str, raw: str | None) -> int:
    if raw is None:
        raw = getpass.getpass(f"Password for '{username}': ")
    if not password_policy_ok(raw):
        print(
            f"Error: password must be at least {MIN_PASSWORD_LENGTH} characters long.",
            file=sys.stderr,
        )
        return 2
    run_migrations()
    with get_session_factory()() as db:
        create_admin_user(db, username, raw)
    print(f"Admin user '{username}' created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
