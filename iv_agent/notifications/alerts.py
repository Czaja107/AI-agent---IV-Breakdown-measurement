"""
Alert management and email notification.

Alerts are created by the agent, formatted here, and optionally sent as email.

SAFETY NOTE: Severity-4 alerts trigger an automatic run pause.  The email
system should be tested and validated before using with real hardware.
"""
from __future__ import annotations

import smtplib
import textwrap
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, TYPE_CHECKING

from rich.console import Console

from ..models.run_state import Alert, AlertSeverity

if TYPE_CHECKING:
    from ..config.schema import AgentConfig
    from ..models.device import DeviceRecord
    from ..models.run_state import RunState


console = Console()


class AlertManager:
    """
    Creates, formats, and dispatches alerts.

    Dispatch modes:
      SEV 1 — logged to console only
      SEV 2 — logged; added to end-of-run email if enabled
      SEV 3 — logged + immediate email (if enabled)
      SEV 4 — logged + immediate email + run pause
    """

    def __init__(self, config: "AgentConfig") -> None:
        self.config = config
        self._deferred_alerts: list[Alert] = []  # SEV 2 alerts for summary email

    def create_alert(
        self,
        run_state: "RunState",
        device: Optional["DeviceRecord"],
        severity: AlertSeverity,
        title: str,
        explanation: str,
        evidence: list[str],
        recent_context: str,
        recommended_action: str,
        hypotheses: list[str] | None = None,
    ) -> Alert:
        """Create a structured Alert record."""
        alert = Alert(
            alert_id=run_state.next_alert_id(),
            severity=severity,
            timestamp=datetime.now(),
            chip_id=run_state.chip_id,
            run_id=run_state.run_id,
            title=title,
            explanation=explanation,
            evidence=evidence,
            recent_context=recent_context,
            recommended_action=recommended_action,
            device_id=device.device_id if device else None,
            hypotheses_implicated=hypotheses or [],
        )
        return alert

    def dispatch(self, alert: Alert) -> None:
        """Log and optionally email the alert based on severity."""
        # Always log
        self._log_alert(alert)

        email_cfg = self.config.email
        if not email_cfg.enabled:
            return

        if alert.severity == AlertSeverity.SUMMARY:
            self._deferred_alerts.append(alert)
        elif alert.severity in (AlertSeverity.IMMEDIATE, AlertSeverity.PAUSE):
            self._send_email(alert)
            alert.email_sent = True

    def send_summary_email(self, run_state: "RunState") -> None:
        """Send end-of-run summary email with all deferred alerts."""
        if not self.config.email.enabled or not self._deferred_alerts:
            return
        # Build a combined message from deferred alerts + run summary
        body = self._format_summary_email(run_state, self._deferred_alerts)
        self._send_raw_email(
            subject=f"[IV-Agent] Run {run_state.run_id} complete — {run_state.chip_id}",
            body=body,
        )

    # -----------------------------------------------------------------------
    # Formatting
    # -----------------------------------------------------------------------

    def format_alert_text(self, alert: Alert) -> str:
        """Format an alert as a plain-text message for email or logging."""
        ev_lines = "\n".join(f"  • {e}" for e in alert.evidence)
        hyp_str = ", ".join(alert.hypotheses_implicated) or "None"
        return textwrap.dedent(f"""
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            SEVERITY {alert.severity.value} ALERT  [{alert.alert_id}]
            Chip: {alert.chip_id}  |  Run: {alert.run_id}
            Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
            Device: {alert.device_id or '(global)'}
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

            TITLE:
              {alert.title}

            EXPLANATION:
              {alert.explanation}

            EVIDENCE:
{ev_lines}

            RECENT CONTEXT:
              {alert.recent_context}

            ACTIVE HYPOTHESES:
              {hyp_str}

            RECOMMENDED ACTION:
              {alert.recommended_action}
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """).strip()

    def _format_summary_email(
        self, run_state: "RunState", alerts: list[Alert]
    ) -> str:
        alert_blocks = "\n\n".join(self.format_alert_text(a) for a in alerts)
        return (
            f"IV-Agent End-of-Run Summary\n"
            f"Chip: {run_state.chip_id}  Run: {run_state.run_id}\n"
            f"Devices: {run_state.n_devices_done}/{run_state.n_devices_total}\n"
            f"Healthy: {run_state.n_healthy}  Failed: {run_state.n_failed}  "
            f"Shorted: {run_state.n_shorted}  Contact: {run_state.n_contact_issue}\n\n"
            f"--- ALERTS ---\n\n"
            f"{alert_blocks}"
        )

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    def _log_alert(self, alert: Alert) -> None:
        colour = {
            AlertSeverity.LOG_ONLY: "dim",
            AlertSeverity.SUMMARY: "yellow",
            AlertSeverity.IMMEDIATE: "bold red",
            AlertSeverity.PAUSE: "bold red on white",
        }.get(alert.severity, "white")
        sep = "=" * 60
        console.print(
            f"\n[{colour}]"
            f"{sep}\n"
            f"  {alert.format_short()}\n"
            f"{sep}"
            f"[/{colour}]"
        )

    def _send_email(self, alert: Alert) -> None:
        """Send an immediate email for this alert."""
        subject = (
            f"[IV-Agent] SEV {alert.severity.value} — {alert.title[:50]} "
            f"| {alert.chip_id}/{alert.run_id}"
        )
        body = self.format_alert_text(alert)
        self._send_raw_email(subject=subject, body=body)

    def _send_raw_email(self, subject: str, body: str) -> None:
        """Low-level SMTP send."""
        email_cfg = self.config.email
        try:
            msg = MIMEMultipart()
            msg["From"] = email_cfg.sender
            msg["To"] = ", ".join(email_cfg.recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(email_cfg.smtp_server, email_cfg.smtp_port) as server:
                if email_cfg.use_tls:
                    server.starttls()
                if email_cfg.sender and email_cfg.password:
                    server.login(email_cfg.sender, email_cfg.password)
                server.sendmail(
                    email_cfg.sender, email_cfg.recipients, msg.as_string()
                )
            console.print("[dim]  [EMAIL] Alert email sent.[/dim]")
        except Exception as exc:
            console.print(f"[red]  [EMAIL] Email send failed: {exc}[/red]")
