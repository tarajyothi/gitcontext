"""Logging: human-readable in development, one JSON object per line in production (for log aggregation)."""
import json
import logging

EXTRA = ("request_id", "method", "path", "status", "ms")


class JsonFormatter(logging.Formatter):
    def format(self, r: logging.LogRecord) -> str:
        d = {"ts": self.formatTime(r, "%Y-%m-%dT%H:%M:%S%z"), "level": r.levelname, "logger": r.name, "msg": r.getMessage()}
        d.update({k: getattr(r, k) for k in EXTRA if hasattr(r, k)})
        if r.exc_info:
            d["exc"] = self.formatException(r.exc_info)  # server-side only; never sent to clients
        return json.dumps(d)


def configure_logging(level: str, fmt: str) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(h)
    root.setLevel(level)
