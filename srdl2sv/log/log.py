import logging
from typing import Optional

class CustomFormatter(logging.Formatter):
    """Logging Formatter to add colors and count warning / errors"""

    MAPPING = {
        'DEBUG'   : 37, # white
        'INFO'    : 32, # green
        'WARNING' : 33, # yellow
        'ERROR'   : 31, # red
        'CRITICAL': 41, # white on red bg
    }

    PREFIX = '\033['
    SUFFIX = '\033[0m'

    def format(self, record):
        colored_record = record
        levelname = colored_record.levelname
        seq = CustomFormatter.MAPPING.get(levelname, 37) # default white
        colored_levelname = ('{0}{1}m{2}{3}') \
            .format(
                CustomFormatter.PREFIX,
                seq,
                levelname,
                CustomFormatter.SUFFIX)
        colored_record.levelname = colored_levelname

        return logging.Formatter.format(self, colored_record)

def create_logger (
        mod_name,
        stream_log_level: int = logging.WARNING,
        file_log_level: int = logging.INFO,
        file_name: Optional[str] = None):

    log = logging.getLogger(mod_name)
    log.setLevel(min(stream_log_level, file_log_level))

    if file_log_level > 0 and file_name:
        file_handler = logging.FileHandler(file_name)
        file_handler.setLevel(file_log_level)

        file_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s: %(message)s")
        file_handler.setFormatter(file_formatter)
        log.addHandler(file_handler)

    if stream_log_level > 0:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(stream_log_level)

        stream_formatter = CustomFormatter(
            "[%(levelname)s][%(name)s] %(message)s")
        stream_handler.setFormatter(stream_formatter)
        log.addHandler(stream_handler)

    return log
