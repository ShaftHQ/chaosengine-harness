"""Choose native tooling or an installed project pack for API client syntax."""


def route(pack_kind: str, addon_present: bool, denied: bool = False) -> str:
    """Return ``pack``, ``blocked``, or ``native``. Unknown kinds raise ValueError."""
    if denied or pack_kind == "none" or not pack_kind:
        return "native"
    if pack_kind == "core":
        return "pack" if addon_present else "blocked"
    if pack_kind == "user":
        return "pack" if addon_present else "blocked"
    raise ValueError(f"unknown pack_kind: {pack_kind!r}")
