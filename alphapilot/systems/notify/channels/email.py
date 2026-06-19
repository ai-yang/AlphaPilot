"""Email channel via stdlib smtplib (SSL or STARTTLS), HTML + plain text."""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from alphapilot.systems.notify.channels.base import BaseChannel, ChannelCapabilities, render_html, render_plaintext
from alphapilot.systems.notify.models import Message

_TIMEOUT = 20


class EmailChannel(BaseChannel):
    name = "email"
    capabilities = ChannelCapabilities()

    def _recipients(self) -> list[str]:
        recipients = self.conf.get("recipients") or []
        if isinstance(recipients, str):
            return [r.strip() for r in recipients.split(",") if r.strip()]
        return [str(r).strip() for r in recipients if str(r).strip()]

    def is_configured(self) -> bool:
        c = self.conf
        return bool(c.get("enabled") and c.get("host") and c.get("sender") and self._recipients())

    def send(self, message: Message) -> None:
        c = self.conf
        recipients = self._recipients()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"{message.emoji()} {message.title}".strip()
        msg["From"] = c["sender"]
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(render_plaintext(message), "plain", "utf-8"))
        msg.attach(MIMEText(f"<html><body>{render_html(message)}</body></html>", "html", "utf-8"))

        host = c["host"]
        port = int(c.get("port") or 465)
        use_ssl = bool(c.get("use_ssl", True))
        username = c.get("username") or c["sender"]
        password = c.get("password") or ""

        server = smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT) if use_ssl else smtplib.SMTP(host, port, timeout=_TIMEOUT)
        try:
            if not use_ssl:
                server.starttls()
            if password:
                server.login(username, password)
            server.sendmail(c["sender"], recipients, msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001 - quit best-effort
                pass
