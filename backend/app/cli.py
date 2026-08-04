"""Management CLI: ``python -m app.cli create-admin`` / ``scan-library`` /
``backfill-links`` / ``backup-now`` (spec 5.1, 6, 8.4, 1.2)."""

from __future__ import annotations

import argparse
import getpass
import sys

from app.config import get_settings
from app.db import get_session_factory
from app.main import run_migrations
from app.security import MIN_PASSWORD_LENGTH, create_admin_user, password_policy_ok
from app.services import backup, discovery, library_scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nucs-cli", description="nucs management commands")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="Create or replace the admin user")
    create.add_argument("username")
    create.add_argument("password", nargs="?", help="optional: prompted securely when omitted")
    scan = sub.add_parser("scan-library", help="Scan the music library and extract artists")
    scan.add_argument(
        "--full", action="store_true", help="Ignore the incremental cache and rescan everything"
    )
    backfill = sub.add_parser("backfill-links", help="Enrich existing releases with covers and links")
    backfill.add_argument(
        "--limit", type=int, default=200, help="Maximum number of releases to process (default 200)"
    )
    sub.add_parser("backup-now", help="Create an online backup of the database (retention 7)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create-admin":
        return _create_admin(args.username, args.password)
    if args.command == "scan-library":
        return _scan_library(args.full)
    if args.command == "backfill-links":
        return _backfill_links(args.limit)
    if args.command == "backup-now":
        return _backup_now()
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


def _scan_library(full: bool) -> int:
    try:
        run_migrations()
        stats = library_scan.scan_library_sync(full=full)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(
        "Library scan finished: "
        f"files_seen={stats['files_seen']} files_parsed={stats['files_parsed']} "
        f"files_skipped={stats['files_skipped']} files_error={stats['files_error']} "
        f"artists_new={stats['artists_new']} artists_total={stats['artists_total']} "
        f"duration_s={stats['duration_s']}"
    )
    return 0


def _backfill_links(limit: int) -> int:
    try:
        run_migrations()
        with get_session_factory()() as db:
            stats = discovery.backfill_links_covers(db, limit=limit)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(
        "Backfill finished: "
        f"covers_fetched={stats['covers_fetched']} links_resolved={stats['links_resolved']} "
        f"errors={stats['pipeline_errors']}"
    )
    return 0


def _backup_now() -> int:
    try:
        run_migrations()
        dest = backup.backup_now(get_settings().db_path)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Backup written: {dest} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
