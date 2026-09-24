"""Café greetings — pure text, no Qt and no browser dependency.

These strings used to live in ``browser/new_tab_page.py``, which forced the data
layer (``services/brief_service.py``) to import from the browser layer. That was
the only services → browser edge in the codebase and it made the two packages
mutually dependent. The helper is plain text, so it belongs in ``core``, and the
browser module re-exports it for its own callers.
"""

CAFE_GREETINGS: dict[str, tuple[str, str]] = {
    "morning": ("Slow Start", "Warm cup, clear mind."),
    "noon": ("Midday Brew", "Focus fuel is served."),
    "afternoon": ("Golden Hour", "Pour a cup, stay a while."),
    "evening": ("Evening Wind-Down", "Low-tide light, soft foam."),
    "night": ("Late Decaf Call", "Closing time is quiet time."),
}


def greeting_period(hour: int) -> str:
    """Bucket an hour into one of the five café periods."""
    return (
        "night" if hour >= 22 or hour < 5 else
        "evening" if hour >= 18 else
        "afternoon" if hour >= 12 else
        "noon" if hour >= 11 else
        "morning"
    )


def cafe_greeting(hour: int | None = None) -> tuple[str, str]:
    """Return a (eyebrow, headline) greeting keyed to the local hour."""
    if hour is None:
        from datetime import datetime as _dt

        hour = _dt.now().hour
    return CAFE_GREETINGS[greeting_period(int(hour))]
