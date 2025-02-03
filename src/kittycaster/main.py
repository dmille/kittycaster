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
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from .chromecast_helper import get_chromecast, cast_media, stop_casting
from .logger import logger
from .fileserver import start_http_server, stop_http_server


def user_message(msg):
    print(msg)


devices_in_use = set()


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

DEFAULT_CONFIG_DICT = {
    "friendly_name": "KittyCaster TV",
    "discovery_timeout": 10,
    "schedule": [],
    "serve_local_folder": "videos",
    "serve_port": 8000,
    "include_local_media": True,
    "media_files": [],
}

DEFAULT_CONTENT = """\
friendly_name: "KittyCaster TV"
discovery_timeout: 10
serve_local_folder: "videos"
serve_port: 8000
include_local_media: true
media_files: []

schedule:
  # - friendly_name: "Living Room TV"
  #   media_file: "my_video.mp4"
  #   time: "08:00"
  #   action: "start"
  #   volume: 0.07
  # - friendly_name: "Living Room TV"
  #   time: "09:00"
  #   action: "stop"
"""

DEFAULT_CONFIG_PATH = Path("~/.config/kittycaster/config.yaml").expanduser()


def create_default_config(config_path: Path) -> None:
    if config_path.exists():
        user_message(f"Config file already exists at '{config_path}'. No changes made.")
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with config_path.open("w", encoding="utf-8") as f:
            f.write(DEFAULT_CONTENT)
        user_message(f"Created default config at '{config_path}'.")
    except Exception as exc:
        logger.error("Failed to create config at '%s': %s", config_path, exc)


def load_config(config_file: Path) -> dict:
    if not config_file.exists():
        logger.warning("Config file '%s' not found. Using defaults.", config_file)
        return DEFAULT_CONFIG_DICT
    try:
        with config_file.open("r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
            return {**DEFAULT_CONFIG_DICT, **user_config}
    except Exception as exc:
        logger.error("Error loading config '%s': %s. Using defaults.", config_file, exc)
        return DEFAULT_CONFIG_DICT


def gather_local_media_urls(directory: str, port: int) -> list:
    from pathlib import Path

    p = Path(directory).expanduser().resolve()
    if not p.is_dir():
        logger.warning("Local media folder '%s' is not a directory.", p)
        return []
    base_url = f"http://{HOST_IP}:{port}"
    found = [
        f"{base_url}/{entry.name}"
        for entry in p.iterdir()
        if entry.is_file() and entry.suffix.lower() in [".mp4", ".webm"]
    ]
    logger.info("Found %d local media files in '%s'.", len(found), p)
    return found


def build_local_url_if_needed(media_file: str, directory: str, port: int) -> str:
    if media_file.startswith("http://") or media_file.startswith("https://"):
        return media_file
    return f"http://{HOST_IP}:{port}/{os.path.basename(media_file)}"


def schedule_event(
    friendly_name: str,
    media_file: str,
    event_time: str,
    action: str,
    discovery_timeout: int,
    volume: float = 1.0,
    serve_local_folder: str = "",
    serve_port: int = 8000,
):
    def perform_action():
        user_message(
            f"Scheduled Event at {event_time}: {action} on {friendly_name} with media {media_file}"
        )
        cc = get_chromecast(friendly_name, discovery_timeout)
        devices_in_use.add(friendly_name)
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
            if config["media_files"]:
                mfile = random.choice(config["media_files"])
            else:
                logger.warning("Skipping schedule item: no media_file available.")
                continue
        t = item.get("time", "08:00")
        act = item.get("action", "start")
        vol = item.get("volume", 1.0)
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


def start_random_video(config):
    if not config["media_files"]:
        logger.warning("No media_files in config; cannot 'start'.")
        return
    chosen = random.choice(config["media_files"])
    cc = get_chromecast(config["friendly_name"], config["discovery_timeout"])
    devices_in_use.add(config["friendly_name"])
    final_url = build_local_url_if_needed(
        chosen, config["serve_local_folder"], config["serve_port"]
    )
    logger.info("Manual start: %s", final_url)
    cast_media(cc, final_url, config.get("volume", 1.0))


def start_specific_video(config, media_file):
    if not media_file:
        logger.warning("No media file provided.")
        return
    cc = get_chromecast(config["friendly_name"], config["discovery_timeout"])
    devices_in_use.add(config["friendly_name"])
    final_url = build_local_url_if_needed(
        media_file, config["serve_local_folder"], config["serve_port"]
    )
    logger.info("Manual start (specific): %s", final_url)
    cast_media(cc, final_url, config.get("volume", 1.0))


def stop_current_video(config):
    cc = get_chromecast(config["friendly_name"], config["discovery_timeout"])
    logger.info("Manual stop.")
    stop_casting(cc)


def stop_all_devices(config):
    user_message("Stopping all videos on all known devices...")
    for dev in devices_in_use:
        user_message(f" - Stopping device: {dev}")
        try:
            cc = get_chromecast(dev, config["discovery_timeout"])
            stop_casting(cc)
        except SystemExit:
            logger.error("Could not stop device '%s'.", dev)
    devices_in_use.clear()


def schedule_worker():
    while True:
        schedule.run_pending()
        time.sleep(1)


def run_schedule_loop_with_prompt(config):
    jobs = schedule.get_jobs()
    if jobs:
        logger.info("Loaded %d scheduled event(s).", len(jobs))
        user_message(f"Loaded {len(jobs)} scheduled event(s):")
        for job in jobs:
            m = job.meta
            user_message(
                f"  Time={m.get('time','??')} | Action={m.get('action','?')} | "
                f"Device={m.get('friendly_name','?')} | Media={m.get('media_file','?')} | "
                f"Volume={m.get('volume',1.0):.3f}"
            )
    else:
        logger.info("No scheduled events found.")
    t = threading.Thread(target=schedule_worker, daemon=True)
    t.start()

    print("\nKittyCaster is running. Type 'start [file]', 'stop', or 'q' to quit.\n")
    session = PromptSession()
    try:
        with patch_stdout():
            while True:
                user_input = session.prompt("KittyCaster> ").strip()
                if not user_input:
                    continue
                parts = user_input.split(maxsplit=1)
                command = parts[0].lower()
                if command == "q":
                    logger.info("User requested quit.")
                    stop_all_devices(config)
                    break
                elif command == "start":
                    if len(parts) > 1:
                        start_specific_video(config, parts[1].strip())
                        user_message(f"Started video: {parts[1].strip()}")
                    else:
                        start_random_video(config)
                        user_message("Started random video.")
                elif command == "stop":
                    stop_current_video(config)
                    user_message("Stopped current video.")
                else:
                    user_message("Unknown command. Use 'start [file]', 'stop', or 'q'.")
    except KeyboardInterrupt:
        logger.info("Ctrl+C pressed; quitting.")
        stop_all_devices(config)
    finally:
        stop_http_server(force_close=True)
        print("KittyCaster exited. Goodbye!")


def main():
    parser = argparse.ArgumentParser(
        description="KittyCaster interactive command tool."
    )
    parser.add_argument(
        "--init", action="store_true", help="Create default config and exit."
    )
    parser.add_argument("--name", help="Override Chromecast name from config.")
    args = parser.parse_args()

    if args.init:
        create_default_config(DEFAULT_CONFIG_PATH)
        sys.exit(0)

    config = load_config(DEFAULT_CONFIG_PATH)
    if args.name:
        config["friendly_name"] = args.name

    if config.get("serve_local_folder"):
        start_http_server(config["serve_local_folder"], config.get("serve_port", 8000))

    if config.get("include_local_media"):
        found = gather_local_media_urls(
            config["serve_local_folder"], config["serve_port"]
        )
        for f in found:
            if f not in config["media_files"]:
                config["media_files"].append(f)

    load_schedule_from_config(config)
    run_schedule_loop_with_prompt(config)


if __name__ == "__main__":
    main()
