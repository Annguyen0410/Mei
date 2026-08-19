# Mei - Safe Vault dialog
import os
import shutil

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
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

    nav_row = QHBoxLayout()
    nav_row.setSpacing(8)
    btn_back = QPushButton("Go up")
    def go_up():
        if len(current_path) > 1:
            current_path.pop()
            refresh_list()
    btn_back.clicked.connect(go_up)
    nav_row.addStretch()
    nav_row.addWidget(btn_back)
    nav_row.addStretch()
    layout.addLayout(nav_row)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)

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
            btn_save = QPushButton("Save")
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
            v.addWidget(btn_save)
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

    btn_new_folder = QPushButton("New folder")
    btn_new_folder.clicked.connect(new_folder)
    btn_note = QPushButton("New note")
    btn_note.clicked.connect(new_note)
    btn_upload = QPushButton("Upload file")
    btn_upload.clicked.connect(upload_file)
    btn_del = QPushButton("Delete selected item")
    btn_del.clicked.connect(delete_selected)
    btn_row.addStretch()
    btn_row.addWidget(btn_new_folder)
    btn_row.addWidget(btn_note)
    btn_row.addWidget(btn_upload)
    btn_row.addWidget(btn_del)
    btn_row.addStretch()
    layout.addLayout(btn_row)

    open_folder_btn = QPushButton("Open Vault folder in Explorer")
    open_folder_btn.clicked.connect(lambda: os.startfile(base_vault))
    layout.addWidget(open_folder_btn, alignment=Qt.AlignCenter)

    dialog.exec_()
