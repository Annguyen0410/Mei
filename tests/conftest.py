"""Suite-wide defaults: offscreen Qt, and no test ever polls a live server.

``AppShell`` performs an update check on startup, and that check now points at the
GitHub release channel — a real HTTP request inside every test that builds the
shell (and, on a machine with no internet, a real timeout: a subprocess probe hit
its 120 s limit because of it). Blanking the channel URL makes
``update_service.check_for_updates`` fail immediately with "update server is not
configured", which is exactly what a fork with no channel sees, and it propagates
to probes launched with ``subprocess.run`` because they inherit this environment.

The channel logic itself is still covered, against fixtures and mocked readers, by
``test_update_identity.py`` and ``test_publish_release.py``.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LITEBROWSER_UPDATE_METADATA_URL"] = ""
