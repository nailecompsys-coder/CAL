"""
Wasabi S3 backup/restore for Cal — surgical_cal DB.
Uses same env pattern as SSS: WASABI_BUCKET, WASABI_KEY_ID, WASABI_SECRET, WASABI_ENDPOINT.
Prefix: cal-backups/ (so same bucket as SSS can be used).
"""
import os
import subprocess
import tempfile
from datetime import datetime

from botocore.exceptions import ClientError

from .wasabi_config import WASABI_CONFIG, parse_database_url, s3_client
from .wasabi_postgres import dump_database_to_gzip, restore_database_from_gzip

WASABI_BUCKET = WASABI_CONFIG.bucket
WASABI_KEY_ID = WASABI_CONFIG.key_id
WASABI_SECRET = WASABI_CONFIG.secret
WASABI_ENDPOINT_RAW = WASABI_CONFIG.endpoint_raw
WASABI_REGION = WASABI_CONFIG.region

BACKUP_PREFIX = "cal-backups/"


def _wasabi_endpoint() -> str:
    """Return a valid Wasabi endpoint URL. Regional format preferred (s3.REGION.wasabisys.com)."""
    return WASABI_CONFIG.endpoint


def _s3_client():
    return s3_client(WASABI_CONFIG)


def is_configured() -> bool:
    return WASABI_CONFIG.is_configured


def _parse_database_url():
    return parse_database_url()


def list_backups() -> list[dict]:
    """List backup folders (cal-backups/YYYYMMDD-HHMMSS/) and their files."""
    if not is_configured():
        return []
    try:
        client = _s3_client()
        paginator = client.get_paginator("list_objects_v2")
        by_ts = {}
        for page in paginator.paginate(Bucket=WASABI_BUCKET, Prefix=BACKUP_PREFIX):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == BACKUP_PREFIX or not key.startswith(BACKUP_PREFIX):
                    continue
                parts = key[len(BACKUP_PREFIX) :].split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    continue
                ts, fname = parts
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
        error = dump_database_to_gzip(db, dbfile)
        if error:
            return {"success": False, "error": f"pg_dump failed: {error}"}
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
        error = restore_database_from_gzip(db, local_gz)
        if error:
            return {"success": False, "error": error}
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
