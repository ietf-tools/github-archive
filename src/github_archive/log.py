import json
import logging
import sys
from datetime import UTC, datetime

logger = logging.getLogger("github_archive")


class JSONFormatter(logging.Formatter):
    def __init__(self, run_id, secret):
        super().__init__()
        self.run_id = run_id
        self.secret = secret

    def format(self, record):
        line = json.dumps({
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            "run_id": self.run_id,
            **getattr(record, "fields", {}),
        }, default=str)
        if self.secret:
            line = line.replace(self.secret, "***")
        return line


def setup(level, run_id, secret):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter(run_id, secret))
    logger.addHandler(handler)
    logger.setLevel(level.upper())


def event(name, level=logging.INFO, **fields):
    logger.log(level, name, extra={"fields": fields})
