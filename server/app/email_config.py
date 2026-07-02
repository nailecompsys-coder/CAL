from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str
    from_name: str
    enabled: bool

    @property
    def sender(self) -> str:
        return f"{self.from_name} <{self.user}>"


def load_smtp_config() -> SMTPConfig:
    return SMTPConfig(
        host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        port=int(os.environ.get("SMTP_PORT", "587")),
        user=os.environ.get("SMTP_USER", ""),
        password=os.environ.get("SMTP_PASS", ""),
        from_name=os.environ.get("SMTP_FROM_NAME", "Mid Florida Surgical"),
        enabled=os.environ.get("SMTP_ENABLED", "true").lower() == "true",
    )


SMTP_CONFIG = load_smtp_config()
