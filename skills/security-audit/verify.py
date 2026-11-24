"""Confirm a defensive finding only after an independent pass."""

def classify(repo_owned: bool, verifier_is_writer: bool, second_pass_verified: bool) -> str:
    if not repo_owned:
        return "stop"
    if verifier_is_writer or not second_pass_verified:
        return "unconfirmed"
    return "confirmed"


def scan_posture(
    repo_owned: bool,
    target_named: bool,
    active_requested: bool,
    *,
    authorized_target: bool = False,
) -> str:
    """Return stop, design-only, or authorized for this scan."""
    if not repo_owned and not authorized_target:
        return "stop"
    if active_requested and not target_named:
        return "stop"
    if active_requested and target_named and (repo_owned or authorized_target):
        return "authorized"
    return "design-only"
