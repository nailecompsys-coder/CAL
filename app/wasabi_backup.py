"""
Wasabi S3 backup/restore for Cal — surgical_cal DB.
Uses same env pattern as SSS: WASABI_BUCKET, WASABI_KEY_ID, WASABI_SECRET, WASABI_ENDPOINT.
Prefix: cal-backups/ (so same bucket as SSS can be used).
"""
import gzip
import os
import subprocess
import tempfile
from datetime import datetime
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Wasabi (S3-compatible) config — same env vars as SSS
WASABI_BUCKET = os.environ.get("WASABI_BUCKET", "mfsa-cal").strip()
WASABI_KEY_ID = os.environ.get("WASABI_KEY_ID", "").strip()
WASABI_SECRET = os.environ.get("WASABI_SECRET", "").strip()
WASABI_ENDPOINT_RAW = os.environ.get("WASABI_ENDPOINT", "").strip()
WASABI_REGION = os.environ.get("WASABI_REGION", "us-east-1").strip()

BACKUP_PREFIX = "cal-backups/"


def _wasabi_endpoint() -> str:
    """Return a valid Wasabi endpoint URL. Regional format preferred (s3.REGION.wasabisys.com)."""
    if WASABI_ENDPOINT_RAW:
        url = WASABI_ENDPOINT_RAW
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        return url.rstrip("/")
    # Default: regional endpoint per Wasabi docs (avoids "Invalid endpoint" with generic s3.wasabisys.com)
    return f"https://s3.{WASABI_REGION}.wasabisys.com"


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=_wasabi_endpoint(),
        region_name=WASABI_REGION,
        aws_access_key_id=WASABI_KEY_ID,
        aws_secret_access_key=WASABI_SECRET,
        config=Config(signature_version="s3v4"),
    )


def is_configured() -> bool:
    return bool(WASABI_KEY_ID and WASABI_SECRET and WASABI_BUCKET)


def _parse_database_url():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return None
    # postgresql://user:pass@host:port/dbname
    if url.startswith("postgres://"):
        url = "postgresql://" + url[11:]
    r = urlparse(url)
    return {
        "host": r.hostname or "localhost",
        "port": r.port or 5432,
        "user": r.username,
        "password": r.password or "",
        "dbname": (r.path or "").lstrip("/").split("?")[0] or "surgical_cal",
    }


def list_backups() -> list[dict]:
    """List backup folders (cal-backups/YYYYMMDD-HHMMSS/) and their files."""
    if not is_configured():
        return []
    try:
        client = _s3_client()
        paginator = client.get_paginator("list_objects_v2")
        by_ts = {}
        for page in paginator.paginate(Bucket=WASABI_BUCKET, Prefix=BACKUP_PREFIX, Delimiter="/"):
            for prefix in page.get("CommonPrefixes", []):
                # e.g. cal-backups/20260316-140000/
                p = prefix["Prefix"]
                if p.startswith(BACKUP_PREFIX) and p != BACKUP_PREFIX:
                    ts = p[len(BACKUP_PREFIX) :].rstrip("/")
                    if ts and ts not in by_ts:
                        by_ts[ts] = {"timestamp": ts, "files": [], "total_bytes": 0}
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == BACKUP_PREFIX or not key.startswith(BACKUP_PREFIX):
                    continue
                parts = key[len(BACKUP_PREFIX) :].split("/")
                if len(parts) >= 2:
                    ts = parts[0]
                    fname = parts[1]
                    size = obj.get("Size", 0)
                    if ts not in by_ts:
                        by_ts[ts] = {"timestamp": ts, "files": [], "total_bytes": 0}
                    by_ts[ts]["files"].append({"name": fname, "size": size, "key": key})
                    by_ts[ts]["total_bytes"] += size
        return sorted(by_ts.values(), key=lambda b: b["timestamp"], reverse=True)
    except Exception:
        return []


def run_backup() -> dict:
    """
    pg_dump surgical_cal -> gzip -> upload to Wasabi.
    Returns dict with success, timestamp, wasabi_key, wasabi_error, etc.
    """
    db = _parse_database_url()
    if not db:
        return {"success": False, "error": "DATABASE_URL not set"}
    if not is_configured():
        return {"success": False, "error": "Wasabi credentials not configured"}
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    wasabi_key = f"{BACKUP_PREFIX}{ts}/db.sql.gz"
    tmpdir = tempfile.mkdtemp(prefix="cal_backup_")
    dbfile = os.path.join(tmpdir, "db.sql.gz")
    try:
        env = os.environ.copy()
        env["PGPASSWORD"] = db["password"] or ""
        cmd = [
            "pg_dump",
            "-h", db["host"],
            "-p", str(db["port"]),
            "-U", db["user"],
            "--no-owner",
            "--clean",
            "--if-exists",
            db["dbname"],
        ]
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        gz = gzip.open(dbfile, "wb", compresslevel=6)
        gz.writelines(proc.stdout)
        gz.close()
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
        proc.wait(timeout=300)
        if proc.returncode != 0:
            return {"success": False, "error": f"pg_dump failed: {stderr[:500]}"}
        size = os.path.getsize(dbfile)
        client = _s3_client()
        client.upload_file(
            dbfile,
            WASABI_BUCKET,
            wasabi_key,
            ExtraArgs={"ContentType": "application/gzip"},
        )
        return {
            "success": True,
            "timestamp": ts,
            "wasabi_key": wasabi_key,
            "db_size_bytes": size,
            "wasabi_ok": True,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "pg_dump timed out"}
    except ClientError as e:
        return {
            "success": True,
            "timestamp": ts,
            "wasabi_key": wasabi_key,
            "wasabi_ok": False,
            "wasabi_error": str(e),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            if os.path.exists(dbfile):
                os.remove(dbfile)
            os.rmdir(tmpdir)
        except Exception:
            pass


def restore_backup(wasabi_key: str, admin_password: str, confirm: str) -> dict:
    """
    Download backup from Wasabi, gunzip, restore via psql.
    Requires confirm == "RESTORE". admin_password is verified by caller.
    """
    if confirm != "RESTORE":
        return {"success": False, "error": "Type RESTORE to confirm."}
    if not wasabi_key or not wasabi_key.startswith(BACKUP_PREFIX):
        return {"success": False, "error": "Invalid backup key."}
    if not is_configured():
        return {"success": False, "error": "Wasabi credentials not configured."}
    db = _parse_database_url()
    if not db:
        return {"success": False, "error": "DATABASE_URL not set"}
    tmpdir = tempfile.mkdtemp(prefix="cal_restore_")
    local_gz = os.path.join(tmpdir, "restore.sql.gz")
    try:
        client = _s3_client()
        client.download_file(WASABI_BUCKET, wasabi_key, local_gz)
        env = os.environ.copy()
        env["PGPASSWORD"] = db["password"] or ""
        # gunzip -c file | psql ...
        with gzip.open(local_gz, "rb") as f:
            proc = subprocess.Popen(
                [
                    "psql",
                    "-h", db["host"],
                    "-p", str(db["port"]),
                    "-U", db["user"],
                    "-d", db["dbname"],
                    "--no-password",
                ],
                stdin=subprocess.PIPE,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = proc.communicate(input=f.read(), timeout=300)
        if proc.returncode != 0:
            return {"success": False, "error": (stderr or stdout).decode("utf-8", errors="replace")[:500]}
        return {"success": True, "restored_from": wasabi_key}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Restore timed out"}
    except ClientError as e:
        return {"success": False, "error": f"Download failed: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            if os.path.exists(local_gz):
                os.remove(local_gz)
            os.rmdir(tmpdir)
        except Exception:
            pass
