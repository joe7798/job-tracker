"""CLI entry point for the job-application tracker agent."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# tomllib is stdlib in 3.11+; tomli is the 3.10 backport.
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from .mail import fetch_recent_messages
from .agent import AgentRunner

_PROCESSED_PATH = Path("processed.json")
_REVIEW_QUEUE_PATH = Path("review_queue.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_config() -> dict:
    config_path = Path("config.toml")
    if not config_path.exists():
        logger.warning("config.toml not found — using defaults.")
        return {}
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    return raw.get("tracker", {})


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(
            f"\nERROR: Environment variable '{name}' is not set.\n"
            "Copy .env.example to .env, fill in the values, and re-run.\n"
            "See README.md for details.",
            file=sys.stderr,
        )
        sys.exit(1)
    return value


def _load_processed() -> set[str]:
    if _PROCESSED_PATH.exists():
        return set(json.loads(_PROCESSED_PATH.read_text(encoding="utf-8")))
    return set()


def _save_processed(ids: set[str]) -> None:
    _PROCESSED_PATH.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


def _append_review_queue(items: list[dict]) -> None:
    existing: list[dict] = []
    if _REVIEW_QUEUE_PATH.exists():
        existing = json.loads(_REVIEW_QUEUE_PATH.read_text(encoding="utf-8"))
    existing.extend(items)
    _REVIEW_QUEUE_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def main() -> None:
    load_dotenv()

    config = _load_config()

    anthropic_key = _require_env("ANTHROPIC_API_KEY")
    azure_client_id = _require_env("AZURE_CLIENT_ID")
    sa_file = _require_env("GOOGLE_SERVICE_ACCOUNT_FILE")
    spreadsheet_id = _require_env("SPREADSHEET_ID")

    worksheet_name = config.get("worksheet_name", "Sheet1")
    lookback_days = int(config.get("lookback_days", 30))
    dry_run = bool(config.get("dry_run", True))
    status_values: list[str] = config.get(
        "status_values",
        ["Applied", "Acknowledged", "Interview", "Offer", "Rejected"],
    )

    if dry_run:
        print("\n*** DRY RUN MODE — no changes will be written to the sheet ***")
        print("Set dry_run = false in config.toml to enable writes.\n")

    # ------------------------------------------------------------------ #
    # Fetch mail                                                            #
    # ------------------------------------------------------------------ #
    logger.info("Fetching inbox messages from the last %d days …", lookback_days)
    try:
        all_messages = fetch_recent_messages(azure_client_id, lookback_days)
    except Exception as exc:
        print(f"\nERROR fetching mail: {exc}", file=sys.stderr)
        sys.exit(1)

    logger.info("Fetched %d message(s) from Graph API.", len(all_messages))

    # ------------------------------------------------------------------ #
    # Deduplication                                                         #
    # ------------------------------------------------------------------ #
    processed_ids = _load_processed()
    new_messages = [m for m in all_messages if m["id"] not in processed_ids]
    logger.info(
        "%d new message(s) after excluding %d already-processed.",
        len(new_messages),
        len(all_messages) - len(new_messages),
    )

    if not new_messages:
        print("\nNothing new to process.")
        return

    # ------------------------------------------------------------------ #
    # Run agent                                                             #
    # ------------------------------------------------------------------ #
    runner = AgentRunner(
        anthropic_api_key=anthropic_key,
        service_account_file=sa_file,
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
        status_values=status_values,
        dry_run=dry_run,
    )

    logger.info("Running agent on %d message(s) …", len(new_messages))
    try:
        agent_summary = runner.run(new_messages)
    except Exception as exc:
        print(f"\nERROR during agent run: {exc}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------ #
    # Persist state                                                         #
    # ------------------------------------------------------------------ #
    new_ids = {m["id"] for m in new_messages}
    _save_processed(processed_ids | new_ids)

    if runner.flagged:
        _append_review_queue(runner.flagged)
        logger.info("Appended %d item(s) to review_queue.json.", len(runner.flagged))

    # ------------------------------------------------------------------ #
    # Summary                                                               #
    # ------------------------------------------------------------------ #
    print("\n" + "=" * 60)
    print("AGENT SUMMARY")
    print("=" * 60)
    if agent_summary:
        print(agent_summary)
    print()
    print(f"  Updated  : {len(runner.updated)}")
    print(f"  Flagged  : {len(runner.flagged)}")
    print(f"  Processed: {len(new_messages)}")

    if runner.updated:
        print("\nUpdates:")
        for u in runner.updated:
            prefix = "[DRY RUN] " if dry_run else ""
            print(
                f"  {prefix}Row {u['row']}  {u['company']} / {u['role']}  "
                f"{u['old_status']} → {u['new_status']}"
            )
            if u.get("note"):
                print(f"           Note: {u['note']}")

    if runner.flagged:
        print("\nFlagged for manual review (see review_queue.json):")
        for f in runner.flagged:
            print(f"  • {f['subject']}")
            print(f"    Reason: {f['reason']}")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
