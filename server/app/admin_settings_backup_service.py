from __future__ import annotations

import urllib.parse


def backup_result_url(result: dict) -> str:
    if result.get("success") and result.get("wasabi_ok"):
        timestamp = result.get("timestamp", "")
        return (
            f"/admin/settings/backup?msg=backup_ok&ts={urllib.parse.quote(timestamp)}"
            if timestamp
            else "/admin/settings/backup?msg=backup_ok"
        )
    if result.get("success") and not result.get("wasabi_ok"):
        return "/admin/settings/backup?msg=backup_upload_failed"
    err = result.get("error", "Backup failed")
    return "/admin/settings/backup?msg=backup_failed&err=" + urllib.parse.quote(err[:200])


def restore_result_url(result: dict) -> str:
    if result.get("success"):
        return "/admin/settings/backup?msg=restore_ok"
    err = result.get("error", "Restore failed")
    return "/admin/settings/backup?msg=restore_failed&err=" + urllib.parse.quote(err[:200])
