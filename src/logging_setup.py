"""Run-scoped logging: console + rotating-per-run file."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)-22s %(message)s"


def setup_logging(level: str = "INFO", log_dir: str | Path = "logs",
                  run_id: str = "run") -> logging.Logger:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / f"{run_id}.log"

    root = logging.getLogger("lia")
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.handlers.clear()
    root.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FMT))
    root.addHandler(console)

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FMT))
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    root.debug("logging to %s", logfile)
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"lia.{name}")
