import logging
import http.server

from logging import FileHandler, StreamHandler, Formatter

# -------------------------------------------------------------------
# Logging Configuration
# -------------------------------------------------------------------
logger = logging.getLogger("kittycaster")  # or __name__
logger.setLevel(logging.INFO)  # Set overall minimum level

# Remove any default handlers that might have been added by basicConfig
for h in logger.handlers[:]:
    logger.removeHandler(h)

# Create a file handler
file_handler = FileHandler("kittycaster.log", mode="a")  # 'a' = append mode
file_handler.setLevel(logging.INFO)
file_formatter = Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler.setFormatter(file_formatter)

# Add both handlers to the logger
logger.addHandler(file_handler)

logger.info(
    "Logger configured. All INFO+ messages will go to kittycaster.log and console."
)
