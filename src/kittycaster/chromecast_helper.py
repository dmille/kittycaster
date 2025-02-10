#!/usr/bin/env python3
"""
chromecast_helper.py
Provides functionality for discovering and controlling a Chromecast device.
"""

import sys
import time
from uuid import UUID

from zeroconf import Zeroconf
from pychromecast.discovery import CastBrowser
from pychromecast.models import CastInfo
from pychromecast import get_chromecast_from_cast_info
from pychromecast.error import PyChromecastError

from .logger import logger


class FriendlyNameListener:
    def __init__(self, target_name: str):
        self.target_name = target_name
        self.devices_by_name: dict[str, CastInfo] = {}

    def add_cast(self, uuid: UUID, service: str) -> None:
        pass

    def remove_cast(self, uuid: UUID, service: str, cast_info: CastInfo) -> None:
        self.devices_by_name.pop(cast_info.friendly_name, None)

    def update_cast(self, uuid: UUID, service: str) -> None:
        pass


def get_chromecast(friendly_name: str, discovery_timeout: int = 5):
    zconf = Zeroconf()
    listener = FriendlyNameListener(friendly_name)
    browser = CastBrowser(cast_listener=listener, zeroconf_instance=zconf)
    browser.start_discovery()
    logger.info(
        "Discovering Chromecasts (friendly_name='%s') for up to %d seconds...",
        friendly_name,
        discovery_timeout,
    )
    deadline = time.time() + discovery_timeout
    found_cast_info = None
    while time.time() < deadline:
        for uuid, cast_info in browser.devices.items():
            listener.devices_by_name[cast_info.friendly_name] = cast_info
            if cast_info.friendly_name == friendly_name:
                found_cast_info = cast_info
                break
        if found_cast_info:
            break
        time.sleep(0.5)
    if not found_cast_info:
        browser.stop_discovery()
        zconf.close()
        logger.error("No Chromecast found with friendly name '%s'.", friendly_name)
        if listener.devices_by_name:
            logger.info("Discovered: %s", ", ".join(listener.devices_by_name.keys()))
        else:
            logger.info("No Chromecasts discovered.")
        sys.exit(1)
    try:
        cast = get_chromecast_from_cast_info(found_cast_info, zconf)
        cast.wait()
    except PyChromecastError as err:
        logger.error("Failed to initialize Chromecast: %s", err)
        sys.exit(1)
    finally:
        browser.stop_discovery()
        zconf.close()
    logger.info("Connected to Chromecast: %s", found_cast_info.friendly_name)
    return cast


def cast_media(chromecast, url: str, volume: float):
    filetype = url.rsplit(".", 1)[-1]
    if filetype not in ["mp4", "webm"]:
        raise ValueError(f"Unsupported filetype: {filetype}")
    logger.info("Casting media: %s", url)
    mc = chromecast.media_controller
    mc.play_media(url, f"video/{filetype}")
    mc.block_until_active()
    logger.info("Media is now playing on %s", chromecast.cast_info.friendly_name)
    chromecast.set_volume(volume)
    logger.info("Set Chromecast volume to %s", volume)


def stop_casting(chromecast):
    chromecast.quit_app()
    logger.info("Stopped casting on %s", chromecast.cast_info.friendly_name)
