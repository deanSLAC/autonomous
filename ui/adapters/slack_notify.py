"""
Slack Notification Module
=========================

One-way Slack posting for BL15-2 beamline automation status updates.
Sends formatted messages for phase completions, alerts, collection
progress, and summary images.

All methods are fire-and-forget: errors are logged but never raised,
so Slack downtime does not interrupt beamline operations.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class SlackNotifier:
    """One-way Slack notification client for beamline status updates.

    Parameters
    ----------
    enabled : bool
        Master toggle. If False, all methods return immediately.
    channel : str, optional
        Slack channel ID. Falls back to SLACK_CHANNEL_ID env var.
    """

    def __init__(
        self,
        enabled: bool = True,
        channel: Optional[str] = None,
    ):
        self.enabled = enabled
        if channel is None:
            from orchestration.config import SLACK_CHAT_CHANNEL_ID
            channel = SLACK_CHAT_CHANNEL_ID
        self.channel = channel
        token = os.getenv("SLACK_BOT_TOKEN")

        if self.enabled and not token:
            logger.warning(
                "SlackNotifier enabled but SLACK_BOT_TOKEN not set. "
                "Falling back to disabled mode."
            )
            self.enabled = False

        if self.enabled and not self.channel:
            logger.warning(
                "SlackNotifier enabled but no channel configured. "
                "Set SLACK_CHANNEL_ID or pass channel to constructor. "
                "Falling back to disabled mode."
            )
            self.enabled = False

        self._client = WebClient(token=token) if self.enabled else None

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def post_message(self, text: str, blocks: Optional[list] = None) -> None:
        """Post a text message to Slack.

        Parameters
        ----------
        text : str
            Plain text message (used as fallback for notifications).
        blocks : list, optional
            Slack Block Kit blocks for rich formatting.
        """
        if not self.enabled:
            return

        try:
            kwargs = {
                "channel": self.channel,
                "text": text,
            }
            if blocks:
                kwargs["blocks"] = blocks
            self._client.chat_postMessage(**kwargs)
            logger.debug("Slack message posted: %s", text[:80])
        except SlackApiError:
            logger.exception("Failed to post Slack message")
        except Exception:
            logger.exception("Unexpected error posting to Slack")

    def post_image(
        self,
        image_path: str,
        caption: str,
        title: Optional[str] = None,
    ) -> None:
        """Upload and post an image file to Slack.

        Parameters
        ----------
        image_path : str
            Path to the image file (PNG, JPEG, etc.).
        caption : str
            Text caption posted with the image.
        title : str, optional
            Title for the uploaded file. Defaults to the filename.
        """
        if not self.enabled:
            return

        path = Path(image_path)
        if not path.exists():
            logger.warning("Image file not found: %s", image_path)
            return

        try:
            self._client.files_upload_v2(
                channel=self.channel,
                file=str(path),
                title=title or path.name,
                initial_comment=caption,
            )
            logger.debug("Slack image uploaded: %s", path.name)
        except SlackApiError:
            logger.exception("Failed to upload image to Slack")
        except Exception:
            logger.exception("Unexpected error uploading image to Slack")

    def post_phase_complete(
        self,
        phase: str,
        experiment_name: str,
        metrics: dict,
        image_path: Optional[str] = None,
        llm_assessment: Optional[str] = None,
    ) -> None:
        """Post a formatted phase completion message.

        Parameters
        ----------
        phase : str
            Phase name (e.g., "Beamline Alignment", "Spectrometer Alignment").
        experiment_name : str
            Name of the current experiment.
        metrics : dict
            Phase metrics to display. Keys are metric names, values are
            strings or numbers (e.g., {"duration": "12m 34s", "scans": 8}).
        image_path : str, optional
            Path to a summary plot to upload with the message.
        llm_assessment : str, optional
            LLM-generated assessment text to include.
        """
        if not self.enabled:
            return

        # Build metrics text
        metrics_lines = []
        for key, value in metrics.items():
            label = key.replace("_", " ").title()
            metrics_lines.append(f"*{label}:* {value}")
        metrics_text = "\n".join(metrics_lines) if metrics_lines else "No metrics"

        blocks = [
            {"type": "divider"},
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Phase Complete: {phase}",
                },
            },
            _section_block(f"*Experiment:* {experiment_name}"),
            _section_block(metrics_text),
        ]

        if llm_assessment:
            blocks.append(
                _context_block(f"LLM Assessment: {llm_assessment}")
            )

        fallback_text = f"Phase complete: {phase} ({experiment_name})"
        self.post_message(fallback_text, blocks=blocks)

        # Upload image separately if provided
        if image_path:
            self.post_image(
                image_path,
                caption=f"{phase} summary",
                title=f"{experiment_name} - {phase}",
            )

    def post_alert(
        self,
        message: str,
        details: Optional[str] = None,
    ) -> None:
        """Post a red-flagged alert message.

        Parameters
        ----------
        message : str
            Short alert message.
        details : str, optional
            Additional details or context.
        """
        if not self.enabled:
            return

        blocks = [
            _section_block(f":red_circle: *ALERT:* {message}"),
        ]
        if details:
            blocks.append(_context_block(details))

        self.post_message(f"ALERT: {message}", blocks=blocks)

    def post_collection_progress(
        self,
        experiment_name: str,
        samples_done: int,
        samples_total: int,
        scans_done: int,
        scans_total: int,
        quality_note: Optional[str] = None,
    ) -> None:
        """Post a collection progress update.

        Parameters
        ----------
        experiment_name : str
            Name of the current experiment.
        samples_done : int
            Number of samples completed.
        samples_total : int
            Total number of samples.
        scans_done : int
            Number of scans completed (across all samples).
        scans_total : int
            Total number of scans planned.
        quality_note : str, optional
            Brief quality assessment to include.
        """
        if not self.enabled:
            return

        # Build progress bar
        if samples_total > 0:
            pct = samples_done / samples_total
            filled = int(pct * 10)
            bar = "\u2588" * filled + "\u2591" * (10 - filled)
            progress_str = f"`{bar}` {samples_done}/{samples_total} samples"
        else:
            progress_str = f"{samples_done} samples"

        blocks = [
            _section_block(
                f"*Collection Progress: {experiment_name}*\n"
                f"{progress_str}\n"
                f"Scans: {scans_done}/{scans_total}"
            ),
        ]

        if quality_note:
            blocks.append(_context_block(quality_note))

        fallback_text = (
            f"Collection: {experiment_name} - "
            f"{samples_done}/{samples_total} samples, "
            f"{scans_done}/{scans_total} scans"
        )
        self.post_message(fallback_text, blocks=blocks)


# ----------------------------------------------------------------------
# Block Kit helpers
# ----------------------------------------------------------------------

def _section_block(text: str) -> dict:
    """Create a Slack section block with mrkdwn text."""
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
    }


def _context_block(text: str) -> dict:
    """Create a Slack context block with mrkdwn text."""
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": text}],
    }
