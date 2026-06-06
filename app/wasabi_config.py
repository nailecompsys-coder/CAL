from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

import boto3
from botocore.config import Config


@dataclass(frozen=True)
class WasabiConfig:
    bucket: str
    key_id: str
    secret: str
    endpoint_raw: str
    region: str

    @property
    def endpoint(self) -> str:
        if self.endpoint_raw:
            url = self.endpoint_raw
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url
            return url.rstrip("/")
        return f"https://s3.{self.region}.wasabisys.com"

    @property
    def is_configured(self) -> bool:
        return bool(self.key_id and self.secret and self.bucket)


def load_wasabi_config() -> WasabiConfig:
    return WasabiConfig(
        bucket=os.environ.get("WASABI_BUCKET", "mfsa-cal").strip(),
        key_id=os.environ.get("WASABI_KEY_ID", "").strip(),
        secret=os.environ.get("WASABI_SECRET", "").strip(),
        endpoint_raw=os.environ.get("WASABI_ENDPOINT", "").strip(),
        region=os.environ.get("WASABI_REGION", "us-east-1").strip(),
    )


def parse_database_url():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    if url.startswith("postgres://"):
        url = "postgresql://" + url[11:]
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password or "",
        "dbname": (parsed.path or "").lstrip("/").split("?")[0] or "surgical_cal",
    }


def s3_client(config: WasabiConfig):
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint,
        region_name=config.region,
        aws_access_key_id=config.key_id,
        aws_secret_access_key=config.secret,
        config=Config(signature_version="s3v4"),
    )


WASABI_CONFIG = load_wasabi_config()
