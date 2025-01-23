#!/usr/bin/env python3
"""
chromecast_helper.py

Provides functionality for discovering and controlling a Chromecast device.
"""

import sys
import time
import logging
from uuid import UUID

from zeroconf import Zeroconf
from pychromecast.discovery import CastBrowser
from pychromecast.models import CastInfo
from pychromecast import get_chromecast_from_cast_info
from pychromecast.controllers.youtube import YouTubeController
from pychromecast.error import PyChromecastError

logger = logging.getLogger(__name__)


class FriendlyNameListener:
    """
    A simple listener to track discovered devices by friendly_name.
    """

    def __init__(self, target_name: str):
        self.target_name = target_name
        self.devices_by_name: dict[str, CastInfo] = {}

    def add_cast(self, uuid: UUID, service: str) -> None:
        pass  # Not strictly needed for minimal usage

    def remove_cast(self, uuid: UUID, service: str, cast_info: CastInfo) -> None:
        name = cast_info.friendly_name
        if name in self.devices_by_name:
            del self.devices_by_name[name]

    def update_cast(self, uuid: UUID, service: str) -> None:
        pass


def get_chromecast(friendly_name: str, discovery_timeout: int = 10):
    """
    Discover and connect to a Chromecast by friendly name.
    """
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
            if cast_info.friendly_name == friendly_name:
                listener.devices_by_name[friendly_name] = cast_info
                found_cast_info = cast_info
                break
        if found_cast_info:
            break
        time.sleep(0.5)

    if not found_cast_info:
        browser.stop_discovery()  # closes Zeroconf internally
        logger.error("No Chromecast found with friendly name '%s'.", friendly_name)
        sys.exit(1)

    try:
        cast = get_chromecast_from_cast_info(found_cast_info, zconf)
        cast.wait()
    except PyChromecastError as err:
        browser.stop_discovery()
        logger.error("Failed to initialize Chromecast: %s", err)
        sys.exit(1)

    browser.stop_discovery()
    logger.info("Connected to Chromecast: %s", found_cast_info.friendly_name)
    return cast


def cast_youtube_video(chromecast, video_id: str, volume: float = 0.003):
    """
    Cast a YouTube video to the selected Chromecast.
    """
    logger.info("Casting YouTube video: https://www.youtube.com/watch?v=%s", video_id)
    chromecast.set_volume(volume)
    logger.info("Set Chromecast volume to %s", volume)

    yt_controller = YouTubeController(timeout=60)
    chromecast.register_handler(yt_controller)
    yt_controller.start_session_if_none()
    logger.info("Started YouTube session on %s", chromecast.cast_info.friendly_name)
    yt_controller.play_video(video_id)
    chromecast.media_controller.block_until_active()

    logger.info(
        "Video %s is now playing on %s", video_id, chromecast.cast_info.friendly_name
    )


def stop_casting(chromecast):
    """
    Stop any currently playing app on the Chromecast (including YouTube).
    """
    chromecast.quit_app()
    logger.info("Stopped casting on %s", chromecast.cast_info.friendly_name)
