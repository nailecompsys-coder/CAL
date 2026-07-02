"""JSON API endpoints for health and public configuration."""
from fastapi import APIRouter

from ..push import VAPID_PUBLIC_KEY

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/vapid-public-key")
def vapid_key():
    return {"publicKey": VAPID_PUBLIC_KEY}
