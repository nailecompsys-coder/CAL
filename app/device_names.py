from __future__ import annotations


def readable_device_name(device_name: str | None, user_agent: str | None = None) -> str:
    source = " ".join(part for part in [device_name, user_agent] if part).strip()
    if not source:
        return "Unknown device"

    lowered = source.lower()
    if "cal admin preview" in lowered or "admin desktop preview" in lowered:
        return "Admin preview"
    if "calnative" in lowered and ("darwin" in lowered or "cfnetwork" in lowered):
        return "CAL iPhone app"
    if "calnative" in lowered and ("okhttp" in lowered or "android" in lowered):
        return "CAL Android app"
    if "okhttp" in lowered:
        return "Android app"
    if "iphone" in lowered:
        return "iPhone browser"
    if "ipad" in lowered:
        return "iPad browser"
    if "android" in lowered:
        return "Android browser"
    if "macintosh" in lowered or "mac os" in lowered:
        return "Mac browser"
    if "windows" in lowered:
        return "Windows browser"
    if lowered.startswith("curl/"):
        return "API test client"
    if "unknown device" in lowered:
        return "Unknown device"
    return device_name or "Unknown device"
