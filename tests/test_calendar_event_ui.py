"""Calendar event creation must not raise from the dialog slot."""
import os
import tempfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import litebrowser  # noqa: E402,F401
from litebrowser.qt import QtCore, QtWidgets  # noqa: E402
from litebrowser.core import prefs  # noqa: E402
from litebrowser.services import life_service  # noqa: E402
from litebrowser.ui import personal_window as pw  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["calendar-event-tests"])


def test_add_event_persists_the_selected_date_and_time():
    with tempfile.TemporaryDirectory() as temp:
        base = prefs.ensure_profile_layout(temp)
        window = pw.PersonalWindow(base, embedded=True)
        selected = QtCore.QDate(2026, 11, 10)
        window.calendar_widget.setSelectedDate(selected)

        with mock.patch.object(
            pw.QInputDialog, "getText", return_value=("Study group", True)
        ), mock.patch.object(
            pw.QDialog, "exec_", return_value=pw.QDialog.DialogCode.Accepted
        ):
            window._add_event()

        events = life_service.load_events(base)
        assert len(events) == 1
        assert events[0]["title"] == "Study group"
        assert events[0]["starts_at"] == QtCore.QDateTime(
            selected, QtCore.QTime(9, 0)
        ).toSecsSinceEpoch()
        assert window.day_events_list.count() == 1

        window.close()
        window.deleteLater()
        app.processEvents()
