import logging
import logging.handlers
import os
import time
import json
import traceback
from typing import Optional, Sequence, Any, Dict
from constants.configs import ROOT_PATH

"""
logging_setup.py

Purpose:
    Centralized logging configuration used by the bot. Provides:
    - Text file logging with optional timed rotation or size-based rotation.
    - Optional JSONL structured logging using JsonFormatter for easier ingestion by
      log collectors (e.g., ELK, Loki, or other line-delimited JSON pipelines).
    - A console handler for immediate stdout visibility.

Important operational notes:
    - DEFAULT_LOG_DIR is resolved relative to the repository layout; ensure the process
      has filesystem permissions to create and write into the directory.
    - The module purposely configures the root logger only when it has no handlers
      to avoid duplicating handlers when setup_logging is called multiple times
      (for example in tests or interactive sessions). When handlers already exist,
      only the logging level of existing handlers is adjusted.
    - The JSON formatter includes a conservative set of reserved record attributes;
      any non-reserved attributes are added under "extra" as JSON-safe values,
      with non-serializable objects converted via repr() to avoid serialization failures.
    - The default UTC timestamping for JSON logs facilitates correlation across systems
      running in different time zones.
    - The setup reduces verbosity for noisy third-party libraries by setting WARNING
      for `asyncpg`, `aiohttp`, and `discord` (adjustable if you need more detailed DB logs).
"""

DEFAULT_LOG_DIR = os.path.join(ROOT_PATH, "logs")
DEFAULT_TEXT_LOG = "bot.log"
DEFAULT_JSON_LOG = "bot.jsonl"


class JsonFormatter(logging.Formatter):
    """
    JSON-oriented logging formatter.

    Rationale and behavior:
    - Produces one JSON object per log record (suitable for JSONL ingestion).
    - `fields` controls which keys are emitted and their order. Consumers should
      expect at least "timestamp", "level", "logger", and "message".
    - The _RESERVED set lists LogRecord attributes that are considered part of the
      standard logging API; other attributes are treated as "extra" and added under
      the "extra" key to avoid collisions with top-level fields.
    - When `include_extra` is True, the formatter will attempt to JSON-serialize
      extra values; any non-serializable value is replaced by its repr() so that
      logging does not fail due to custom objects.
    - `ensure_ascii` controls json.dumps behavior; default False to preserve UTF-8 content.
    - `separators` are provided to control output compactness; the default is (",", ":")
      for compact JSON suitable for line-oriented logs.
    """

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
        """
        Constructor parameters:
        - fields: sequence controlling emitted top-level JSON keys and their order.
        - utc: when True timestamps are rendered in UTC (ISO-like format), otherwise local time.
        - include_extra: when True non-reserved LogRecord attributes will be serialized under "extra".
        - ensure_ascii: passed to json.dumps; False preserves unicode characters.
        - separators: passed to json.dumps to control spacing (compact vs pretty).
        """
        super().__init__()
        self.fields = list(fields)
        self.utc = utc
        self.include_extra = include_extra
        self.ensure_ascii = ensure_ascii
        self.separators = separators  

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """
        Format the record.created timestamp.

        - If datefmt is provided it defers to time.strftime using either UTC or local time.
        - Otherwise it produces an ISO-like timestamp with a trailing 'Z' when utc=True.
        - Using time.gmtime/time.localtime avoids timezone-aware datetime dependencies and
          keeps the function lightweight and dependency-free.
        """
        t = time.gmtime(record.created) if self.utc else time.localtime(record.created)

        if datefmt:
            return time.strftime(datefmt, t)

        if self.utc:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", t)
        return time.strftime("%Y-%m-%dT%H:%M:%S", t)

    def _base_dict(self, record: logging.LogRecord) -> Dict[str, Any]:
        """
        Build the minimal dictionary of standard fields from a LogRecord.

        These base fields are always present and are the canonical metadata expected
        by downstream log consumers.
        """
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
        """
        Extract non-reserved LogRecord attributes as a serializable mapping.

        Behavior:
        - Skips keys in the reserved set.
        - Attempts json.dumps(v) to detect serializability; falls back to repr(v) on failure.
        - This strategy prevents logging from raising when custom objects are attached to records.
        """
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
        """
        Render the LogRecord as a JSON string.

        - Constructs the base object using `_base_dict` and then maps it through `fields`
          to enforce ordering and the presence of expected keys.
        - Attaches serialized exception and stack information when present to aid post-mortem
          analysis (note: large tracebacks will inflate log size).
        - Includes 'extra' if any non-reserved attributes were present on the LogRecord.
        """
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
    """
    Configure application-wide logging.

    Notes on parameters:
    - level: root logger level; handlers are also set to this level.
    - log_dir: directory where rotated log files will be created (auto-created if missing).
    - text_use_timed_rotation / text_when: use time-based rotation (e.g., 'midnight') or size-based rotation.
    - json_enabled: when True a JSONL file is written alongside the text log.
    - json_fields / json_utc / json_include_extra: configure JsonFormatter behavior.

    Behavior:
    - If the root logger already has handlers, setup_logging updates their levels instead
      of adding duplicate handlers. This design avoids double-logging when code calls this
      function multiple times (useful in unit tests or interactive sessions).
    - The function reduces verbosity for noisy third-party libraries by setting WARNING
      for `asyncpg`, `aiohttp`, and `discord`.
    """
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
        # Only add handlers when none exist to prevent duplicate log lines.
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
        # Root already configured elsewhere: adjust levels to match requested `level`.
        root.setLevel(level)
        for h in root.handlers:
            h.setLevel(level)

    # Reduce excessive log noise from common libraries unless the operator overrides them.
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.WARNING)