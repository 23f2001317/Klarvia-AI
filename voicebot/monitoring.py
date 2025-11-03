import logging
import time
from typing import Dict, Optional

# Global debug flag (toggle from main)
DEBUG_MODE = False

# Internal pipeline state store
pipeline_state: Dict[str, Dict] = {}


def configure(debug: bool = False) -> None:
    """Configure global logging and debug mode."""
    global DEBUG_MODE
    DEBUG_MODE = bool(debug)
    level = logging.DEBUG if DEBUG_MODE else logging.INFO
    # Configure root logger if not already configured
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger(name: str):
    return logging.getLogger(name)


def stage_start(stage: str) -> float:
    """Mark the start time for a pipeline stage and return the timestamp."""
    t = time.time()
    pipeline_state[stage] = {"start": t, "end": None, "duration": None, "success": None, "msg": None}
    return t


def stage_end(stage: str, success: bool = True, msg: Optional[str] = None) -> float:
    """Mark the end time for a pipeline stage and store duration and status."""
    t = time.time()
    rec = pipeline_state.get(stage, {})
    start = rec.get("start")
    dur = (t - start) if start else None
    pipeline_state[stage] = {"start": start, "end": t, "duration": dur, "success": success, "msg": msg}
    return t


def debug_report() -> Dict[str, Dict]:
    """Return a copy of the current pipeline state for monitoring or printing."""
    # Return shallow copy to avoid external mutation
    return {k: dict(v) for k, v in pipeline_state.items()}
