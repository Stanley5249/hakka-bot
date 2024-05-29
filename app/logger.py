import json
import logging
import logging.config
from os import PathLike
from pathlib import Path

__all__ = ["get_logger"]

CONFIG_PATH = Path("app/resource/config.json")


def get_logger(
    name: str, config_path: str | PathLike[str] = CONFIG_PATH
) -> logging.Logger:
    logger = logging.getLogger(name)

    with open(config_path) as f:
        config_file = json.load(f)

    logging.config.dictConfig(config_file)

    return logger
