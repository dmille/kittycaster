#!/usr/bin/env python3

import os
import sys
import time
import random
import argparse
import logging
import schedule
import yaml
from datetime import datetime
from pathlib import Path
from functools import partial

# Relative import from within the same package
from .chromecast_helper import get_chromecast, cast_youtube_video, stop_casting

# -------------------------------------------------------------------
# Logging Configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default configuration if user doesn't provide or if no file found
DEFAULT_CONTENT = """\
friendly_name: "KittyCaster TV"
video_ids:
  - "Dk7bervg7b4"
  - "3H5w8LUdNT8"
  - "WjpCrzdMtCk"
  - "MrSYP-cotdg"
  - "e291etllHOQ"
discovery_timeout: 10
schedule:
  # Example schedule entries can go here
  # - friendly_name: "Living Room TV"
  #   video_id: "dQw4w9WgXcQ"
  #   time: "08:00"
  #   action: "start"
  #   volume: 0.05
  # - friendly_name: "Living Room TV"
  #   time: "10:00"
  #   action: "stop"
"""

DEFAULT_CONFIG_DICT = {
    "friendly_name": "KittyCaster TV",
    "video_ids": [
        "Dk7bervg7b4",
        "3H5w8LUdNT8",
        "WjpCrzdMtCk",
        "MrSYP-cotdg",
        "e291etllHOQ",
    ],
    "discovery_timeout": 10,
    "schedule": [],
}

# Our "accessible default location" for config
# For Linux/macOS, ~/.config/kittycaster/config.yaml is common
DEFAULT_CONFIG_PATH = Path("~/.config/kittycaster/config.yaml").expanduser()


def create_default_config(config_path: Path) -> None:
    """Create a default config file if none exists."""
    if config_path.exists():
        logger.info("Config file already exists at '%s'. No changes made.", config_path)
        return

    logger.info("Creating default config file at '%s'.", config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with config_path.open("w", encoding="utf-8") as f:
            f.write(DEFAULT_CONTENT)
        logger.info("Default config created successfully.")
    except Exception as exc:
        logger.error("Failed to create config at '%s': %s", config_path, exc)


def load_config(config_file: Path) -> dict:
    """
    Attempt to load a YAML config file, falling back to DEFAULT_CONFIG_DICT on failure.
    """
    if not config_file.exists():
        logger.warning(
            "Config file '%s' not found. Using built-in defaults. "
            "You can create one with 'kittycaster init' or manually at that path.",
            config_file,
        )
        return DEFAULT_CONFIG_DICT

    try:
        with config_file.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            # Merge with DEFAULT_CONFIG_DICT so missing keys fall back
            merged = {**DEFAULT_CONFIG_DICT, **config}
            return merged
    except Exception as exc:
        logger.error(
            "Error loading config file '%s': %s. Using defaults.", config_file, exc
        )
        return DEFAULT_CONFIG_DICT


import schedule
from functools import partial


def schedule_event(
    friendly_name: str,
    video_id: str,
    event_time: str,
    action: str,
    discovery_timeout: int,
    volume: float = 0.003,
):
    """
    Schedule a single event (start or stop) at a specific daily time.
    """

    def perform_action():
        # Import or reference your get_chromecast, cast_youtube_video, stop_casting
        from .chromecast_helper import get_chromecast, cast_youtube_video, stop_casting

        chromecast = get_chromecast(friendly_name, discovery_timeout)

        if action == "start":
            cast_youtube_video(chromecast, video_id, volume)
        elif action == "stop":
            stop_casting(chromecast)
        else:
            print(f"Unknown action: {action}")

    # Create the scheduled job
    job = schedule.every().day.at(event_time).do(perform_action)

    # Attach metadata so we can print it in run_schedule_loop, if desired
    job.meta = {
        "friendly_name": friendly_name,
        "video_id": video_id,
        "time": event_time,
        "action": action,
        "volume": volume,
    }


def schedule_video(
    friendly_name, video_id, start_time, end_time, discovery_timeout, volume=0.003
):
    """
    Schedule to start casting at start_time and stop at end_time daily.
    Uses the `schedule` library for once-daily triggers.
    """

    def start_cast():
        try:
            chromecast = get_chromecast(friendly_name, discovery_timeout)
            cast_youtube_video(chromecast, video_id, volume)
        except SystemExit:
            logger.error(
                "Could not start cast for %s due to device or error.", friendly_name
            )

    def stop_cast():
        try:
            chromecast = get_chromecast(friendly_name, discovery_timeout)
            stop_casting(chromecast)
        except SystemExit:
            logger.error(
                "Could not stop cast for %s due to device or error.", friendly_name
            )

    # Attach metadata to the schedule job via tagging or partial
    job_start = schedule.every().day.at(start_time).do(partial(start_cast))
    # You can attach a custom attribute on the job:
    job_start.meta = {
        "friendly_name": friendly_name,
        "video_id": video_id,
        "start_time": start_time,
        "volume": volume,
        "action": "start",
    }

    job_stop = schedule.every().day.at(end_time).do(partial(stop_cast))
    job_stop.meta = {
        "friendly_name": friendly_name,
        "video_id": video_id,
        "end_time": end_time,
        "volume": volume,
        "action": "stop",
    }


def interactive_schedule(config):
    """
    Prompt the user to interactively add schedule entries.
    """
    while True:
        logger.info("Interactive Scheduling - Enter details or type 'done' to finish.")

        friendly = input(f"Friendly Name (default: {config['friendly_name']}): ")
        if friendly.strip().lower() == "done":
            break
        friendly = friendly or config["friendly_name"]

        video_id = input("Video ID (default: random from config): ")
        if video_id.strip().lower() == "done":
            break
        if not video_id:
            video_id = random.choice(config["video_ids"])

        start_time = input("Start Time (HH:MM, 24-hr): ")
        if start_time.strip().lower() == "done":
            break

        end_time = input("End Time (HH:MM, 24-hr): ")
        if end_time.strip().lower() == "done":
            break

        volume_str = input("Volume (default 0.003): ")
        if volume_str.strip().lower() == "done":
            break
        volume = float(volume_str) if volume_str else 0.003

        # Validate times quickly (not robust but enough for example)
        try:
            datetime.strptime(start_time, "%H:%M")
            datetime.strptime(end_time, "%H:%M")
        except ValueError:
            logger.error("Invalid time format. Please retry.")
            continue

        logger.info(
            "Added schedule: friendly_name=%s, video_id=%s, start=%s, end=%s, volume=%s",
            friendly,
            video_id,
            start_time,
            end_time,
            volume,
        )
        schedule_video(
            friendly,
            video_id,
            start_time,
            end_time,
            config["discovery_timeout"],
            volume,
        )

        cont = input("Add another schedule? (y/N) ")
        if cont.lower() not in ["y", "yes"]:
            break


def run_schedule_loop():
    jobs = schedule.get_jobs()
    if not jobs:
        logger.warning("No schedule entries found.")
    else:
        logger.info("KittyCaster loaded %d scheduled event(s):", len(jobs))
        for job in jobs:
            meta = getattr(job, "meta", {})
            fname = meta.get("friendly_name", "Unknown")
            vid = meta.get("video_id", "N/A")
            t = meta.get("time", "??:??")
            act = meta.get("action", "unknown")
            vol = meta.get("volume", 0.003)
            if act == "start":
                # Show time, action, device, video ID, volume
                logger.info(
                    "Event: [Time=%s, Action=%s, Device=%s, VideoID=%s, Volume=%.3f]",
                    t,
                    act,
                    fname,
                    vid,
                    vol,
                )
            else:
                # For "stop" (or any other action), omit video/volume
                logger.info("Event: [Time=%s, Action=%s, Device=%s]", t, act, fname)

    logger.info("KittyCaster schedule is now running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(1)


def cmd_init(args):
    """
    Initialize config if none exists.
    """
    config_path = Path(args.config).expanduser()
    create_default_config(config_path)
    logger.info(
        "KittyCaster init complete. Config is located at '%s'. "
        "You can edit it or run 'kittycaster schedule --interactive' to add schedules.",
        config_path,
    )


def cmd_once(args):
    """
    Handle a one-off start or stop cast event.
    """
    config_path = Path(args.config).expanduser()
    config = load_config(config_path)

    if not args.start and not args.stop:
        raise SystemExit("--once requires either --start or --stop.")

    friendly_name = args.friendly_name or config["friendly_name"]
    discovery_timeout = config["discovery_timeout"]

    chromecast = get_chromecast(friendly_name, discovery_timeout)

    if args.start:
        video_id = (
            args.video_id if args.video_id else random.choice(config["video_ids"])
        )
        cast_youtube_video(chromecast, video_id, args.volume)
    elif args.stop:
        stop_casting(chromecast)


def cmd_schedule(args):
    config_path = Path(args.config).expanduser()
    config = load_config(config_path)

    if args.interactive:
        # If still doing interactive mode, you'll prompt for time + action,
        # then schedule one event at a time.
        interactive_schedule(config)
    else:
        schedule_data = config.get("schedule")

        # Validate that 'schedule' is a list
        if not isinstance(schedule_data, list):
            logger.error("Config error: 'schedule' must be a list.")
            sys.exit(1)

        for item in schedule_data:
            fname = item.get("friendly_name", config["friendly_name"])
            vid = item.get("video_id", random.choice(config["video_ids"]))
            etime = item.get("time", "08:00")  # Single time for this event
            act = item.get("action", "start")
            vol = item.get("volume", 0.003)

            schedule_event(fname, vid, etime, act, config["discovery_timeout"], vol)

    run_schedule_loop()


def main():
    parser = argparse.ArgumentParser(
        description="KittyCaster: Cast YouTube videos to Chromecast with scheduling. "
        "Default config path: ~/.config/kittycaster/config.yaml"
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to a YAML config file. Default: ~/.config/kittycaster/config.yaml",
    )

    subparsers = parser.add_subparsers(title="subcommands", dest="subcommand")

    # Subcommand: init
    init_parser = subparsers.add_parser(
        "init", help="Initialize KittyCaster config if it doesn't exist."
    )
    init_parser.set_defaults(func=cmd_init)

    # Subcommand: once
    once_parser = subparsers.add_parser("once", help="One-off cast or stop, then exit.")
    once_parser.add_argument(
        "--start", action="store_true", help="Start casting immediately."
    )
    once_parser.add_argument(
        "--stop", action="store_true", help="Stop casting immediately."
    )
    once_parser.add_argument(
        "--friendly_name", help="Override Chromecast friendly name."
    )
    once_parser.add_argument("--video_id", help="YouTube video ID to cast.")
    once_parser.add_argument(
        "--volume", type=float, default=0.003, help="Chromecast volume (default=0.003)."
    )
    once_parser.set_defaults(func=cmd_once)

    # Subcommand: schedule
    schedule_parser = subparsers.add_parser(
        "schedule", help="Run daily scheduled casts."
    )
    schedule_parser.add_argument(
        "--interactive", action="store_true", help="Prompt for schedule entries."
    )
    schedule_parser.set_defaults(func=cmd_schedule)

    if len(sys.argv) == 1:
        # If no subcommand is given, show help
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
