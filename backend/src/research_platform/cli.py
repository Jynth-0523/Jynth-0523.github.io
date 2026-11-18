from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .alerts import LocalAlertManager
from .config import ConfigurationError, load_config
from .health_schema import validate_health_file
from .runner import AutomationRunner
from .store import RuntimeStore


def _default_config() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "platform_config.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platform-control")
    parser.add_argument("--config", type=Path, default=_default_config())
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    replay = subparsers.add_parser("replay", help="validate a saved fixture without running a subprocess")
    replay.add_argument("fixture", type=Path)
    subparsers.add_parser("run-now", help="manually run the one allowlisted read-only health check")
    disable = subparsers.add_parser("disable", help="activate kill switch")
    disable.add_argument("reason")
    enable = subparsers.add_parser("enable", help="clear kill switch")
    enable.add_argument("reason")
    subparsers.add_parser("verify-chain", help="verify immutable envelope chain")
    subparsers.add_parser("status", help="show chain head only")
    acknowledge = subparsers.add_parser("ack", help="acknowledge a local simulated alert")
    acknowledge.add_argument("fingerprint")
    acknowledge.add_argument("reason")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigurationError as exc:
        print(json.dumps({"state": "CONFIGURATION_ERROR", "message": str(exc)}, ensure_ascii=False))
        return 2

    if args.subcommand == "replay":
        validation = validate_health_file(
            args.fixture,
            config.identity,
            config.maximum_health_json_bytes,
        )
        print(json.dumps(validation.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if validation.valid else 1

    store = RuntimeStore(config.runtime_root)
    if args.subcommand == "run-now":
        outcome = AutomationRunner(config).run()
        print(json.dumps(outcome.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        if outcome.state in {"COMPLETED", "DUPLICATE", "ALREADY_RUNNING"}:
            return 0
        return 2
    if args.subcommand == "disable":
        path = store.set_disabled(True, args.reason)
        print(json.dumps({"state": "DISABLED", "audit_path": str(path)}, ensure_ascii=False))
        return 0
    if args.subcommand == "enable":
        path = store.set_disabled(False, args.reason)
        print(json.dumps({"state": "ENABLED", "audit_path": str(path)}, ensure_ascii=False))
        return 0
    if args.subcommand == "verify-chain":
        ok, issues = store.verify_chain()
        print(json.dumps({"valid": ok, "issues": issues}, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    if args.subcommand == "status":
        print(json.dumps({"disabled": store.disabled(), "chain_head": store.head()}, ensure_ascii=False, indent=2))
        return 0
    if args.subcommand == "ack":
        try:
            decision = LocalAlertManager(config.runtime_root).acknowledge(
                args.fingerprint,
                args.reason,
            )
        except (ValueError, FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"state": "ACK_ERROR", "message": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps(decision.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
