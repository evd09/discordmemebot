# logger_setup.py
import os
import logging
from logging.handlers import RotatingFileHandler

def setup_logger(name: str, log_file: str, level=logging.INFO):
    # If no directory was provided (e.g. "audio.log"), default to logs/
    dirpath = os.path.dirname(log_file)
    if not dirpath:
        dirpath = "logs"
        os.makedirs(dirpath, exist_ok=True)
        log_file = os.path.join(dirpath, log_file)
    else:
        os.makedirs(dirpath, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(level)
    handler = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    # Also log to stdout
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    return logger
