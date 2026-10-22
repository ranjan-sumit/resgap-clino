"""Back up or restore the run database and project folders.

    python scripts/backup.py create [--to DIR] [--keep N]
    python scripts/backup.py list
    python scripts/backup.py verify BACKUP.zip
    python scripts/backup.py restore BACKUP.zip [--overwrite]

Stop the app before restoring. Paths follow RESGAP_DB_PATH / RESGAP_PROJECTS_DIR / RESGAP_BACKUP_DIR.
A scheduled backup is just `create` run from cron or Task Scheduler.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import backup  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--to", default=None)
    c.add_argument("--keep", type=int, default=7)
    sub.add_parser("list")
    v = sub.add_parser("verify")
    v.add_argument("path")
    r = sub.add_parser("restore")
    r.add_argument("path")
    r.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "create":
            path = backup.create_backup(args.to, keep=args.keep)
            print(f"Backup written: {path}")
        elif args.cmd == "list":
            for p in backup.list_backups():
                print(p)
        elif args.cmd == "verify":
            m = backup.verify_backup(args.path)
            print(f"OK: made {m['created_at']}, {m['project_files']} project files, database {m['database_bytes']:,} bytes")
        else:
            out = backup.restore_backup(args.path, overwrite=args.overwrite)
            print(f"Restored {out['project_files']} project files and the database to {out['database']}")
            for m in out["moved_aside"]:
                print(f"  kept the previous data as {m}")
    except backup.BackupError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
