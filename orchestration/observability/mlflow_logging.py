"""MLflow tracing helper for autonomous-beamline chat turns.

One MLflow Run per chat turn, in experiment `autonomous/chat`, tagged with
`source` ∈ {`web`, `slack_llm_thread`, `slack_dm`, `orchestrator`}.

Failure-mode contract: this module must NEVER raise. Bounded HTTP timeouts
mean worst-case ~10 s of degradation per turn; the user turn always
proceeds.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Iterator, Optional

# Bound HTTP timeouts BEFORE importing mlflow — the SDK reads these at
# import time to seed its requests.Session defaults. Without this, a
# single mlflow call can hang ~120 s on a flaky WAN.
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")

import mlflow  # noqa: E402

from orchestration.config import MLFLOW_ENABLED, MLFLOW_TOKEN, MLFLOW_TRACKING_URI

# config.py gives us a Python-level default for MLFLOW_TRACKING_URI, but the
# mlflow SDK only reads os.environ. Push our resolved value back so both
# layers agree — otherwise a user who sets MLFLOW_ENABLED=1 + token but
# leaves URI unset would silently write to ./mlruns while our health_check
# reports "reachable at isaac…".
os.environ.setdefault("MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI)

logger = logging.getLogger(__name__)


# Module-level state: experiment-id cache + degraded flag surfaced via
# the orchestrator snapshot.
_exp_cache: dict[str, str] = {}
MLFLOW_DEGRADED: bool = False


def _enabled() -> bool:
    return bool(MLFLOW_ENABLED and MLFLOW_TOKEN)


def _mark_degraded(reason: str, *, first: bool) -> None:
    global MLFLOW_DEGRADED
    if first:
        logger.warning("mlflow degraded: %s", reason)
        MLFLOW_DEGRADED = True
    else:
        logger.info("mlflow still degraded: %s", reason)


def status() -> str:
    """`ok` | `degraded` | `disabled` — for the orchestrator snapshot."""
    if not _enabled():
        return "disabled"
    return "degraded" if MLFLOW_DEGRADED else "ok"


def get_or_create_experiment(name: str) -> Optional[str]:
    """Return experiment_id for `name`, creating if missing. None on failure."""
    if name in _exp_cache:
        return _exp_cache[name]
    try:
        exp = mlflow.get_experiment_by_name(name)
        exp_id = exp.experiment_id if exp else mlflow.create_experiment(name)
        _exp_cache[name] = exp_id
        return exp_id
    except Exception as e:
        _mark_degraded(f"get_or_create_experiment({name!r}): {e}",
                       first=not MLFLOW_DEGRADED)
        return None


@contextlib.contextmanager
def run(experiment: str, run_name: str | None = None,
        **tags) -> Iterator[Optional["mlflow.ActiveRun"]]:
    """Best-effort run context. Yields the active run, or None on any failure.

    Never raises. Coerces tag values to strings; drops Nones.
    """
    if not _enabled():
        yield None
        return

    exp_id = get_or_create_experiment(experiment)
    if exp_id is None:
        yield None
        return

    clean_tags = {k: str(v) for k, v in tags.items() if v is not None}

    active = None
    try:
        active = mlflow.start_run(
            experiment_id=exp_id, run_name=run_name, tags=clean_tags,
        )
    except Exception as e:
        _mark_degraded(f"start_run: {e}", first=not MLFLOW_DEGRADED)
        yield None
        return

    try:
        yield active
    except Exception:
        # Body errors propagate; we just make sure the run is closed.
        try:
            mlflow.end_run(status="FAILED")
        except Exception as e:
            _mark_degraded(f"end_run(FAILED): {e}", first=not MLFLOW_DEGRADED)
        raise
    else:
        try:
            mlflow.end_run()
        except Exception as e:
            _mark_degraded(f"end_run: {e}", first=not MLFLOW_DEGRADED)


def health_check() -> tuple[bool, str]:
    """One-time startup probe. Returns (ok, reason).

    Used by the FastAPI lifespan to log a loud banner if MLflow is
    unreachable, so a misconfigured deployment doesn't quietly drop traces.
    """
    if not MLFLOW_ENABLED:
        return False, "MLFLOW_ENABLED=0"
    if not MLFLOW_TOKEN:
        return False, "MLFLOW_TRACKING_TOKEN missing"
    try:
        mlflow.get_experiment_by_name("__healthcheck__")
        return True, f"reachable at {MLFLOW_TRACKING_URI}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
