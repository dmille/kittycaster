#!/usr/bin/env python3

import os
import sys
import time
import random
import argparse
import schedule
import yaml
import threading
import socket
import queue
import socketserver

from pathlib import Path

from .chromecast_helper import (
    get_chromecast,
    cast_media,
    stop_casting,
)
from .logger import logger
from .fileserver import start_http_server, stop_http_server


# -------------------------------------------------------------------
# Determine local IP
# -------------------------------------------------------------------
def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


HOST_IP = get_local_ip()
logger.info("Auto-detected local IP for HTTP server: %s", HOST_IP)

# -------------------------------------------------------------------
# Default Config
# -------------------------------------------------------------------

DEFAULT_CONFIG_DICT = {
    "friendly_name": "KittyCaster TV",
    "discovery_timeout": 10,
    "schedule": [],
    "serve_local_folder": "videos",
    "serve_port": 8000,
    "include_local_media": True,
    "media_files": [],
}


DEFAULT_CONTENT = yaml.dump(DEFAULT_CONFIG_DICT)
DEFAULT_CONFIG_PATH = Path("~/.config/kittycaster/config.yaml").expanduser()


# -------------------------------------------------------------------
# Config creation / load
# -------------------------------------------------------------------
def create_default_config(config_path: Path) -> None:
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
    if not config_file.exists():
        logger.warning(
            "Config file '%s' not found. Using defaults. "
            "Create one with 'kittycaster --init'.",
            config_file,
        )
        return DEFAULT_CONFIG_DICT

    try:
        with config_file.open("r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
            merged = {**DEFAULT_CONFIG_DICT, **user_config}
            return merged
    except Exception as exc:
        logger.error("Error loading config '%s': %s. Using defaults.", config_file, exc)
        return DEFAULT_CONFIG_DICT


# -------------------------------------------------------------------
# Local Media
# -------------------------------------------------------------------
def gather_local_media_urls(directory: str, port: int) -> list:
    if not directory:
        return []
    p = Path(directory).expanduser().resolve()
    if not p.is_dir():
        logger.warning("Local media folder '%s' is not a directory.", p)
        return []

    base_url = f"http://{HOST_IP}:{port}"
    exts = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".wav")
    found = []
    for entry in p.iterdir():
        if entry.is_file() and entry.suffix.lower() in exts:
            found.append(f"{base_url}/{entry.name}")

    logger.info("Found %d local media files in '%s'.", len(found), p)
    return found


def build_local_url_if_needed(media_file: str, directory: str, port: int) -> str:
    if media_file.startswith("http://") or media_file.startswith("https://"):
        return media_file
    filename = os.path.basename(media_file)
    return f"http://{HOST_IP}:{port}/{filename}"


# -------------------------------------------------------------------
# Scheduling
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
    def perform_action():
        cc = get_chromecast(friendly_name, discovery_timeout)
        if action == "start":
            final_url = build_local_url_if_needed(
                media_file, serve_local_folder, serve_port
            )
            cast_media(cc, final_url, volume)
        elif action == "stop":
            stop_casting(cc)
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


def load_schedule_from_config(config):
    sched = config.get("schedule", [])
    if not isinstance(sched, list):
        logger.error("Config 'schedule' must be a list.")
        return

    for item in sched:
        fname = item.get("friendly_name", config["friendly_name"])
        mfile = item.get("media_file")
        if not mfile:
            # if not specified, pick random from config
            if config["media_files"]:
                mfile = random.choice(config["media_files"])
            else:
                logger.warning(
                    "Skipping schedule item: no media_file & empty media_files."
                )
                continue

        t = item.get("time", "08:00")
        act = item.get("action", "start")
        vol = item.get("volume", 0.003)
        schedule_event(
            fname,
            mfile,
            t,
            act,
            config["discovery_timeout"],
            vol,
            config["serve_local_folder"],
            config["serve_port"],
        )


# -------------------------------------------------------------------
# Manual Commands
# -------------------------------------------------------------------
def start_random_video(config):
    if not config["media_files"]:
        logger.warning("No media_files in config; cannot 'start'.")
        return
    chosen = random.choice(config["media_files"])
    cc = get_chromecast(config["friendly_name"], config["discovery_timeout"])
    final_url = build_local_url_if_needed(
        chosen, config["serve_local_folder"], config["serve_port"]
    )
    logger.info("Manual start: %s", final_url)
    cast_media(cc, final_url, config.get("volume", 0.003))


def stop_current_video(config):
    cc = get_chromecast(config["friendly_name"], config["discovery_timeout"])
    logger.info("Manual stop.")
    stop_casting(cc)


# -------------------------------------------------------------------
# Main Loop with separate input thread
# -------------------------------------------------------------------
def read_user_input(cmd_queue):
    """
    Blocking input() in a separate thread.
    Each time the user types a line, we put it into cmd_queue.
    """
    print("\nKittyCaster is running. Type 'start', 'stop', or 'q' to quit.\n")
    while True:
        try:
            cmd = input("KittyCaster> ").strip().lower()
        except EOFError:
            # e.g. if user closes terminal
            cmd = "q"
        cmd_queue.put(cmd)
        if cmd == "q":
            break


def run_schedule_loop(config):
    # Display any scheduled events
    jobs = schedule.get_jobs()
    if jobs:
        logger.info("Loaded %d scheduled event(s).", len(jobs))
        for job in jobs:
            m = job.meta
            logger.info(
                "  Time=%s | Action=%s | Device=%s | Media=%s | Volume=%.3f",
                m.get("time", "??"),
                m.get("action", "?"),
                m.get("friendly_name", "?"),
                m.get("media_file", "?"),
                m.get("volume", 0.003),
            )
    else:
        logger.info("No scheduled events found.")

    # Start a thread to read user commands
    cmd_queue = queue.Queue()
    input_thread = threading.Thread(
        target=read_user_input, args=(cmd_queue,), daemon=True
    )
    input_thread.start()

    try:
        while True:
            # 1) Run any scheduled tasks
            schedule.run_pending()

            # 2) Check if user typed something
            while not cmd_queue.empty():
                cmd = cmd_queue.get()
                if cmd == "start":
                    start_random_video(config)
                elif cmd == "stop":
                    stop_current_video(config)
                elif cmd == "q":
                    logger.info("User requested quit.")
                    return
                else:
                    print("Unknown command:", cmd)

            # 3) Sleep a bit so we don't busy-loop
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Ctrl+C pressed; quitting.")
    finally:
        stop_http_server()
        print("KittyCaster exited. Goodbye!")


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="KittyCaster with 2-thread solution to avoid repeated prompts."
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Create default config if missing, then exit.",
    )
    parser.add_argument("--name", help="Override Chromecast name from config.")
    args = parser.parse_args()

    if args.init:
        create_default_config(DEFAULT_CONFIG_PATH)
        sys.exit(0)

    # Load config
    config = load_config(DEFAULT_CONFIG_PATH)
    if args.name:
        config["friendly_name"] = args.name

    # Start HTTP server
    if config.get("serve_local_folder"):
        start_http_server(config["serve_local_folder"], config.get("serve_port", 8000))

    # If needed, gather local media
    if config.get("include_local_media"):
        found = gather_local_media_urls(
            config["serve_local_folder"], config["serve_port"]
        )
        for f in found:
            if f not in config["media_files"]:
                config["media_files"].append(f)

    # Load schedule
    load_schedule_from_config(config)

    # Run main loop
    run_schedule_loop(config)


if __name__ == "__main__":
    main()
