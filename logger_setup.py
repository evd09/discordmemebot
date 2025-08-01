import logging
from logging.handlers import RotatingFileHandler
import os

def setup_logger(name, log_file, level=logging.INFO):
    os.makedirs(os.path.dirname(log_file), exist_ok=True)  # Ensures log dir exists
    logger = logging.getLogger(name)
    logger.setLevel(level)

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s %(message)s')

    # Avoid duplicate handlers on reload
    if not logger.handlers:
        # Rotating file handler
        file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    logger.propagate = False
    return logger
