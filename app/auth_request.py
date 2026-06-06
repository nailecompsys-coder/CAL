from __future__ import annotations

from fastapi import HTTPException, Request


def request_wants_json(request: Request) -> bool:
    accept = request.headers.get("Accept", "").lower()
    content_type = request.headers.get("Content-Type", "").lower()
    requested_with = request.headers.get("X-Requested-With", "")
    path = (request.scope.get("path") or request.url.path or "").lower()
    return (
        path.startswith("/api/")
        or path.startswith("api/")
        or "/api/" in path
        or "application/json" in accept
        or "application/json" in content_type
        or requested_with == "XMLHttpRequest"
    )


def raise_html_or_json_auth_error(request: Request, login_path: str) -> None:
    if request_wants_json(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    raise HTTPException(status_code=302, headers={"Location": login_path})
