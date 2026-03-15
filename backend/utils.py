"""Shared utilities — avoid duplicate definitions across modules."""
import os
import re
import hmac
from fastapi import Header, HTTPException


def verify_admin(x_admin_key: str = Header(None)):
    """Verify admin key via HMAC-safe comparison. Reads ADMIN_KEY at call time."""
    admin_key = os.getenv("ADMIN_KEY", "")
    if not x_admin_key or not admin_key or not hmac.compare_digest(x_admin_key, admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")


def strip_html(text: str) -> str:
    """Remove HTML tags from user input (defense-in-depth)."""
    return re.sub(r'<[^>]+>', '', text)
