"""Compatibility exports for admin settings services."""

from .admin_settings_backup_service import backup_result_url, restore_result_url
from .admin_settings_branding_service import remove_practice_logo, save_practice_settings
from .admin_settings_page_service import registered_surgeon_devices, rules_engine_settings, settings_backups
from .admin_settings_user_service import (
    add_admin_user,
    delete_admin_user,
    edit_admin_user,
    save_rule_config,
    set_admin_password,
    toggle_admin_user,
)

__all__ = [
    "add_admin_user",
    "backup_result_url",
    "delete_admin_user",
    "edit_admin_user",
    "registered_surgeon_devices",
    "remove_practice_logo",
    "restore_result_url",
    "rules_engine_settings",
    "save_practice_settings",
    "save_rule_config",
    "set_admin_password",
    "settings_backups",
    "toggle_admin_user",
]
