"""Shared dialog stylesheet hook."""


def _stylesheet(parent):
    return getattr(parent, "_dialog_stylesheet", lambda: "")()
