"""Safe, bounded diagnostics for optional Azure services."""

import os
import re


def safe_error_text(value, *credentials: str, limit: int = 600) -> str:
    text = str(value)
    secrets = {
        secret for name, secret in os.environ.items()
        if name.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")) and secret
    }
    secrets.update(secret for secret in credentials if secret)
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)(Bearer\s+)[^\s\"'<>]+", r"\1[redacted]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[redacted]", text)
    return " ".join(text.split())[:limit]
