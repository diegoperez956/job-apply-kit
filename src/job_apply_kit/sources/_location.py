"""Keep explicit remote metadata in the location consumed by ranking."""

from __future__ import annotations


def remote_location(
    location: str, *, is_remote: object = None, workplace_type: object = None
) -> str:
    """Mark explicit remote postings, retaining the original geography.

    Accept only a boolean true flag or the remote workplace enum; missing,
    hybrid, onsite, and malformed metadata must not imply remote work.
    Existing remote labels are left unchanged.
    """
    remote = is_remote is True or (
        isinstance(workplace_type, str) and workplace_type.strip().casefold() == "remote"
    )
    if not remote or "remote" in location.casefold():
        return location
    return f"Remote - {location}" if location else "Remote"
