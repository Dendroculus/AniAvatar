import logging
import logging.handlers
import os
import time
import json
import traceback
from typing import Optional, Sequence, Any, Dict

DEFAULT_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "logs")
DEFAULT_TEXT_LOG = "bot.log"
DEFAULT_JSON_LOG = "bot.jsonl"


class JsonFormatter(logging.Formatter):
    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message"
    }

    def __init__(
        self,
        *,
        fields: Sequence[str] = ("timestamp", "level", "logger", "message", "module", "funcName", "lineno"),
        utc: bool = True,
        include_extra: bool = True,
        ensure_ascii: bool = False,
        separators: tuple[str, str] = (",", ":"),
    ):
        super().__init__()
        self.fields = list(fields)
        self.utc = utc
        self.include_extra = include_extra
        self.ensure_ascii = ensure_ascii
        self.separators = separators  

    def formatTime(self, record: logging.LogRecord) -> str:
        t = time.gmtime(record.created) if self.utc else time.localtime(record.created)
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", t) if self.utc else time.strftime("%Y-%m-%dT%H:%M:%S", t)

    def _base_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        base = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }
        return base

    def _extras(self, record: logging.LogRecord) -> Dict[str, Any]:
        if not self.include_extra:
            return {}
        extras: Dict[str, Any] = {}
        for k, v in record.__dict__.items():
            if k in self._RESERVED:
                continue
            try:
                json.dumps(v)
                extras[k] = v
            except Exception:
                extras[k] = repr(v)
        return extras

    def format(self, record: logging.LogRecord) -> str:
        obj = self._base_dict(record)

        obj = {k: obj.get(k, None) for k in self.fields}

        if record.exc_info:
            try:
                obj["exc_info"] = "".join(traceback.format_exception(*record.exc_info))
            except Exception:
                obj["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            obj["exc_info"] = record.exc_text

        if record.stack_info:
            obj["stack_info"] = record.stack_info

        extras = self._extras(record)
        if extras:
            obj["extra"] = extras

        return json.dumps(obj, ensure_ascii=self.ensure_ascii, separators=self.separators)


def setup_logging(
    *,
    level: int = logging.INFO,
    log_dir: Optional[str] = None,
    text_log_file: str = DEFAULT_TEXT_LOG,
    text_use_timed_rotation: bool = True,
    text_when: str = "midnight",
    text_backup_count: int = 7,
    text_max_bytes: int = 5 * 1024 * 1024,
    console_format: str = "%(levelname)s %(name)s: %(message)s",
    file_text_format: str = "%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    json_enabled: bool = True,
    json_log_file: str = DEFAULT_JSON_LOG,
    json_use_timed_rotation: bool = True,
    json_when: str = "midnight",
    json_backup_count: int = 7,
    json_max_bytes: int = 10 * 1024 * 1024,
    json_fields: Sequence[str] = ("timestamp", "level", "logger", "message", "module", "funcName", "lineno"),
    json_utc: bool = True,
    json_include_extra: bool = True,
) -> None:
    log_dir = log_dir or DEFAULT_LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(logging.Formatter(console_format))

    text_path = os.path.abspath(os.path.join(log_dir, text_log_file))
    if text_use_timed_rotation:
        text_handler = logging.handlers.TimedRotatingFileHandler(
            filename=text_path, when=text_when, backupCount=text_backup_count, encoding="utf-8", utc=True
        )
    else:
        text_handler = logging.handlers.RotatingFileHandler(
            filename=text_path, maxBytes=text_max_bytes, backupCount=text_backup_count, encoding="utf-8"
        )
    text_handler.setLevel(level)
    text_handler.setFormatter(logging.Formatter(file_text_format, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(level)
        root.addHandler(console)
        root.addHandler(text_handler)

        if json_enabled:
            json_path = os.path.abspath(os.path.join(log_dir, json_log_file))
            if json_use_timed_rotation:
                json_handler = logging.handlers.TimedRotatingFileHandler(
                    filename=json_path, when=json_when, backupCount=json_backup_count, encoding="utf-8", utc=True
                )
            else:
                json_handler = logging.handlers.RotatingFileHandler(
                    filename=json_path, maxBytes=json_max_bytes, backupCount=json_backup_count, encoding="utf-8"
                )
            json_handler.setLevel(level)
            json_handler.setFormatter(
                JsonFormatter(
                    fields=json_fields,
                    utc=json_utc,
                    include_extra=json_include_extra,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            root.addHandler(json_handler)
    else:
        root.setLevel(level)
        for h in root.handlers:
            h.setLevel(level)

    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)