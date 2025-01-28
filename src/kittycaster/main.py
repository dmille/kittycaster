#!/usr/bin/env python3

import os
import sys
import time
import random
import argparse
import logging
import schedule
import yaml
import threading
import socket
from datetime import datetime
from pathlib import Path
from functools import partial

# -------------------------------------------------------------------
# Relative import from within the same package
# (Ensure chromecast_helper.py is in the same directory or package)
# -------------------------------------------------------------------
from .chromecast_helper import (
    get_chromecast,
    cast_media,
    stop_casting,
)

# -------------------------------------------------------------------
# Logging Configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Automatically determine local IP
# -------------------------------------------------------------------
def get_local_ip() -> str:
    """
    Attempt to determine the machine's LAN IP by briefly connecting
    to a known external server (8.8.8.8). If that fails, fallback to 127.0.0.1.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually send data, just needs to 'connect' to get the right interface
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


HOST_IP = get_local_ip()
logger.info("Auto-detected local IP for HTTP server: %s", HOST_IP)

# -------------------------------------------------------------------
# Default Configuration (local-only)
# -------------------------------------------------------------------
DEFAULT_CONTENT = """\
friendly_name: "KittyCaster TV"
discovery_timeout: 10
schedule: []
serve_local_folder: "videos"
serve_port: 8000
include_local_media: true
media_files: []
"""

DEFAULT_CONFIG_DICT = {
    "friendly_name": "KittyCaster TV",
    "discovery_timeout": 10,
    "schedule": [],
    "serve_local_folder": "videos",
    "serve_port": 8000,
    "include_local_media": True,
    "media_files": [],
}

DEFAULT_CONFIG_PATH = Path("~/.config/kittycaster/config.yaml").expanduser()


# -------------------------------------------------------------------
# Create/load config
# -------------------------------------------------------------------
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


# -------------------------------------------------------------------
# Simple HTTP server for local media
# -------------------------------------------------------------------
import http.server
import socketserver


def start_http_server(directory: str, port: int):
    """
    Starts a simple HTTP server in a background thread, serving 'directory' at 'port'.
    """
    if not directory:
        return  # No directory configured -> do nothing

    directory = str(Path(directory).expanduser().resolve())

    def serve_forever():
        Handler = partial(http.server.SimpleHTTPRequestHandler, directory=directory)
        with socketserver.TCPServer(("", port), Handler) as httpd:
            logger.info(
                "Serving local folder '%s' at http://0.0.0.0:%d/", directory, port
            )
            httpd.serve_forever()

    server_thread = threading.Thread(target=serve_forever, daemon=True)
    server_thread.start()


def gather_local_media_urls(directory: str, port: int) -> list:
    """
    Scans the given directory for media files and returns a list of full HTTP URLs,
    served at http://<HOST_IP>:port/<filename>.
    """
    if not directory:
        return []

    directory_path = Path(directory).expanduser().resolve()
    if not directory_path.is_dir():
        logger.warning(
            "Local media folder '%s' does not exist or is not a directory.",
            directory_path,
        )
        return []

    # We'll reuse the globally determined HOST_IP
    base_url = f"http://{HOST_IP}:{port}"

    # Recognize these file extensions as "media"
    media_extensions = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".wav")
    local_urls = []

    for entry in directory_path.iterdir():
        if entry.is_file() and entry.suffix.lower() in media_extensions:
            media_url = f"{base_url}/{entry.name}"
            local_urls.append(media_url)

    logger.info("Found %d local media files in '%s'.", len(local_urls), directory_path)
    return local_urls


def build_local_url_if_needed(media_file: str, directory: str, port: int) -> str:
    """
    If 'media_file' starts with 'http', return it as-is.
    Otherwise, treat it as a local filename in 'directory' and build a URL:
      http://<HOST_IP>:<port>/<file_name>
    """
    if media_file.startswith("http://") or media_file.startswith("https://"):
        return media_file

    file_name = os.path.basename(media_file)  # Just ensure we take the basename
    return f"http://{HOST_IP}:{port}/{file_name}"


# -------------------------------------------------------------------
# Scheduling logic
# -------------------------------------------------------------------
def schedule_event(
    friendly_name: str,
    media_file: str,
    event_time: str,
    action: str,
    discovery_timeout: int,
    volume: float = 0.003,
    serve_local_folder: str = "",
    serve_port: int = 8000,
):
    """
    Schedule a single event (start or stop) at a specific daily time.
    """

    def perform_action():
        chromecast = get_chromecast(friendly_name, discovery_timeout)

        if action == "start":
            final_url = build_local_url_if_needed(
                media_file, serve_local_folder, serve_port
            )
            cast_media(chromecast, final_url, volume)
        elif action == "stop":
            stop_casting(chromecast)
        else:
            logger.error("Unknown action: %s", action)

    job = schedule.every().day.at(event_time).do(perform_action)
    job.meta = {
        "friendly_name": friendly_name,
        "media_file": media_file,
        "time": event_time,
        "action": action,
        "volume": volume,
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

        media_file = input("Local filename or full URL (default: random from config): ")
        if media_file.strip().lower() == "done":
            break
        if not media_file:
            # pick random from config["media_files"] if available
            if config["media_files"]:
                media_file = random.choice(config["media_files"])
            else:
                logger.warning("No local media found; please enter a filename/URL.")
                continue

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

        # Validate times quickly
        try:
            datetime.strptime(start_time, "%H:%M")
            datetime.strptime(end_time, "%H:%M")
        except ValueError:
            logger.error("Invalid time format. Please retry.")
            continue

        logger.info(
            "Added schedule: friendly_name=%s, media_file=%s, start=%s, end=%s, volume=%.3f",
            friendly,
            media_file,
            start_time,
            end_time,
            volume,
        )

        schedule_event(
            friendly,
            media_file,
            start_time,
            "start",
            config["discovery_timeout"],
            volume,
            config["serve_local_folder"],
            config["serve_port"],
        )
        schedule_event(
            friendly,
            media_file,
            end_time,
            "stop",
            config["discovery_timeout"],
            volume,
            config["serve_local_folder"],
            config["serve_port"],
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
            mf = meta.get("media_file", "N/A")
            t = meta.get("time", "??:??")
            act = meta.get("action", "unknown")
            vol = meta.get("volume", 0.003)
            if act == "start":
                logger.info(
                    "Event: [Time=%s, Action=%s, Device=%s, Media=%s, Volume=%.3f]",
                    t,
                    act,
                    fname,
                    mf,
                    vol,
                )
            else:
                logger.info("Event: [Time=%s, Action=%s, Device=%s]", t, act, fname)

    logger.info("KittyCaster schedule is now running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(1)


# -------------------------------------------------------------------
# Subcommand Handlers
# -------------------------------------------------------------------
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
    Handle a one-off start or stop cast event, using config defaults if no CLI overrides.
    """
    config_path = Path(args.config).expanduser()
    config = load_config(config_path)

    # --- Start HTTP server if configured ---
    if config.get("serve_local_folder"):
        start_http_server(config["serve_local_folder"], config.get("serve_port", 8000))

    # If local media is included, gather & add to config["media_files"]
    if config.get("include_local_media"):
        local_files = gather_local_media_urls(
            config["serve_local_folder"], config.get("serve_port", 8000)
        )
        for f in local_files:
            if f not in config["media_files"]:
                config["media_files"].append(f)

    if not args.start and not args.stop:
        raise SystemExit("--once requires either --start or --stop.")

    friendly_name = args.friendly_name or config["friendly_name"]
    discovery_timeout = config.get("discovery_timeout", 10)

    # Volume: command-line override > config > fallback
    if args.volume != 0.003:  # parser's default
        volume = args.volume
    else:
        volume = config.get("volume", 0.003)

    # Decide what to cast if --start
    if args.start:
        if args.media_file:
            chosen_file = args.media_file
        else:
            if config["media_files"]:
                chosen_file = random.choice(config["media_files"])
            else:
                logger.error("No local media found in config. Exiting.")
                sys.exit(1)

    chromecast = get_chromecast(friendly_name, discovery_timeout)

    if args.start:
        final_url = build_local_url_if_needed(
            chosen_file, config["serve_local_folder"], config["serve_port"]
        )
        cast_media(chromecast, final_url, volume)
    elif args.stop:
        stop_casting(chromecast)


def cmd_schedule(args):
    """
    Run daily scheduled casts (local-only).
    """
    config_path = Path(args.config).expanduser()
    config = load_config(config_path)

    # Start HTTP server if configured
    if config.get("serve_local_folder"):
        start_http_server(config["serve_local_folder"], config.get("serve_port", 8000))

    # If local media is included, gather & add to config["media_files"]
    if config.get("include_local_media"):
        local_files = gather_local_media_urls(
            config["serve_local_folder"], config.get("serve_port", 8000)
        )
        for f in local_files:
            if f not in config["media_files"]:
                config["media_files"].append(f)

    if args.interactive:
        interactive_schedule(config)
    else:
        schedule_data = config.get("schedule")
        if not isinstance(schedule_data, list):
            logger.error("Config error: 'schedule' must be a list.")
            sys.exit(1)

        for item in schedule_data:
            fname = item.get("friendly_name", config["friendly_name"])
            mf = item.get("media_file")  # user-specified local file or URL
            if not mf:
                # If config doesn't specify a media_file, try a random from the pool
                if config["media_files"]:
                    mf = random.choice(config["media_files"])
                else:
                    logger.warning(
                        "No media_file specified and none in config. Skipping."
                    )
                    continue

            etime = item.get("time", "08:00")
            act = item.get("action", "start")
            vol = item.get("volume", 0.003)

            schedule_event(
                fname,
                mf,
                etime,
                act,
                config["discovery_timeout"],
                vol,
                config["serve_local_folder"],
                config["serve_port"],
            )

    run_schedule_loop()


# -------------------------------------------------------------------
# Main Entry
# -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="KittyCaster (Local Only): Serve and cast local files to Chromecast with scheduling."
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
    once_parser.add_argument(
        "--media_file", help="Local file name (within served folder) or full http URL."
    )
    once_parser.add_argument(
        "--volume", type=float, default=0.003, help="Chromecast volume (default=0.003)."
    )
    once_parser.set_defaults(func=cmd_once)

    # Subcommand: schedule
    schedule_parser = subparsers.add_parser(
        "schedule", help="Run daily scheduled casts (local-only)."
    )
    schedule_parser.add_argument(
        "--interactive", action="store_true", help="Prompt for schedule entries."
    )
    schedule_parser.set_defaults(func=cmd_schedule)

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
