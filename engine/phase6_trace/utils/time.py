from datetime import datetime, timezone

def current_utc_time() -> str:
    """
    Return current UTC time in ISO 8601 format.
    Example: 2026-02-18T14:20:00Z
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
