"""Settings → Data Management.

Small, explicit controls for the recovery services.  Long operations (backup,
scan, restore) run on a QThread so the shell stays responsive; every destructive
action asks for confirmation and reports the exact artifact or failure.
"""
from __future__ import annotations

import json

from litebrowser.qt import QtCore, QtWidgets

Qt = QtCore.Qt
QThread = QtCore.QThread
pyqtSignal = QtCore.pyqtSignal
QCheckBox = QtWidgets.QCheckBox
QComboBox = QtWidgets.QComboBox
QDialog = QtWidgets.QDialog
QFileDialog = QtWidgets.QFileDialog
QHBoxLayout = QtWidgets.QHBoxLayout
QInputDialog = QtWidgets.QInputDialog
QLabel = QtWidgets.QLabel
QLineEdit = QtWidgets.QLineEdit
QListWidget = QtWidgets.QListWidget
QListWidgetItem = QtWidgets.QListWidgetItem
QMessageBox = QtWidgets.QMessageBox
QPushButton = QtWidgets.QPushButton
QTabWidget = QtWidgets.QTabWidget
QTextEdit = QtWidgets.QTextEdit
QVBoxLayout = QtWidgets.QVBoxLayout

from litebrowser.core import prefs
from litebrowser.services import (
    backup_service,
    conflict_service,
    encrypted_backup_service,
    integrity_service,
    record_restore_service,
    recovery_service,
    restore_service,
    safe_http,
)
from litebrowser.ui.dialogs.common import _stylesheet, ghost_button, primary_button


class _Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, function):
        super().__init__()
        self.function = function

    def run(self):
        try:
            self.done.emit(self.function())
        except Exception as exc:  # reported to the user, never swallowed
            self.failed.emit(str(exc))


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return text[:4000] + ("\n…" if len(text) > 4000 else "")


class DataManagementDialog(QDialog):
    def __init__(self, base_dir: str, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self._workers: list[_Worker] = []
        self.policy = backup_service.load_policy(base_dir)
        self.setWindowTitle("Data Management — Mei")
        self.resize(880, 620)
        self.setStyleSheet(_stylesheet(parent))
        layout = QVBoxLayout(self)
        title = QLabel("Data Management")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        note = QLabel(
            "Backups are independent of folder sync. Secrets, Chromium profile data, "
            "downloads and Incognito data are never included. Restores create a "
            "pre-restore backup and can be rolled back."
        )
        note.setWordWrap(True)
        note.setObjectName("MutedLabel")
        layout.addWidget(note)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_backups()
        self._build_restore()
        self._build_record_restore()
        self._build_integrity()
        self._build_conflicts()
        self._build_health()
        self._build_recovery()
        self._build_proxy()
        close = ghost_button("Close")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)
        layout.addLayout(footer)
        self.refresh_all()

    # ------------------------------------------------------------------ #
    def _run(self, function, on_done, message: str = ""):
        worker = _Worker(function)
        self._workers.append(worker)
        worker.done.connect(on_done)

        def failed(text):
            QMessageBox.warning(self, "Data Management", text or "The operation failed.")

        worker.failed.connect(failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()
        return worker

    def refresh_all(self):
        self.refresh_backups()
        self.refresh_record_backups()
        self.refresh_conflicts()
        self.refresh_health()
        self.refresh_recovery()
        self.refresh_proxy()

    # ------------------------------- backups -------------------------- #
    def _build_backups(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        self.lbl_backup_status = QLabel("")
        self.lbl_backup_status.setWordWrap(True)
        layout.addWidget(self.lbl_backup_status)
        self.list_backups = QListWidget()
        layout.addWidget(self.list_backups, 1)
        row = QHBoxLayout()
        self.btn_create_backup = primary_button("Create backup now")
        self.btn_encrypt_backup = ghost_button("Create encrypted backup…")
        self.btn_verify_backup = ghost_button("Verify selected")
        self.btn_retention = ghost_button("Apply retention")
        self.btn_destination = ghost_button("Change destination…")
        for button in (
            self.btn_create_backup,
            self.btn_encrypt_backup,
            self.btn_verify_backup,
            self.btn_retention,
            self.btn_destination,
        ):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.btn_create_backup.clicked.connect(self.create_backup)
        self.btn_encrypt_backup.clicked.connect(self.create_encrypted_backup)
        self.btn_verify_backup.clicked.connect(self.verify_backup)
        self.btn_retention.clicked.connect(self.apply_retention)
        self.btn_destination.clicked.connect(self.change_destination)
        self.tabs.addTab(tab, "Backups")

    def refresh_backups(self):
        rows = backup_service.list_backups(self.policy.destination, verify=False)
        self.list_backups.clear()
        for row in rows:
            label = (
                f"{row['name']} · {row.get('status', 'unknown')} · "
                f"{row['size'] // 1024} KiB"
            )
            if row.get("encrypted"):
                label = "[encrypted] " + label
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, row["path"])
            self.list_backups.addItem(item)
        status = backup_service.status(self.base_dir)
        self.lbl_backup_status.setText(
            f"Destination: {status['destination']}\n"
            f"Last backup: {status['last_backup_at'] or 'never'} · "
            f"{status['backup_count']} archive(s) ({status.get('encrypted_count', 0)} encrypted) · {status['frequency']} "
            f"(daily {status['retention']['daily']}, weekly {status['retention']['weekly']}, "
            f"monthly {status['retention']['monthly']})"
        )

    def _selected_backup(self) -> str:
        item = self.list_backups.currentItem()
        return str(item.data(Qt.UserRole)) if item else ""

    def create_backup(self):
        self.btn_create_backup.setEnabled(False)

        def done(result):
            self.btn_create_backup.setEnabled(True)
            if result.ok:
                QMessageBox.information(self, "Backup", f"Verified backup created:\n{result.path}")
            else:
                QMessageBox.warning(self, "Backup", result.error or "Backup failed.")
            self.refresh_backups()

        self._run(lambda: backup_service.create_backup(self.base_dir), done)

    def create_encrypted_backup(self):
        password, ok = QInputDialog.getText(
            self,
            "Encrypted backup",
            f"Password (at least {encrypted_backup_service.MIN_PASSWORD_CHARS} characters):",
            QLineEdit.Password,
        )
        if not ok or not password:
            return
        confirm, ok = QInputDialog.getText(
            self,
            "Encrypted backup",
            "Repeat the password:",
            QLineEdit.Password,
        )
        if not ok or confirm != password:
            QMessageBox.warning(self, "Encrypted backup", "The passwords do not match.")
            return
        self.btn_encrypt_backup.setEnabled(False)

        def done(result):
            self.btn_encrypt_backup.setEnabled(True)
            if result.ok:
                QMessageBox.information(
                    self,
                    "Encrypted backup",
                    f"Verified encrypted backup created:\n{result.path}\n\n"
                    "The password is not stored. If it is lost, this backup cannot be opened.",
                )
            else:
                QMessageBox.warning(self, "Encrypted backup", result.error or "Backup failed.")
            self.refresh_backups()

        self._run(
            lambda: encrypted_backup_service.create_encrypted_backup(
                self.base_dir, password
            ),
            done,
        )

    def _password_for_backup(self, path: str):
        if not path.endswith(backup_service.ENCRYPTED_EXTENSION):
            return ""
        password, ok = QInputDialog.getText(
            self,
            "Encrypted backup",
            "Password:",
            QLineEdit.Password,
        )
        return password if ok and password else None

    def verify_backup(self):
        path = self._selected_backup()
        if not path:
            return
        password = self._password_for_backup(path)
        if password is None:
            return
        if path.endswith(backup_service.ENCRYPTED_EXTENSION):
            checked = encrypted_backup_service.verify_encrypted(path, password)
        else:
            checked = backup_service.verify_backup(path)
        if checked["ok"]:
            QMessageBox.information(self, "Backup", "Manifest, paths, sizes and checksums are valid.")
        else:
            QMessageBox.warning(self, "Backup", "\n".join(checked["errors"]) or "Backup is invalid.")

    def apply_retention(self):
        deleted = backup_service.apply_retention(self.policy.destination, self.policy)
        QMessageBox.information(
            self,
            "Retention",
            f"Removed {len(deleted)} old verified backup(s); the newest verified backup was kept.",
        )
        self.refresh_backups()

    def change_destination(self):
        chosen = QFileDialog.getExistingDirectory(self, "Backup destination", self.policy.destination)
        if not chosen:
            return
        if not backup_service.destination_is_separate(self.base_dir, chosen):
            QMessageBox.warning(self, "Backup", "Choose a folder outside the active profile.")
            return
        updated = backup_service.BackupPolicy(
            destination=chosen,
            enabled=self.policy.enabled,
            frequency=self.policy.frequency,
            daily_keep=self.policy.daily_keep,
            weekly_keep=self.policy.weekly_keep,
            monthly_keep=self.policy.monthly_keep,
        )
        backup_service.save_policy(self.base_dir, updated)
        self.policy = updated
        self.refresh_all()

    # ------------------------------- restore -------------------------- #
    def _build_restore(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Choose a verified backup, then preview before restoring."))
        self.list_restore = QListWidget()
        layout.addWidget(self.list_restore, 1)
        self.category_boxes: list[QCheckBox] = []
        categories = QVBoxLayout()
        for group in restore_service.ALL_GROUPS:
            box = QCheckBox(group.replace("_", " "))
            box.setChecked(True)
            categories.addWidget(box)
            self.category_boxes.append(box)
        layout.addLayout(categories)
        self.restore_preview = QTextEdit()
        self.restore_preview.setReadOnly(True)
        layout.addWidget(self.restore_preview, 1)
        row = QHBoxLayout()
        self.btn_preview = primary_button("Preview")
        self.btn_restore = ghost_button("Restore selected")
        row.addWidget(self.btn_preview)
        row.addWidget(self.btn_restore)
        row.addStretch(1)
        layout.addLayout(row)
        self.btn_preview.clicked.connect(self.preview_restore)
        self.btn_restore.clicked.connect(self.do_restore)
        self.tabs.addTab(tab, "Restore Center")

    def _restore_categories(self):
        selected = [box.text().replace(" ", "_") for box in self.category_boxes if box.isChecked()]
        return selected or None

    def _selected_restore_backup(self) -> str:
        item = self.list_restore.currentItem()
        return str(item.data(Qt.UserRole)) if item else self._selected_backup()

    def _load_restore_list(self):
        self.list_restore.clear()
        for row in backup_service.list_backups(self.policy.destination, verify=False):
            label = f"{row['name']} · {row.get('created_at', 0)}"
            if row.get("encrypted"):
                label = "[encrypted] " + label
            elif not row.get("verified"):
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, row["path"])
            self.list_restore.addItem(item)

    def preview_restore(self):
        path = self._selected_restore_backup()
        if not path:
            QMessageBox.information(self, "Restore", "Select a verified backup first.")
            return
        password = self._password_for_backup(path)
        if password is None:
            return
        plan = restore_service.preview(
            self.base_dir, path, categories=self._restore_categories(), password=password
        )
        if not plan.get("ok"):
            QMessageBox.warning(self, "Restore", plan.get("error", "Invalid backup."))
            return
        lines = [
            f"Added: {plan['totals']['added']} · Replaced: {plan['totals']['replaced']} "
            f"· Unchanged: {plan['totals']['unchanged']}",
            "",
        ]
        for row in plan["files"]:
            lines.append(
                f"{row['action']}: {row['path']} "
                f"(backup records={row.get('backup_records')}, current={row.get('current_records')})"
            )
        if plan.get("warnings"):
            lines.append("\nWarnings:\n" + "\n".join(plan["warnings"]))
        self.restore_preview.setPlainText("\n".join(lines))

    def do_restore(self):
        path = self._selected_restore_backup()
        if not path:
            QMessageBox.information(self, "Restore", "Select a verified backup first.")
            return
        categories = self._restore_categories()
        password = self._password_for_backup(path)
        if password is None:
            return
        if QMessageBox.Yes != QMessageBox.question(
            self,
            "Restore",
            "This replaces the selected categories. A pre-restore backup is created first. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ):
            return
        self.btn_restore.setEnabled(False)

        def done(result):
            self.btn_restore.setEnabled(True)
            self.refresh_backups()
            if result.ok:
                QMessageBox.information(
                    self,
                    "Restore",
                    f"Restored {len(result.restored)} file(s).\nPre-restore backup:\n{result.pre_restore_backup}",
                )
            else:
                QMessageBox.warning(self, "Restore", result.error or result.status)

        self._run(
            lambda: restore_service.restore(
                self.base_dir, path, categories=categories, confirm=True, password=password
            ),
            done,
        )

    # --------------------------- record restore ----------------------- #
    def _build_record_restore(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        layout.addWidget(
            QLabel(
                "Recover one record through its normal store writer. A full pre-restore "
                "backup is created first; restoring over an existing record requires confirmation."
            )
        )
        row = QHBoxLayout()
        self.record_backup = QComboBox()
        self.record_store = QComboBox()
        for key in record_restore_service.SUPPORTED_STORES:
            label = record_restore_service.ADAPTERS[key].label if key in record_restore_service.ADAPTERS else "Notes"
            self.record_store.addItem(label, key)
        row.addWidget(QLabel("Backup:"))
        row.addWidget(self.record_backup, 2)
        row.addWidget(QLabel("Store:"))
        row.addWidget(self.record_store, 1)
        layout.addLayout(row)
        self.record_filter = QLineEdit()
        self.record_filter.setPlaceholderText("Filter records by title or id…")
        layout.addWidget(self.record_filter)
        self.record_list = QListWidget()
        self.record_list.currentItemChanged.connect(self.preview_record)
        layout.addWidget(self.record_list, 1)
        self.record_preview = QTextEdit()
        self.record_preview.setReadOnly(True)
        layout.addWidget(self.record_preview, 1)
        buttons = QHBoxLayout()
        self.btn_record_load = ghost_button("Load records")
        self.btn_record_replace = primary_button("Restore selected")
        self.btn_record_new = ghost_button("Restore as new")
        buttons.addWidget(self.btn_record_load)
        buttons.addWidget(self.btn_record_replace)
        buttons.addWidget(self.btn_record_new)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.btn_record_load.clicked.connect(self.load_record_choices)
        self.record_backup.currentIndexChanged.connect(self.load_record_choices)
        self.record_store.currentIndexChanged.connect(self.load_record_choices)
        self.record_filter.textChanged.connect(self._filter_record_choices)
        self.btn_record_replace.clicked.connect(lambda: self.do_record_restore(False))
        self.btn_record_new.clicked.connect(lambda: self.do_record_restore(True))
        self.tabs.addTab(tab, "Record Restore")

    def refresh_record_backups(self):
        current = self.record_backup.currentData()
        self.record_backup.clear()
        for row in backup_service.list_backups(self.policy.destination, verify=False):
            if row.get("verified"):
                self.record_backup.addItem(row["name"], row["path"])
        if current:
            index = self.record_backup.findData(current)
            if index >= 0:
                self.record_backup.setCurrentIndex(index)

    def load_record_choices(self, *_args):
        path = str(self.record_backup.currentData() or "")
        store = str(self.record_store.currentData() or "")
        self.record_list.clear()
        if not path or not store:
            return
        try:
            rows = record_restore_service.list_records(path, store)
        except Exception as exc:
            self.record_preview.setPlainText(str(exc))
            return
        for row in rows:
            item = QListWidgetItem(f"{row.get('title') or row.get('id')} · {row.get('id')}")
            item.setData(Qt.UserRole, row["id"])
            item.setData(Qt.UserRole + 1, row.get("title") or row["id"])
            self.record_list.addItem(item)

    def _filter_record_choices(self, text: str):
        needle = (text or "").strip().lower()
        for index in range(self.record_list.count()):
            item = self.record_list.item(index)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def preview_record(self, current, _previous=None):
        if current is None:
            return
        path = str(self.record_backup.currentData() or "")
        store = str(self.record_store.currentData() or "")
        record_id = str(current.data(Qt.UserRole) or "")
        try:
            plan = record_restore_service.preview(self.base_dir, path, store, record_id)
        except Exception as exc:
            self.record_preview.setPlainText(str(exc))
            return
        self.record_preview.setPlainText(
            f"{plan.get('title', record_id)}\n"
            f"Current: {'present' if plan.get('exists') else 'deleted/missing'} · "
            f"Changed: {'yes' if plan.get('changed') else 'no'}\n\n"
            "BACKUP RECORD\n" + _short(plan.get("backup"))
        )

    def do_record_restore(self, as_new: bool):
        item = self.record_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Record restore", "Select a record first.")
            return
        path = str(self.record_backup.currentData() or "")
        store = str(self.record_store.currentData() or "")
        record_id = str(item.data(Qt.UserRole) or "")
        if QMessageBox.Yes != QMessageBox.question(
            self,
            "Record restore",
            "A full pre-restore backup will be created. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ):
            return
        self.btn_record_replace.setEnabled(False)
        self.btn_record_new.setEnabled(False)

        def done(result):
            self.btn_record_replace.setEnabled(True)
            self.btn_record_new.setEnabled(True)
            if result.get("ok"):
                QMessageBox.information(
                    self,
                    "Record restore",
                    f"Restored {result.get('record_id')}.\nPre-restore backup:\n{result.get('pre_restore_backup')}",
                )
                self.load_record_choices()
            else:
                QMessageBox.warning(self, "Record restore", result.get("error") or "Restore failed.")

        self._run(
            lambda: record_restore_service.restore(
                self.base_dir,
                path,
                store,
                record_id,
                mode="as_new" if as_new else "replace",
                confirm=True,
            ),
            done,
        )

    # ------------------------------ integrity ------------------------- #
    def _build_integrity(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        self.integrity_text = QTextEdit()
        self.integrity_text.setReadOnly(True)
        self.integrity_text.setPlainText("The integrity scan is read-only and never repairs data.")
        layout.addWidget(self.integrity_text, 1)
        row = QHBoxLayout()
        self.btn_scan = primary_button("Run integrity check")
        self.btn_scan.clicked.connect(self.run_scan)
        row.addWidget(self.btn_scan)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Integrity Check")

    def run_scan(self):
        self.btn_scan.setEnabled(False)

        def done(report):
            self.btn_scan.setEnabled(True)
            summary = report["summary"]
            lines = [
                f"Status: {summary['status']} · {summary['findings']} finding(s)",
                f"Stores: {report['stores_inspected']} · records: {report['records_inspected']} "
                f"· notes: {report['notes_inspected']}",
                "",
            ]
            for finding in report["findings"]:
                lines.append(
                    f"[{finding['severity']}] {finding['store']}: {finding['message']} "
                    f"({finding['record']})"
                )
            self.integrity_text.setPlainText("\n".join(lines))

        self._run(lambda: integrity_service.scan(self.base_dir), done)

    # ------------------------------ conflicts ------------------------- #
    def _build_conflicts(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        self.list_conflicts = QListWidget()
        self.list_conflicts.currentItemChanged.connect(self._show_conflict)
        layout.addWidget(self.list_conflicts, 1)
        self.conflict_text = QTextEdit()
        self.conflict_text.setReadOnly(True)
        layout.addWidget(self.conflict_text, 1)
        row = QHBoxLayout()
        for label, action in (
            ("Keep local", "keep_local"),
            ("Keep remote", "keep_remote"),
            ("Keep both", "keep_both"),
            ("Defer", "defer"),
        ):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=action: self.resolve_conflict(value))
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Sync Conflicts")

    def refresh_conflicts(self):
        self.list_conflicts.clear()
        try:
            rows = conflict_service.list_conflicts(self.base_dir)
        except conflict_service.ConflictError as exc:
            self.conflict_text.setPlainText(str(exc))
            return
        for row in rows:
            item = QListWidgetItem(
                f"{row.get('status')} · {row.get('store')} · {row.get('title') or row.get('record_id')}"
            )
            item.setData(Qt.UserRole, row.get("id"))
            self.list_conflicts.addItem(item)
        self._load_restore_list()

    def _show_conflict(self, current, _previous=None):
        if current is None:
            return
        try:
            rows = conflict_service.list_conflicts(self.base_dir)
        except conflict_service.ConflictError as exc:
            self.conflict_text.setPlainText(str(exc))
            return
        conflict = next((row for row in rows if row.get("id") == current.data(Qt.UserRole)), None)
        if conflict:
            self.conflict_text.setPlainText(
                "LOCAL\n" + _short(conflict.get("local")) + "\n\nREMOTE\n" + _short(conflict.get("remote"))
            )

    def resolve_conflict(self, action: str):
        item = self.list_conflicts.currentItem()
        if item is None:
            return
        conflict_id = str(item.data(Qt.UserRole))
        if QMessageBox.Yes != QMessageBox.question(
            self,
            "Conflict",
            f"Apply '{action}' to this archived conflict? Both versions remain in history.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ):
            return
        result = conflict_service.resolve_conflict(
            self.base_dir, conflict_id, action, confirm=True
        )
        if not result.ok:
            QMessageBox.warning(self, "Conflict", result.error or result.status)
        self.refresh_conflicts()
        self.refresh_backups()

    # ------------------------------ health ---------------------------- #
    def _build_health(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        self.health_text = QTextEdit()
        self.health_text.setReadOnly(True)
        self.health_text.setPlainText("Checking stores…")
        layout.addWidget(self.health_text, 1)
        row = QHBoxLayout()
        refresh = ghost_button("Refresh health")
        refresh.clicked.connect(self.refresh_health)
        row.addWidget(refresh)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Storage Health")

    def refresh_health(self):
        from litebrowser.core import storage_health
        from litebrowser.core.storage_catalog import migration_coverage

        try:
            summary = storage_health.health_summary(self.base_dir)
            coverage = migration_coverage()
        except Exception as exc:
            self.health_text.setPlainText(f"Could not inspect stores: {exc}")
            return
        lines = [
            f"{summary['available']}/{summary['total']} stores readable · "
            f"{summary['unavailable_count']} unavailable · "
            f"{summary['quarantine_count']} quarantine artifact(s)",
            f"Migration coverage: {coverage['journaled']}/{coverage['total']} catalogued stores "
            f"journaled ({coverage['journaled_percent']}%); legacy stores remain byte-guarded "
            f"and backup-protected, not silently transformed.",
            "",
        ]
        for row in summary["stores"]:
            if row["available"]:
                continue
            lines.append(
                f"[{row['status'].upper()}] {row['name']} — {row['detail'] or 'unreadable'}"
            )
            artifact = row.get("recovery_artifact") or {}
            if artifact:
                lines.append(f"  preserved copy: {artifact.get('artifact', '')}")
        if summary["healthy"]:
            lines.append("All catalogued stores are readable. Missing optional stores are normal.")
        else:
            lines.append(
                "\nOriginal bytes were left in place. Use Restore Center with a verified backup; "
                "do not save a default payload over an unavailable store."
            )
        self.health_text.setPlainText("\n".join(lines))

    # ----------------------------- recovery --------------------------- #
    def _build_recovery(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        self.recovery_text = QTextEdit()
        self.recovery_text.setReadOnly(True)
        layout.addWidget(self.recovery_text, 1)
        row = QHBoxLayout()
        refresh = ghost_button("Refresh report")
        refresh.clicked.connect(self.refresh_recovery)
        row.addWidget(refresh)
        row.addStretch(1)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Recovery")

    def refresh_recovery(self):
        from litebrowser.core import storage_health

        try:
            inspection = recovery_service.inspect_startup(self.base_dir)
        except Exception as exc:
            self.recovery_text.setPlainText(f"Could not inspect startup recovery: {exc}")
            return
        report = storage_health.read_json_checked(
            recovery_service.report_path(self.base_dir), dict
        )
        lines = [
            f"Previous session: {'unclean' if inspection['unclean_previous_session'] else 'clean'}",
            f"Restore state: {inspection['restore_state'] or 'none'}",
            f"Unresolved migrations: {len(inspection['pending_migrations'])}",
            f"Stale temporary files: {len(inspection['stale_temp_files'])}",
            f"Incomplete backups: {len(inspection['incomplete_backups'])}",
            f"Quarantine artifacts: {inspection['quarantine_count']}",
        ]
        if report.ok:
            value = report.value
            lines.extend(
                [
                    "",
                    f"Last recovery report: {value.get('status', 'unknown')} "
                    f"(generated {value.get('generated_at', 0)})",
                ]
            )
        else:
            lines.extend(["", "No readable startup recovery report yet."])
        if inspection["pending_migrations"]:
            lines.append("\nReview these migrations; they are not replayed automatically:")
            for entry in inspection["pending_migrations"]:
                lines.append(
                    f"- {entry.get('store')}: {entry.get('state')} "
                    f"({entry.get('error') or 'needs review'})"
                )
        if inspection["restore_state"] not in ("", "COMMITTED", "FAILED"):
            lines.append(
                "\nAn interrupted restore needs review. The pre-restore backup and rollback "
                "copies are preserved; it is never replayed automatically."
            )
        self.recovery_text.setPlainText("\n".join(lines))

    # ------------------------------- proxy ---------------------------- #
    def _build_proxy(self):
        tab = QDialog()
        layout = QVBoxLayout(tab)
        self.proxy_text = QTextEdit()
        self.proxy_text.setReadOnly(True)
        layout.addWidget(self.proxy_text, 1)
        self.chk_direct = QCheckBox(
            "Allow Page Monitor and subscription refresh to connect directly while a proxy is configured"
        )
        self.chk_direct.setToolTip(
            "This is an explicit privacy choice. Without it, safe HTTP refuses rather than bypassing your proxy."
        )
        self.chk_direct.toggled.connect(self._set_direct_access)
        layout.addWidget(self.chk_direct)
        self.tabs.addTab(tab, "Proxy")

    def refresh_proxy(self):
        try:
            policy = safe_http.proxy_policy_status(
                proxy_config=prefs.get_proxy_config(self.base_dir)
            )
        except Exception as exc:
            self.proxy_text.setPlainText(f"Could not read proxy policy: {exc}")
            return
        lines = [
            f"Application proxy configured: {'yes' if policy['application_configured'] else 'no'}",
            "Environment proxy variables: "
            + (", ".join(policy["environment_variables"]) or "none"),
            f"Safe HTTP transport: {policy['transport']}",
            "Automatic mode: "
            + (
                "refuses when a proxy is configured"
                if policy["automatic_mode"] == "refuse"
                else "direct"
            ),
            "Application proxy transport implemented: no",
            "",
            "Mei never claims SOCKS or Windows system-proxy support. Page Monitor and "
            "adblock subscription refresh refuse rather than silently going direct.",
        ]
        if policy["automatic_mode"] == "refuse":
            lines.append(
                "If you deliberately want those background features to bypass the browser "
                "proxy, use the checkbox below; it is recorded as an explicit choice."
            )
        self.proxy_text.setPlainText("\n".join(lines))
        self.chk_direct.blockSignals(True)
        self.chk_direct.setChecked(prefs.get_page_monitor_direct(self.base_dir))
        self.chk_direct.blockSignals(False)

    def _set_direct_access(self, checked: bool):
        prefs.set_page_monitor_direct(self.base_dir, bool(checked))
        self.refresh_proxy()


def show_data_management(shell):
    """Open the dialog for an AppShell (which owns ``profile_dir``)."""
    base_dir = getattr(shell, "profile_dir", "")
    if not base_dir:
        return
    parent = getattr(shell, "browser_page", None)
    dialog = DataManagementDialog(base_dir, parent)
    dialog.exec_()


__all__ = ["DataManagementDialog", "show_data_management"]
