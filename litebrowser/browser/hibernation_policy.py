"""Whether a tab's renderer may be discarded, and why it may not.

Hibernation releases a Chromium renderer. The URL survives; the page's live
state does not. Anything typed into an unsaved form, a SPA's in-memory state,
an open dialog, an upload in progress, a call in a WebSocket and the current
scroll position are all lost when the renderer goes away, and no browser can
recreate them from outside.

Mei used to hibernate any background tab that had been idle for N seconds,
including tabs that were playing audio or in the middle of a download. This
module is the gate: it answers "is discarding this tab safe?" and returns the
reason when it is not. The rule is conservative on purpose — when a state
cannot be determined, the tab is **not** hibernated. Losing a tab is cheap;
losing a half-written message is not.

Pure functions only (no Qt) so the policy is testable without a display.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Reasons, most specific first. Empty string means "safe to hibernate".
REASON_ACTIVE = "active"
REASON_PINNED = "pinned"
REASON_NEVER = "never_hibernate"
REASON_INCOGNITO = "incognito"
REASON_AUDIBLE = "audible"
REASON_NAVIGATING = "navigating"
REASON_DOWNLOAD = "download"
REASON_TOO_SOON = "recently_active"


@dataclass(frozen=True)
class TabState:
    """The facts the policy is allowed to consider.

    Defaults describe a quiet, ordinary background tab. Every flag that means
    "work may be in progress" defaults to the *safe* answer for that field.
    """

    is_active: bool = False
    is_pinned: bool = False
    never_hibernate: bool = False
    is_incognito: bool = False
    is_audible: bool = False
    is_navigating: bool = False
    has_active_download: bool = False
    ms_since_last_active: int = -1  # -1 = unknown
    is_hibernated: bool = False


def hibernate_block_reason(state: TabState, idle_seconds: int) -> str:
    """Return "" when hibernating is safe, else the first blocking reason.

    ``idle_seconds <= 0`` disables automatic hibernation entirely, matching the
    existing preference. ``ms_since_last_active`` of -1 means the caller could
    not measure idleness; that is treated as *not idle* rather than as idle.
    """
    if state.is_hibernated:
        return "already_hibernated"
    if state.is_active:
        return REASON_ACTIVE
    if state.is_pinned:
        return REASON_PINNED
    if state.never_hibernate:
        return REASON_NEVER
    if state.is_incognito:
        # A private tab's renderer holds state that must never be written to a
        # durable profile. Hibernating it would require persisting something;
        # refuse instead of inventing a private-session snapshot.
        return REASON_INCOGNITO
    if state.is_audible:
        return REASON_AUDIBLE
    if state.is_navigating:
        return REASON_NAVIGATING
    if state.has_active_download:
        return REASON_DOWNLOAD
    if idle_seconds <= 0:
        return "disabled"
    if state.ms_since_last_active < 0:
        return REASON_TOO_SOON
    if state.ms_since_last_active < int(idle_seconds) * 1000:
        return REASON_TOO_SOON
    return ""


def describe_reason(reason: str) -> str:
    """One short, user-facing sentence for a blocked hibernate attempt."""
    return {
        REASON_ACTIVE: "This tab is active.",
        REASON_PINNED: "Pinned tabs are never hibernated.",
        REASON_NEVER: "This tab is marked to never hibernate.",
        REASON_INCOGNITO: "Private tabs are never hibernated automatically.",
        REASON_AUDIBLE: "Audio is playing in this tab.",
        REASON_NAVIGATING: "The tab is still navigating.",
        REASON_DOWNLOAD: "A download is running in this tab.",
        REASON_TOO_SOON: "The tab was used too recently.",
        "disabled": "Automatic hibernation is turned off.",
        "already_hibernated": "The tab is already hibernated.",
    }.get(reason, "This tab may be doing work that hibernation would discard.")


__all__ = [
    "REASON_ACTIVE",
    "REASON_AUDIBLE",
    "REASON_DOWNLOAD",
    "REASON_INCOGNITO",
    "REASON_NAVIGATING",
    "REASON_NEVER",
    "REASON_PINNED",
    "REASON_TOO_SOON",
    "TabState",
    "describe_reason",
    "hibernate_block_reason",
]
