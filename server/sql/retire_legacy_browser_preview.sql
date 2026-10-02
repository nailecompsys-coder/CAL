-- Idempotently revoke sessions created by the removed admin web Preview button.
UPDATE surgeon_devices
SET is_active = FALSE
WHERE device_name = 'Admin desktop preview'
  AND is_active IS DISTINCT FROM FALSE;
