# Mei - Safe Vault dialog
import os
import shutil

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from litebrowser.ui.dialogs.common import (
    dialog_footer,
    ghost_button,
    primary_button,
)


def show_vault_dialog(parent, base_vault, dialog_stylesheet):
    if not os.path.exists(base_vault):
        os.makedirs(base_vault)

    dialog = QDialog(parent)
    dialog.setWindowTitle("Safe Vault — Notes, folders, files")
    dialog.resize(680, 520)
    dialog.setStyleSheet(dialog_stylesheet())
    layout = QVBoxLayout(dialog)
    layout.setAlignment(Qt.AlignCenter)

    current_path = [base_vault]
    path_label = QLabel("SafeVault")
    path_label.setAlignment(Qt.AlignCenter)
    path_label.setObjectName("MutedLabel")
    layout.addWidget(path_label)

    list_widget = QListWidget()
    list_widget.setObjectName("CafeList")
    list_widget.setMinimumHeight(280)

    def get_current():
        return current_path[-1]

    def refresh_list():
        list_widget.clear()
        path = get_current()
        path_label.setText(os.path.relpath(path, base_vault) or "SafeVault")
        if not os.path.isdir(path):
            return
        try:
            names = sorted(os.listdir(path))
            dirs = [n for n in names if os.path.isdir(os.path.join(path, n))]
            files = [n for n in names if os.path.isfile(os.path.join(path, n))]
            for n in dirs:
                item = QListWidgetItem(f"[Folder] {n}")
                item.setData(Qt.UserRole, ("dir", os.path.join(path, n)))
                list_widget.addItem(item)
            for n in files:
                item = QListWidgetItem(n)
                item.setData(Qt.UserRole, ("file", os.path.join(path, n)))
                list_widget.addItem(item)
        except Exception as e:
            QMessageBox.warning(dialog, "Error", str(e))

    def on_item_double_click(item):
        kind, full = item.data(Qt.UserRole)
        if kind == "dir":
            current_path.append(full)
            refresh_list()
        else:
            try:
                os.startfile(full)
            except Exception:
                QMessageBox.warning(dialog, "Open file", "Could not open the file.")

    list_widget.itemDoubleClicked.connect(on_item_double_click)
    refresh_list()
    layout.addWidget(list_widget)

    def go_up():
        if len(current_path) > 1:
            current_path.pop()
            refresh_list()

    def new_folder():
        name, ok = QInputDialog.getText(dialog, "New folder", "Folder name:")
        if ok and name.strip():
            name = name.strip()
            full = os.path.join(get_current(), name)
            if os.path.exists(full):
                QMessageBox.warning(dialog, "Error", "A folder with this name already exists.")
                return
            try:
                os.makedirs(full, exist_ok=True)
                refresh_list()
                QMessageBox.information(dialog, "OK", "Folder created.")
            except Exception as e:
                QMessageBox.warning(dialog, "Error", str(e))

    def new_note():
        name, ok = QInputDialog.getText(dialog, "New note", "File name (.txt):", text="note.txt")
        if ok and name.strip():
            name = name.strip()
            if not name.endswith(".txt"):
                name += ".txt"
            full = os.path.join(get_current(), name)
            if os.path.exists(full):
                reply = QMessageBox.question(dialog, "Overwrite?", "The file already exists. Open it to edit?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return
            note_dlg = QDialog(dialog)
            note_dlg.setWindowTitle("Note: " + name)
            note_dlg.setStyleSheet(dialog_stylesheet())
            note_dlg.resize(500, 400)
            v = QVBoxLayout(note_dlg)
            te = QTextEdit()
            if os.path.exists(full):
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        te.setPlainText(f.read())
                except Exception:
                    pass
            v.addWidget(te)
            btn_save = primary_button("Save")

            def do_save():
                try:
                    with open(full, "w", encoding="utf-8") as f:
                        f.write(te.toPlainText())
                    refresh_list()
                    note_dlg.accept()
                    QMessageBox.information(dialog, "OK", "Note saved.")
                except Exception as e:
                    QMessageBox.warning(note_dlg, "Error", str(e))
            btn_save.clicked.connect(do_save)
            dialog_footer(v, primary=btn_save, close=note_dlg.accept)
            note_dlg.exec_()

    def upload_file():
        path, _ = QFileDialog.getOpenFileName(dialog, "Choose file to upload", get_current())
        if path:
            try:
                dest = os.path.join(get_current(), os.path.basename(path))
                shutil.copy2(path, dest)
                refresh_list()
                QMessageBox.information(dialog, "OK", "File saved to the Vault.")
            except Exception as e:
                QMessageBox.warning(dialog, "Error", str(e))

    def delete_selected():
        item = list_widget.currentItem()
        if not item:
            QMessageBox.information(dialog, "Select item", "Select a folder or file to delete.")
            return
        kind, full = item.data(Qt.UserRole)
        name = os.path.basename(full)
        reply = QMessageBox.question(dialog, "Delete?", f"Delete \"{name}\"?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            if kind == "dir":
                shutil.rmtree(full)
            else:
                os.remove(full)
            refresh_list()
            QMessageBox.information(dialog, "OK", "Deleted.")
        except Exception as e:
            QMessageBox.warning(dialog, "Error", str(e))

    # Writing a note is what the vault is for; the folder chores and the file
    # verbs used to sit beside it as four more identical boxes.
    btn_note = primary_button("New note")
    btn_note.clicked.connect(new_note)
    btn_up = ghost_button("↑  Up one level", "Go to the parent folder")
    btn_up.clicked.connect(go_up)
    dialog_footer(
        layout,
        primary=btn_note,
        secondary=(btn_up,),
        menu=(
            ("New folder…", new_folder),
            ("Upload a file…", upload_file),
            (None, None),
            ("Open the Vault folder in Explorer", lambda: os.startfile(base_vault)),
            ("🗑  Delete the selected item", delete_selected),
        ),
        close=dialog.accept,
    )

    dialog.exec_()
