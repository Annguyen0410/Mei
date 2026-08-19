import os
import time
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from litebrowser.core import app_paths, prefs
from litebrowser.core import time_utils as _time_utils
from litebrowser.services import (
    ai_service,
    history_service,
    life_service,
    personal_service,
    tab_sets,
)
from litebrowser.ui import components, theme, win_titlebar


class AIWindow(QMainWindow):
    query_finished = pyqtSignal(object, str)

    def __init__(self, base_dir: str, app_dir: str = None, embedded: bool = False):
        super().__init__()
        self.base_dir = prefs.ensure_profile_layout(base_dir)
        self.app_dir = app_dir or app_paths.project_root()
        self.embedded = embedded
        self._prompt_history = []
        self._thread_items = []
        self._last_question = ""
        self._last_answer = ""
        self._last_context = ""
        self._external_context = ""
        self._external_context_label = "Workspace-wide"
        self._query_pending = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="litebrowser-ai")
        self.ollama_models = ai_service.detect_ollama_models()
        self.setWindowTitle("AI Workspace - Mei")
        self.setWindowIcon(QIcon(os.path.join(self.app_dir, "icon.png")))
        self.resize(1180, 780)
        self.setMinimumSize(760 if embedded else 880, 520 if embedded else 620)
        if not self.embedded:
            win_titlebar.apply_dark_titlebar(self, enabled=True)

        root = QWidget()
        root.setObjectName("AIWorkspace")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(14, 12, 14, 12)
        hero_layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.addWidget(components.page_header("AI Assistant", "Ask one assistant across Browser, Personal, Library, and this workspace"))
        brand_row.addStretch(1)
        hero_layout.addLayout(brand_row)

        settings_row = QHBoxLayout()
        settings_row.setSpacing(8)
        self.cmb_provider = QComboBox()
        self.cmb_provider.addItem("RAG local only", "rag")
        self.cmb_provider.addItem("OpenRouter assistant", "openrouter")
        self.cmb_provider.addItem("Local LLM: Ollama", "ollama")
        self.cmb_provider.addItem("Local LLM: llama.cpp server", "llama_cpp")
        settings_row.addWidget(self.cmb_provider)
        self.ed_model = QLineEdit()
        self.ed_model.setPlaceholderText("Model name")
        self.ed_model.setMinimumWidth(150)
        settings_row.addWidget(self.ed_model)
        self.ed_api_key = QLineEdit()
        self.ed_api_key.setPlaceholderText("OpenRouter API key")
        self.ed_api_key.setEchoMode(QLineEdit.Password)
        self.ed_api_key.setMinimumWidth(160)
        settings_row.addWidget(self.ed_api_key, 1)
        self.btn_save_settings = QPushButton("Save AI settings")
        settings_row.addWidget(self.btn_save_settings)
        hero_layout.addLayout(settings_row)

        prompt_row = QHBoxLayout()
        self.ed_question = QLineEdit()
        self.ed_question.setPlaceholderText("Ask about the current page, your notes, tasks, saved pages, or the whole workspace...")
        prompt_row.addWidget(self.ed_question, 1)
        self.btn_ask = QPushButton("Ask assistant")
        self.btn_ask.setObjectName("TopAccentButton")
        self.btn_reindex = QPushButton("Rebuild index")
        prompt_row.addWidget(self.btn_ask)
        prompt_row.addWidget(self.btn_reindex)
        hero_layout.addLayout(prompt_row)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        self.lbl_index = components.badge("Index: —", "accent")
        badge_row.addWidget(self.lbl_index)
        self.lbl_context_scope = components.badge("Context: Workspace-wide")
        badge_row.addWidget(self.lbl_context_scope)
        badge_row.addStretch(1)
        self.chk_show_context = QCheckBox("Show sources")
        self.chk_show_context.setChecked(True)
        badge_row.addWidget(self.chk_show_context)
        self.btn_to_note = QPushButton("☰ Save to note")
        self.btn_to_task = QPushButton("☑ Create task")
        self.btn_save_set = QPushButton("◫ Save session")
        self.btn_export_thread = QPushButton("⇩ Export")
        self.btn_clear_thread = QPushButton("✕ Clear")
        badge_row.addWidget(self.btn_to_note)
        badge_row.addWidget(self.btn_to_task)
        badge_row.addWidget(self.btn_save_set)
        badge_row.addWidget(self.btn_export_thread)
        badge_row.addWidget(self.btn_clear_thread)
        hero_layout.addLayout(badge_row)

        layout.addWidget(hero)

        body = QSplitter(Qt.Horizontal)
        layout.addWidget(body, 1)

        left_card = QFrame()
        left_card.setObjectName("SectionCard")
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(6)
        left_layout.addWidget(components.section_header("Sessions", "Ask history"))
        self.history_list = QListWidget()
        self.history_list.setObjectName("CafeList")
        left_layout.addWidget(self.history_list, 1)
        body.addWidget(left_card)

        center_card = QFrame()
        center_card.setObjectName("SectionCard")
        center_layout = QVBoxLayout(center_card)
        center_layout.setContentsMargins(12, 12, 12, 12)
        center_layout.setSpacing(6)
        center_layout.addWidget(components.section_header("Assistant thread", "Answers from the assistant"))
        self.txt_answer = QTextEdit()
        self.txt_answer.setReadOnly(True)
        self.txt_answer.setPlaceholderText("Answers from the assistant will appear here.")
        center_layout.addWidget(self.txt_answer, 1)
        body.addWidget(center_card)

        right_card = QFrame()
        right_card.setObjectName("SectionCard")
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(6)
        right_layout.addWidget(components.section_header("Sources & prompts", "Retrieved sources + quick prompts"))
        self.txt_context = QTextEdit()
        self.txt_context.setReadOnly(True)
        self.txt_context.setPlaceholderText("Retrieved sources and injected workspace context show here.")
        right_layout.addWidget(self.txt_context, 1)
        right_layout.addWidget(components.section_header("Prompt Library", "Double-click to use"))
        self.prompt_list = QListWidget()
        self.prompt_list.setObjectName("CafeList")
        for text in (
            "Summarize this workspace",
            "Turn current page into a note",
            "Extract deadlines and tasks",
            "Build a study brief",
            "What changed in my recent saved pages?",
            "What should I focus on today?",
        ):
            self.prompt_list.addItem(text)
        right_layout.addWidget(self.prompt_list, 1)
        body.addWidget(right_card)
        body.setChildrenCollapsible(True)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setStretchFactor(2, 0)
        body.setSizes([180, 760, 220])

        self.setStyleSheet(theme.main_qss(prefs.get_shell_theme(self.base_dir), prefs.get_accent(self.base_dir)))
        self.btn_reindex.clicked.connect(self._reindex)
        self.btn_ask.clicked.connect(self._ask)
        self.ed_question.returnPressed.connect(self._ask)
        self.cmb_provider.currentIndexChanged.connect(self._on_provider_change)
        self.btn_save_set.clicked.connect(self.save_current_set)
        self.btn_to_note.clicked.connect(self.save_answer_to_note)
        self.btn_to_task.clicked.connect(self.create_task_from_answer)
        self.btn_export_thread.clicked.connect(self._export_thread)
        self.btn_clear_thread.clicked.connect(self._clear_thread)
        self.prompt_list.itemDoubleClicked.connect(self._apply_prompt_template)
        self.history_list.itemDoubleClicked.connect(self._load_history_item)
        self.btn_save_settings.clicked.connect(self._save_settings_with_notice)
        self.query_finished.connect(self._finish_assistant_query)
        self._load_settings()
        self._refresh_index_label()
        self._apply_compact_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_compact_layout()

    def _apply_compact_layout(self):
        width = max(0, self.width())
        compact = width < 1180
        narrow = width < 940
        tiny = width < 820
        body = self.findChild(QSplitter)
        if body:
            left = 132 if tiny else 150 if narrow else 170 if compact else 190
            right = 0 if tiny else 180 if narrow else 210 if compact else 240
            center = max(320, width - left - right - 24)
            body.setSizes([left, center, right])
        self.chk_show_context.setVisible(not tiny)
        self.btn_to_note.setVisible(not narrow)
        self.btn_to_task.setVisible(not narrow)
        self.btn_save_set.setVisible(not tiny)

    def _load_settings(self):
        data = prefs.load_ai_settings(self.base_dir)
        idx = self.cmb_provider.findData(data.get("provider", "rag"))
        if idx >= 0:
            self.cmb_provider.setCurrentIndex(idx)
        self.ed_api_key.setText(data.get("openrouter_api_key", ""))
        self._refresh_model_value()
        self.chk_show_context.setChecked(bool(data.get("show_sources", True)))
        self._on_provider_change()

    def _refresh_model_value(self):
        settings = prefs.load_ai_settings(self.base_dir)
        provider = self.cmb_provider.currentData()
        if provider == "openrouter":
            self.ed_model.setText(settings.get("openrouter_model", "openai/gpt-4o-mini"))
        elif provider == "ollama":
            self.ed_model.setText(settings.get("ollama_model", self.ollama_models[0] if self.ollama_models else ""))
        elif provider == "llama_cpp":
            self.ed_model.setText(settings.get("llama_cpp_url", "http://127.0.0.1:8080/completion"))
        else:
            self.ed_model.setText("")

    def _collect_settings_payload(self):
        provider = self.cmb_provider.currentData()
        payload = {
            "provider": provider,
            "openrouter_api_key": self.ed_api_key.text().strip(),
            "show_sources": self.chk_show_context.isChecked(),
        }
        if provider == "openrouter":
            payload["openrouter_model"] = self.ed_model.text().strip() or "openai/gpt-4o-mini"
        elif provider == "ollama":
            payload["ollama_model"] = self.ed_model.text().strip()
        elif provider == "llama_cpp":
            payload["llama_cpp_url"] = self.ed_model.text().strip() or "http://127.0.0.1:8080/completion"
        return payload

    def _save_settings(self):
        prefs.save_ai_settings(self.base_dir, self._collect_settings_payload())

    def _save_settings_with_notice(self):
        self._save_settings()
        QMessageBox.information(self, "AI Assistant", "AI provider settings saved.")

    def _on_provider_change(self):
        provider = self.cmb_provider.currentData()
        self.ed_api_key.setVisible(provider == "openrouter")
        self._refresh_model_value()
        if provider == "rag":
            self.ed_model.setPlaceholderText("No remote model needed")
            self.ed_model.setEnabled(False)
        elif provider == "openrouter":
            self.ed_model.setPlaceholderText("Example: openai/gpt-4o-mini")
            self.ed_model.setEnabled(True)
        elif provider == "ollama":
            self.ed_model.setPlaceholderText("Ollama model name")
            self.ed_model.setEnabled(True)
        else:
            self.ed_model.setPlaceholderText("llama.cpp completion URL")
            self.ed_model.setEnabled(True)

    def _refresh_index_label(self):
        data = ai_service.load_index(self.base_dir)
        self.lbl_index.setText(f"Index: {len(data.get('docs', []))} docs · updated {_format_ts(int(data.get('built_at', 0) or 0))}")

    def _reindex(self):
        data = ai_service.rebuild_index(self.base_dir)
        self._refresh_index_label()
        QMessageBox.information(self, "AI Assistant", f"Rebuilt index with {len(data.get('docs', []))} docs.")

    def _apply_prompt_template(self, item: QListWidgetItem):
        self.ed_question.setText(item.text())
        self.ed_question.setFocus()

    def _append_history_item(self, question: str, answer: str, context_label: str):
        payload = {"question": question, "answer": answer, "context_label": context_label, "context": self._last_context}
        self._thread_items.insert(0, payload)
        self._thread_items = self._thread_items[:24]
        self.history_list.clear()
        for entry in self._thread_items:
            row = QListWidgetItem(f"{entry['question']}\n{entry['context_label']}")
            row.setData(Qt.UserRole, entry)
            self.history_list.addItem(row)

    def _load_history_item(self, item: QListWidgetItem):
        payload = item.data(Qt.UserRole) or {}
        self.ed_question.setText(payload.get("question", ""))
        self.txt_answer.setPlainText(payload.get("answer", ""))
        self.txt_context.setPlainText(payload.get("context", ""))
        self.lbl_context_scope.setText(payload.get("context_label", "Context: Workspace-wide"))

    def _ask(self):
        question = (self.ed_question.text() or "").strip()
        if not question:
            return
        self.run_assistant_query(question, self._external_context_label, self._external_context)

    def run_assistant_query(self, question: str, context_label: str = "Workspace-wide", extra_context: str = ""):
        if self._query_pending:
            self.txt_answer.setPlainText("Another request is still running — please wait for it to finish.")
            return
        self._save_settings()
        self._last_question = question
        self._prompt_history.append(question)
        self._prompt_history = self._prompt_history[-20:]
        self._query_pending = True
        self.btn_ask.setEnabled(False)
        self.btn_reindex.setEnabled(False)
        self.txt_answer.setPlainText("Thinking...")
        future = self._executor.submit(
            ai_service.answer_query,
            self.base_dir,
            question,
            self.cmb_provider.currentData() or "rag",
            self.ed_model.text().strip(),
            extra_context,
            10,
        )
        future.add_done_callback(lambda done, label=context_label: self.query_finished.emit(done, label))

    def _finish_assistant_query(self, future, context_label: str):
        self._query_pending = False
        self.btn_ask.setEnabled(True)
        self.btn_reindex.setEnabled(True)
        try:
            result = future.result()
        except Exception as exc:
            self.txt_answer.setPlainText(f"Assistant request failed: {exc}")
            return
        self._last_answer = result.get("answer", "")
        self._last_context = result.get("context", "")
        question = self._last_question or ""
        history_service.log_event(
            self.base_dir,
            "ai-question",
            question,
            (self._last_answer or "")[:280],
            {"provider": result.get("provider", ""), "context": context_label},
        )
        self.lbl_context_scope.setText(f"Context: {context_label}")
        if self.chk_show_context.isChecked():
            self.txt_context.setPlainText(self._last_context or "(no sources)")
        else:
            self.txt_context.setPlainText("(hidden)")
        provider_label = self.cmb_provider.currentText()
        answer = self._last_answer or "No answer returned."
        self.txt_answer.setPlainText(f"{answer}\n\n---\nProvider: {provider_label}")
        self._append_history_item(question, self.txt_answer.toPlainText(), f"Context: {context_label}")

    def ask_with_context(self, question: str, context_label: str, context_text: str):
        self._external_context_label = context_label or "Workspace-wide"
        self._external_context = context_text or ""
        self.ed_question.setText(question or "")
        self.run_assistant_query(question or "Summarize this context", self._external_context_label, self._external_context)

    def _clear_thread(self):
        """Empty the in-memory thread, session list, and visible answer panes."""
        self._thread_items = []
        self.history_list.clear()
        self.txt_answer.clear()
        self.txt_context.clear()
        self._last_question = ""
        self._last_answer = ""
        self._last_context = ""
        self.ed_question.clear()
        self.lbl_context_scope.setText("Context: Workspace-wide")

    def _export_thread(self):
        """Write the current assistant thread to a markdown/text file."""
        entries = list(self._thread_items)
        if not entries and not self.txt_answer.toPlainText().strip():
            QMessageBox.information(self, "AI Assistant", "Nothing to export yet.")
            return
        default = os.path.join(self.base_dir, "ai-thread-" + time.strftime("%Y%m%d-%H%M") + ".md")
        path, _ = QFileDialog.getSaveFileName(self, "Export AI thread", default, "Markdown (*.md);;Text (*.txt)")
        if not path:
            return
        lines = []
        for entry in reversed(entries):
            lines.append("## " + (entry.get("question") or "Question"))
            lines.append("")
            lines.append(entry.get("answer") or "")
            lines.append("")
        if not lines and self.txt_answer.toPlainText().strip():
            lines.append("## " + (self._last_question or "Thread"))
            lines.append("")
            lines.append(self.txt_answer.toPlainText())
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
        except OSError as exc:
            QMessageBox.warning(self, "AI Assistant", "Could not export the thread: %s" % (exc,))
            return
        QMessageBox.information(self, "AI Assistant", "AI thread exported to:\n" + path)

    def save_answer_to_note(self):
        if not self._last_answer:
            QMessageBox.information(self, "AI Assistant", "Ask something first.")
            return
        title = self._last_question[:60] or "AI note"
        body = "# " + title + "\n\n" + self._last_answer
        note = personal_service.create_note(self.base_dir, title, body)
        QMessageBox.information(self, "AI Assistant", "Saved answer to note: " + note["title"])

    def create_task_from_answer(self):
        if not self._last_answer:
            QMessageBox.information(self, "AI Assistant", "Ask something first.")
            return
        title = self._last_question[:80] or "AI follow-up"
        life_service.add_task(self.base_dir, title, bucket="work")
        QMessageBox.information(self, "AI Assistant", "Created a task from the current answer.")

    def get_current_ai_state(self):
        return [
            {"url": f"ai://prompt/{idx + 1}", "prompt": prompt, "active": idx == len(self._prompt_history) - 1}
            for idx, prompt in enumerate(self._prompt_history)
        ]

    def _auto_save_set(self):
        tabs = self.get_current_ai_state()
        if tabs:
            tab_sets.add_tab_set(self.base_dir, "ai", time.strftime("AI auto %Y-%m-%d %H:%M"), tabs)

    def save_current_set(self):
        tabs = self.get_current_ai_state()
        if not tabs:
            QMessageBox.information(self, "AI session", "No prompts yet.")
            return
        default = time.strftime("AI manual %Y-%m-%d %H:%M")
        name, ok = QInputDialog.getText(self, "Save AI session", "Session name:", text=default)
        if not ok:
            return
        tab_sets.add_tab_set(self.base_dir, "ai", name or default, tabs)
        QMessageBox.information(self, "AI session", "Current AI session saved.")

    def closeEvent(self, event):
        try:
            self._auto_save_set()
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        event.accept()


def _format_ts(ts_value: int) -> str:
    """Backward-compatible alias; the canonical helper lives in core.time_utils."""
    return _time_utils.format_ts(ts_value)
