#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path


ADAPTER_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(ADAPTER_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_SERVICE_ROOT))

from app.services.runtime_state import RuntimeStateError, RuntimeStateManager


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create, migrate, and restore whole AI-WPS runtime-state snapshots."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot")
    _add_runtime_paths(snapshot)
    snapshot.add_argument("--reason", required=True)
    snapshot.add_argument("--protect-last-accepted", action="store_true")

    migrate = subparsers.add_parser("migrate")
    _add_runtime_paths(migrate)
    migrate.add_argument("--legacy-root", required=True)

    restore = subparsers.add_parser("restore")
    _add_runtime_paths(restore)
    restore.add_argument("--snapshot-id", required=True)
    restore.add_argument(
        "--confirm",
        choices=("RESTORE_WHOLE_STATE",),
        required=True,
        help="Explicit confirmation; partial restore is not supported.",
    )
    return parser


def _add_runtime_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--release-version", required=True)


def main(argv=None) -> int:
    arguments = _parser().parse_args(argv)
    manager = RuntimeStateManager(
        state_dir=Path(arguments.state_dir),
        backup_dir=Path(arguments.backup_dir),
        release_version=arguments.release_version,
    )
    try:
        if arguments.command == "snapshot":
            result = manager.create_snapshot(
                arguments.reason,
                protect_last_accepted=arguments.protect_last_accepted,
            )
        elif arguments.command == "migrate":
            result = manager.migrate_legacy_state(Path(arguments.legacy_root))
        else:
            result = manager.restore_snapshot(
                arguments.snapshot_id,
                confirmed=arguments.confirm == "RESTORE_WHOLE_STATE",
            )
    except RuntimeStateError as error:
        print(
            json.dumps(
                {"success": False, "status": error.status, "errorCode": error.code},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2 if error.status == "blocked" else 1
    except Exception:
        print(
            json.dumps(
                {
                    "success": False,
                    "status": "recovery",
                    "errorCode": "RUNTIME_STATE_OPERATION_FAILED",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(dict(result, success=True), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
