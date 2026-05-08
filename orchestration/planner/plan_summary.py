"""Plan summary generator.

Orchestrator-side routine called automatically when the Planner
submits or updates the experiment plan. Produces a per-sample summary
that is:

  1. Posted to Slack via SlackNotifier (no-ops when SLACK_BOT_TOKEN
     is missing — fine in dev / test).
  2. Persisted to disk under `data/plan_summaries/plan_summary_<experiment_id>.json`
     so the Data Collection UI page can render it without a fresh
     query.

Per-sample columns:
    sample_name, n_filters (xas_filter), counts_per_sec
    (survey_counts_per_sec), planned_n_scans (from plan_json or
    xas_reps fallback), planned_time_s (planned_n_scans × scan
    duration).

Latest 2 XAS plot images per sample are linked when available. Plots
are searched under `data/tool_plots/` (the canonical tool-output
directory written by `scripts/beamtimehero`); when no reliable
mapping exists, an empty `recent_plots` list is emitted and the slack
post skips the image attachments. Failures here are non-fatal — the
caller wraps the whole routine in try/except so a summary failure
never blows up the agent's update-plan call.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlmodel import select

from orchestration.config import DATA_DIR
from orchestration.plan_store.client import get_experiment_plan
from orchestration.plan_store.models import (
    CollectionScan,
    Experiment,
    SampleHolder,
    SamplePosition,
)
from orchestration.plan_store.session import get_session


logger = logging.getLogger(__name__)


SUMMARY_DIR = DATA_DIR / "plan_summaries"
TOOL_PLOTS_DIR = DATA_DIR / "tool_plots"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_and_post(experiment_id: str) -> Optional[dict]:
    """Build the plan summary, persist it, and fire the Slack notify.

    Returns the summary dict on success, None on hard failure (caller
    treats either as best-effort). Never raises.
    """
    try:
        summary = _build_summary(experiment_id)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("plan_summary: build failed for %s: %s", experiment_id, e)
        return None

    if summary is None:
        return None

    try:
        path = _persist_summary(experiment_id, summary)
        logger.info("plan_summary: wrote %s", path)
    except Exception as e:  # pragma: no cover
        logger.warning("plan_summary: persist failed: %s", e)

    try:
        _post_to_slack(summary)
    except Exception as e:  # pragma: no cover
        logger.warning("plan_summary: slack post failed: %s", e)

    return summary


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _build_summary(experiment_id: str) -> Optional[dict]:
    wrapper = get_experiment_plan(experiment_id) or {}
    body = wrapper.get("plan") or {}
    queue = body.get("sample_queue") or []
    plan_by_sid: dict[str, dict] = {q.get("sample_id"): q for q in queue if q.get("sample_id")}

    with get_session() as session:
        exp = session.get(Experiment, experiment_id)
        if exp is None:
            logger.info("plan_summary: experiment %s missing — skipping", experiment_id)
            return None
        # Walk every holder/sample; the summary is whole-experiment so
        # downstream views can choose how to slice.
        holders = list(session.exec(
            select(SampleHolder)
            .where(SampleHolder.experiment_id == experiment_id)
            .order_by(SampleHolder.queue_order, SampleHolder.created_at)  # type: ignore[arg-type]
        ).all())
        samples_by_holder: dict[str, list[SamplePosition]] = {}
        for h in holders:
            stmt = (
                select(SamplePosition)
                .where(SamplePosition.sample_holder_id == h.id)
                .order_by(SamplePosition.sample_number)  # type: ignore[union-attr]
            )
            samples_by_holder[h.id] = list(session.exec(stmt).all())

    holder_payloads: list[dict] = []
    for h in holders:
        rows: list[dict] = []
        for s in samples_by_holder.get(h.id, []):
            if not s.enabled:
                continue
            plan_entry = plan_by_sid.get(s.id, {}) or {}
            n_scans = plan_entry.get("planned_scans_total")
            count_time = None
            for m in plan_entry.get("modes") or []:
                if (m.get("mode") or "").lower() == "xas":
                    if n_scans is None and m.get("reps") is not None:
                        n_scans = m.get("reps")
                    if m.get("count_time_s") is not None:
                        count_time = float(m["count_time_s"])
                    break
            if n_scans is None:
                n_scans = s.xas_reps
            try:
                n_scans = int(n_scans)
            except (TypeError, ValueError):
                n_scans = int(s.xas_reps)
            if count_time is None:
                count_time = float(s.xas_time)

            planned_time_s = float(n_scans) * float(count_time)
            rows.append({
                "sample_id": s.id,
                "sample_name": s.sample_name,
                "element_symbol": s.element_symbol,
                "n_filters": int(s.xas_filter),
                "counts_per_sec": s.survey_counts_per_sec,
                "planned_n_scans": int(n_scans),
                "scan_duration_s": float(count_time),
                "planned_time_s": planned_time_s,
                "recent_plots": _find_recent_plots_for_sample(
                    s.id, s.sample_name, max_n=2,
                ),
            })
        holder_payloads.append({
            "holder_id": h.id,
            "holder_name": h.name,
            "samples": rows,
        })

    return {
        "experiment_id": experiment_id,
        "experiment_name": exp.name,
        "experimenter": exp.experimenter,
        "generated_at": datetime.now().isoformat(),
        "plan_updated_at": wrapper.get("updated_at"),
        "phase": wrapper.get("phase"),
        "holders": holder_payloads,
    }


# ---------------------------------------------------------------------------
# Plot lookup (best-effort)
# ---------------------------------------------------------------------------

def _find_recent_plots_for_sample(
    sample_id: str,
    sample_name: str | None = None,
    *,
    max_n: int = 2,
) -> list[str]:
    """Return up to ``max_n`` recent plot paths for the given sample.

    Primary path: query CollectionScan rows for ``sample_id`` (newest
    first). For each scan, glob
    ``data/tool_plots/plot_scan_*_scan{N}_*.png`` (the convention
    written by scripts/tool_dispatcher.py and scripts/beamtimehero
    when ``plot_scan`` runs with a ``file_name`` + ``scan_number``).
    Take the most recent file per scan by mtime, and return up to two.

    Backward-compat fallback: if no scans yield matches, fall back to
    the legacy substring match against ``sample_name`` so plots from
    before the per-scan filename convention still surface. Returns an
    empty list if nothing matches.
    """
    if not TOOL_PLOTS_DIR.exists():
        return []

    matched: list[Path] = []
    seen: set[str] = set()
    if sample_id:
        try:
            with get_session() as session:
                stmt = (
                    select(CollectionScan)
                    .where(CollectionScan.sample_id == sample_id)
                    .order_by(CollectionScan.timestamp.desc())  # type: ignore[union-attr]
                )
                scans = list(session.exec(stmt).all())
        except Exception as e:
            logger.warning("plan_summary: scan lookup failed for %s: %s", sample_id, e)
            scans = []

        for scan in scans:
            if len(matched) >= max_n:
                break
            try:
                pattern = f"plot_scan_*_scan{int(scan.scan_number)}_*.png"
            except (TypeError, ValueError):
                continue
            try:
                candidates = list(TOOL_PLOTS_DIR.glob(pattern))
            except OSError:
                continue
            if not candidates:
                continue
            candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            best = candidates[0]
            key = str(best)
            if key in seen:
                continue
            matched.append(best)
            seen.add(key)

    if matched:
        return [str(p) for p in matched[:max_n]]

    # Fallback: substring match against sample_name for legacy plots that
    # don't have a scan_number embedded in the filename.
    if not sample_name:
        return []
    needle = sample_name.lower().replace(" ", "_")
    if not needle:
        return []
    legacy: list[Path] = []
    try:
        for p in TOOL_PLOTS_DIR.glob("*.png"):
            if needle in p.name.lower():
                legacy.append(p)
    except OSError:
        return []
    if not legacy:
        return []
    legacy.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [str(p) for p in legacy[:max_n]]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _persist_summary(experiment_id: str, summary: dict) -> Path:
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    path = SUMMARY_DIR / f"plan_summary_{experiment_id}.json"
    path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Slack post
# ---------------------------------------------------------------------------

def _format_slack_text(summary: dict) -> str:
    name = summary.get("experiment_name") or summary.get("experiment_id")
    phase = summary.get("phase") or "?"
    lines: list[str] = [f"*Plan summary — {name}*  _(phase: {phase})_"]
    for h in summary.get("holders", []) or []:
        rows = h.get("samples") or []
        if not rows:
            continue
        lines.append(f"\n*Holder:* {h.get('holder_name') or h.get('holder_id')}")
        # Plain text table — Slack will render the backticks as monospace.
        header = (
            "`{:<22} {:>3} {:>10} {:>5} {:>9}`".format(
                "sample", "flt", "cps", "scans", "time_s"
            )
        )
        lines.append(header)
        for r in rows:
            cps = r.get("counts_per_sec")
            cps_str = f"{cps:>10.1f}" if isinstance(cps, (int, float)) else "         -"
            lines.append(
                "`{:<22} {:>3} {} {:>5} {:>9.1f}`".format(
                    (r.get("sample_name") or "")[:22],
                    r.get("n_filters", 0),
                    cps_str,
                    r.get("planned_n_scans", 0),
                    float(r.get("planned_time_s") or 0.0),
                )
            )
    return "\n".join(lines)


def _post_to_slack(summary: dict) -> None:
    try:
        from ui.adapters.slack_notify import SlackNotifier
    except Exception as e:
        logger.info("plan_summary: slack notifier unavailable (%s) — skipping post", e)
        return

    channel = os.getenv("SLACK_CHAT_CHANNEL_ID") or os.getenv("SLACK_CHANNEL_ID")
    notifier = SlackNotifier(enabled=True, channel=channel)
    text = _format_slack_text(summary)
    # post_message is a no-op when the notifier disabled itself for
    # missing token/channel — log either way so smoke tests can see
    # the call was exercised.
    logger.info(
        "plan_summary: posting to slack (enabled=%s) text-len=%d",
        notifier.enabled, len(text),
    )
    notifier.post_message(text)

    # Attach the first 2 plot images per sample, if any are resolvable.
    for h in summary.get("holders", []) or []:
        for r in h.get("samples") or []:
            for plot_path in (r.get("recent_plots") or [])[:2]:
                try:
                    notifier.post_image(plot_path, caption=f"{r.get('sample_name')} XAS")
                except Exception:  # pragma: no cover
                    logger.exception("plan_summary: post_image failed for %s", plot_path)
