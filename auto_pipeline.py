import argparse
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from settings import load_environment


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

load_environment()
PROJECT_DIR = Path(__file__).resolve().parent


def parse_schedule(value: str) -> set[str]:
    entries = set()
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        try:
            parsed = datetime.strptime(entry, "%H:%M")
        except ValueError as exc:
            raise ValueError(f"Invalid schedule time {entry!r}; expected HH:MM") from exc
        entries.add(parsed.strftime("%H:%M"))
    return entries


def pipeline_timezone() -> ZoneInfo:
    name = os.getenv("PIPELINE_TIMEZONE", os.getenv("DATA_TIMEZONE", "UTC"))
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Unknown PIPELINE_TIMEZONE: {name}") from exc


def run_script(script_name: str, *arguments: str) -> None:
    command = [sys.executable, str(PROJECT_DIR / script_name), *arguments]
    logger.info("Running: %s", " ".join(command))
    subprocess.run(command, cwd=PROJECT_DIR, check=True)


def run_ingestion_cycle() -> None:
    logger.info("Starting extraction and Bronze-to-Silver publish cycle")
    run_script("twitter_batch_interceptor.py")
    run_script("twitter_parser.py")
    logger.info("Ingestion cycle completed successfully")


def run_gold_cycle(target_date: str) -> None:
    logger.info("Starting Silver-to-Gold aggregation for %s", target_date)
    run_script("gold_aggregator.py", "--date", target_date)


def run_scheduler() -> None:
    ingestion_schedule = parse_schedule(
        os.getenv("PIPELINE_SCHEDULE", "09:30,11:00,12:30,14:00,15:30,16:50")
    )
    gold_schedule = parse_schedule(os.getenv("GOLD_SCHEDULE", "23:55"))
    timezone = pipeline_timezone()
    poll_seconds = int(os.getenv("SCHEDULER_POLL_SECONDS", "20"))
    if poll_seconds < 1:
        raise ValueError("SCHEDULER_POLL_SECONDS must be at least 1")
    completed_slots: set[str] = set()

    logger.info(
        "Scheduler online: timezone=%s ingestion=%s gold=%s",
        timezone,
        sorted(ingestion_schedule),
        sorted(gold_schedule),
    )
    while True:
        now = datetime.now(timezone)
        time_slot = now.strftime("%H:%M")
        date_key = now.date().isoformat()

        ingestion_key = f"ingestion:{date_key}:{time_slot}"
        if time_slot in ingestion_schedule and ingestion_key not in completed_slots:
            try:
                run_ingestion_cycle()
            except subprocess.CalledProcessError:
                logger.exception("Ingestion cycle failed; parser or downstream stages were stopped")
            finally:
                completed_slots.add(ingestion_key)

        gold_key = f"gold:{date_key}:{time_slot}"
        if time_slot in gold_schedule and gold_key not in completed_slots:
            try:
                run_gold_cycle(date_key)
            except subprocess.CalledProcessError:
                logger.exception("Gold aggregation failed")
            finally:
                completed_slots.add(gold_key)

        completed_slots = {key for key in completed_slots if f":{date_key}:" in key}
        time.sleep(poll_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Orchestrate the X Medallion pipeline")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Run one ingestion cycle and exit")
    mode.add_argument("--gold-only", action="store_true", help="Run only Gold aggregation")
    parser.add_argument("--date", help="Gold date in YYYY-MM-DD format")
    args = parser.parse_args()

    if args.once:
        run_ingestion_cycle()
    elif args.gold_only:
        target = args.date or datetime.now(pipeline_timezone()).date().isoformat()
        run_gold_cycle(target)
    else:
        run_scheduler()
