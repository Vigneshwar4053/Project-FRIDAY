"""Native Qt Widgets application. Network and inference never run on the GUI thread."""
import importlib.util
import json
import sys
from pathlib import Path
from threading import Event
from time import monotonic

from zorvyq import EXPANSION
from zorvyq.services import Controller, DEFAULT_MODEL, ROOT, knowledge_inventory, resource_snapshot


def main():
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        # A graphical error when a GNOME session is available; no silent terminal-only failure.
        import subprocess
        message = ('ZORVYQ needs the approved Qt desktop dependency. Install requirements-desktop.txt '
                   'into this project’s existing .venv after owner approval. No models or data were changed.')
        if Path('/usr/bin/zenity').is_file():
            subprocess.run(['/usr/bin/zenity', '--error', '--title=ZORVYQ', '--text='+message], check=False)
        else:
            print(message, file=sys.stderr)
        return 1
    # This application supplies its own palette. Avoid loading a host GTK theme
    # plugin whose GSettings schema can be incompatible with the Qt wheel.
    app = QApplication([sys.argv[0], '-platformtheme', 'generic', '-style', 'Fusion', *sys.argv[1:]])
    app.setApplicationName('ZORVYQ')
    app.setOrganizationName('ZORVYQ')
    app.setDesktopFileName('com.zorvyq.ZORVYQ')
    from PySide6.QtCore import QLockFile, QStandardPaths
    runtime = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
    lock = QLockFile(str(Path(runtime)/'zorvyq-desktop.lock'))
    if not lock.tryLock(0):
        QMessageBox.information(None, 'ZORVYQ', 'ZORVYQ is already running. Select its window in Ubuntu Activities.')
        return 0
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(str(ROOT/'assets/zorvyq.svg')))
    try:
        window = build_window()
        window.show()
        return app.exec()
    except Exception:
        QMessageBox.critical(None, 'ZORVYQ startup failed',
            'ZORVYQ could not open its workspace. Check the project location, local settings and desktop dependencies. '
            'Use docs/ZORVYQ_STARTUP_MIGRATION.md for recovery. No startup entry was changed.')
        return 1


def build_window():
    from PySide6.QtCore import Qt, QObject, Signal, Slot, QThread, QTimer
    from PySide6.QtGui import QIcon, QTextDocument
    from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
        QLabel, QPushButton, QListWidget, QStackedWidget, QScrollArea, QFrame, QGridLayout,
        QTextEdit, QTextBrowser, QCheckBox, QLineEdit, QComboBox, QMessageBox, QProgressBar,
        QDialog, QDialogButtonBox, QPlainTextEdit, QInputDialog, QSizePolicy, QSpinBox, QButtonGroup)
    from friday.tools.access import FolderDecision
    from friday.intelligence.permissions import KnowledgePurpose, KnowledgeDecision

    class ApprovalBridge(QObject):
        requested = Signal(object)
        def __init__(self):
            super().__init__()
            self.closing = False
        def decide(self, title, summary, detail):
            ticket = {'title': title, 'summary': summary, 'detail': detail,
                      'event': Event(), 'allowed': False}
            if self.closing:
                return False
            self.requested.emit(ticket)
            # GUI remains responsive. Closing denies outstanding requests.
            while not ticket['event'].wait(.2):
                if self.closing:
                    return False
            return ticket['allowed']
        def request(self, approval):
            # No persistent-grant option: narrower than existing CLI, never broader.
            return FolderDecision.ALLOW_ONCE if self.decide('Permission required',
                'Allow this exact operation once?', approval.prompt()) else FolderDecision.DENY
        def secret(self, prompt):
            ticket = {'kind': 'credential', 'event': Event(), 'secret': None}
            if self.closing:
                return None
            self.requested.emit(ticket)
            while not ticket['event'].wait(.2):
                if self.closing:
                    return None
            return ticket.pop('secret', None)
        def knowledge(self, documents):
            def decide(request):
                if request.purpose is not KnowledgePurpose.RETRIEVE or set(request.targets) != set(documents):
                    return KnowledgeDecision.DENY
                details = 'Scope fingerprint: '+request.scope_sha256+'\n\n'+'\n\n'.join(
                    json.dumps({'source_id': sid, 'title': documents[sid]['title'],
                        'url': documents[sid]['source_url'], 'revision': documents[sid]['document_version']},
                        ensure_ascii=True) for sid in request.targets)
                allowed = self.decide('Approved knowledge access',
                    'ZORVYQ requests access to approved knowledge.\n\nCollection: Cybersecurity\n'
                    f'Eligible sources: {len(request.targets)}\nPurpose: Answer your current question', details)
                return KnowledgeDecision.ALLOW_ONCE if allowed else KnowledgeDecision.DENY
            return decide

    class Worker(QThread):
        result = Signal(object)
        progress = Signal(str)
        def __init__(self, operation, parent):
            super().__init__(parent)
            self.operation = operation
        def run(self):
            try:
                self.result.emit({'ok': True, 'value': self.operation()})
            except BaseException as error:
                # Fixed categories only. No exception text, prompts, paths or backend logs.
                from friday.voice.backend import ProcessCleanupError, VoiceError
                from friday.voice.tts import SpeechError
                category = ('audio_cleanup_unconfirmed' if isinstance(error, ProcessCleanupError) else
                            'offline_playback_failed' if isinstance(error, SpeechError) else
                            getattr(error, 'category', 'local_voice_failed') if isinstance(error, VoiceError) else
                            getattr(error, 'category', 'gui_worker_failure'))
                from zorvyq.diagnostics import category as safe_category
                self.result.emit({'ok': False, 'category': safe_category(category)})

    class Composer(QTextEdit):
        send = Signal()
        def keyPressEvent(self, event):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.send.emit()
            else:
                super().keyPressEvent(event)

    class SafeBrowser(QTextBrowser):
        """No remote images, local file resources, automatic URLs or browser sessions."""
        def loadResource(self, resource_type, url):
            return None

    def label(text, role=None):
        widget = QLabel(text)
        widget.setTextFormat(Qt.TextFormat.PlainText)
        widget.setWordWrap(True)
        if role:
            widget.setObjectName(role)
        return widget

    def button(text, action=None):
        widget = QPushButton(text)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.setProperty('runtimeAction', text in {
            'Refresh inventory', 'Refresh installed and loaded models', 'Unload selected resident model…',
            'View selected model details', 'Speak entered text', 'Activate microphone once…'})
        if action:
            widget.clicked.connect(action)
        return widget

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('ZORVYQ — Local AI Assistant')
            self.resize(1180, 820)
            self.setMinimumSize(700, 500)
            self.bridge = ApprovalBridge()
            self.bridge.requested.connect(self.permission)
            self.controller = Controller(self.bridge, self.bridge.knowledge)
            from zorvyq.preferences import Preferences
            from zorvyq.projects import Projects
            from zorvyq.voice import DesktopSpeech
            from zorvyq.security import Nmap
            self.preferences = Preferences()
            self.controller.preferences = self.preferences
            self.projects = Projects(self.controller.configuration.database_path,
                                     hidden=self.preferences.values['hidden_projects'])
            self.speech = DesktopSpeech(self.preferences)
            from zorvyq.voice import VoiceInteraction
            from zorvyq.tasks import TaskStore
            self.voice_interaction = VoiceInteraction()
            self.queued_speech = None
            self.tasks = TaskStore(self.preferences.path.parent/'tasks.sqlite3')
            from zorvyq.awareness.store import ActivityStore
            from zorvyq.awareness.monitor import MonitoringManager
            self.activity_store = ActivityStore(self.preferences.path.parent/'activity.sqlite3')
            from zorvyq.awareness.runtime import LocalRuntime
            self.monitoring = MonitoringManager(self.activity_store,
                runtime=LocalRuntime(self.activity_store.path.parent/'activitywatch'))
            self.nmap = Nmap()
            from zorvyq.operations.engine import Engine
            self.operations = Engine()
            from zorvyq.awareness.intelligence import ActivityQueries
            self.activity_queries = ActivityQueries(self.activity_store, self.tasks, self.operations.permissions, self.monitoring)
            self.close_requested = False
            self.shutdown_complete = False
            self.project_page = None
            self.project_dialog = None
            self.active_model = DEFAULT_MODEL
            self.worker = None
            self.pending = None
            self.busy = False
            self.started = None
            self.last_error = 'None'
            self.audio_unsafe = False
            self.speech_enabled = False
            self.large_text = False
            self.light_mode = False
            self.poll_enabled = True
            self.chats = {}
            self.pages = {}
            self.cards = {}
            self.feature_labels = {}
            self.cached_models = {'installed': [], 'loaded': []}
            self.setWindowIcon(QIcon(str(ROOT/'assets/zorvyq.svg')))
            central = QWidget()
            self.setCentralWidget(central)
            shell = QVBoxLayout(central)
            shell.setContentsMargins(16, 12, 16, 10)
            top = QHBoxLayout()
            logo = label('Z', 'logo'); logo.setFixedSize(42, 42)
            top.addWidget(logo)
            top.addWidget(label('ZORVYQ', 'brand'))
            top.addStretch()
            self.top_status = label('Qwen3:4b  ·  Checking local service…')
            top.addWidget(self.top_status)
            top.addWidget(label('● Local-first', 'accent'))
            top.addWidget(button('Settings', lambda: self.navigate('Settings')))
            shell.addLayout(top)
            middle = QHBoxLayout()
            self.sidebar = QListWidget()
            self.sidebar.setObjectName('sidebar')
            self.sidebar.setMaximumWidth(190)
            self.sidebar.setMinimumWidth(135)
            names = ['Dashboard', 'AI Chat', 'Cybersecurity', 'Knowledge', 'Desktop Tools',
                     'Voice', 'My Tasks', 'AI Models', 'Activity History', 'System Operations', 'Cybersecurity Operations', 'Settings', 'About']
            self.sidebar.addItems(names)
            middle.addWidget(self.sidebar)
            self.stack = QStackedWidget()
            middle.addWidget(self.stack, 1)
            shell.addLayout(middle, 1)
            for name in names:
                body = QWidget()
                layout = QVBoxLayout(body)
                layout.setContentsMargins(22, 16, 22, 20)
                layout.setSpacing(14)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(body)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                self.stack.addWidget(scroll)
                self.pages[name] = layout
            self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
            self.sidebar.setCurrentRow(0)
            from zorvyq.desktop.awareness import AwarenessPanel
            self.awareness_panel = AwarenessPanel(self, self.activity_store, self.monitoring)
            self.dashboard()
            self.chat_page('AI Chat', False)
            self.chat_page('Cybersecurity', True)
            self.knowledge_page()
            self.tools_page()
            self.voice_page()
            from zorvyq.desktop.tasks import TasksPanel
            self.tasks_panel = TasksPanel(self, self.tasks)
            self.pages['My Tasks'].addWidget(self.tasks_panel)
            self.models_page()
            self.activity_page()
            from zorvyq.desktop.operations import OperationsPanel
            self.operation_panel = OperationsPanel(self, self.operations)
            self.pages['System Operations'].addWidget(self.operation_panel)
            self.cyber_operations = OperationsPanel(self, self.operations, security=True)
            self.pages['Cybersecurity Operations'].addWidget(self.cyber_operations)
            self.settings_page()
            self.pages['Settings'].insertWidget(2, self.awareness_panel.controls)
            self.sidebar.currentRowChanged.connect(lambda row: self.awareness_panel.refresh()
                if list(self.pages)[row] in ('Dashboard', 'Activity History') else None)
            if self.activity_store.preferences()['start_at_login']:
                self.monitoring.start()
            self.about_page()
            footer = QHBoxLayout()
            self.status = label('Ready · Session messages are not saved')
            footer.addWidget(self.status, 1)
            self.progress = QProgressBar()
            self.progress.setRange(0, 0)
            self.progress.setMaximumWidth(150)
            self.progress.hide()
            footer.addWidget(self.progress)
            shell.addLayout(footer)
            self.apply_theme(False)
            self.timer = QTimer(self)
            self.timer.setInterval(15000)
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
            self.elapsed_timer = QTimer(self)
            self.elapsed_timer.setInterval(1000)
            self.elapsed_timer.timeout.connect(self.update_elapsed)
            self.elapsed_timer.start()
            QTimer.singleShot(0, self.refresh)
            self.reminder_timer = QTimer(self)
            self.reminder_timer.setInterval(30000)
            self.reminder_timer.timeout.connect(self.reminders)
            self.reminder_timer.start()
            QTimer.singleShot(1000, self.reminders)
            self.welcome_deadline = monotonic()+20
            QTimer.singleShot(1500, self.welcome_speech)

        def heading(self, name, title, subtitle):
            layout = self.pages[name]
            layout.addWidget(label(title, 'heading'))
            layout.addWidget(label(subtitle, 'muted'))
            return layout

        def navigate(self, name):
            self.sidebar.setCurrentRow(list(self.pages).index(name))

        def dashboard(self):
            from zorvyq.projects import greeting
            layout = self.heading('Dashboard', greeting(), 'Would you like to resume previous work?')
            layout.addWidget(self.awareness_panel.dashboard)
            self.task_summary = label(self.tasks.summary())
            layout.addWidget(self.task_summary)
            self.task_reminders = label('Upcoming reminders: none')
            layout.addWidget(self.task_reminders)
            layout.addWidget(button('Review pending tasks', lambda: self.navigate('My Tasks')))
            layout.addWidget(button('Open cybersecurity operations', lambda: self.navigate('Cybersecurity Operations')))
            self.recent_rows = QVBoxLayout()
            layout.addLayout(self.recent_rows)
            self.render_recent()
            layout.addWidget(button('Choose Another Project', lambda: self.choose_projects('AI Chat')))
            layout.addWidget(button('Clear recent work', self.clear_recent))
            dismiss = button('Dismiss welcome', lambda: self.navigate('AI Chat'))
            layout.addWidget(dismiss)
            hero = QFrame(); hero.setObjectName('hero')
            h = QVBoxLayout(hero)
            h.addWidget(label('Intelligence, on your terms.', 'heroTitle'))
            h.addWidget(label('Reason locally. Explore approved knowledge. Stay in control of every action.'))
            h.addWidget(button('Start a conversation  →', lambda: self.navigate('AI Chat')))
            layout.addWidget(hero)
            grid = QGridLayout()
            for i, (key, title) in enumerate([('engine','AI Engine'), ('specialist','Cybersecurity Specialist'),
                ('knowledge','Knowledge Base'), ('voice','Voice System'), ('tools','Desktop Tools'), ('privacy','Privacy')]):
                frame = QFrame(); frame.setObjectName('card')
                card = QVBoxLayout(frame)
                card.addWidget(label(title, 'muted'))
                value = label('Checking…', 'cardValue')
                card.addWidget(value)
                self.cards[key] = value
                grid.addWidget(frame, i//2, i%2)
            self.cards['privacy'].setText('Local-first operation\nNo desktop chat persistence')
            layout.addLayout(grid)
            actions = QGridLayout()
            for i, (text, page) in enumerate([('Ask cybersecurity', 'Cybersecurity'), ('Explore knowledge', 'Knowledge'),
                ('Check models', 'AI Models'), ('Open settings', 'Settings'), ('Installed capabilities', 'About')]):
                actions.addWidget(button(text, lambda checked=False, p=page: self.navigate(p)), i//2, i%2)
            layout.addLayout(actions)
            layout.addStretch()

        def chat_page(self, name, security):
            layout = self.heading(name, 'ZORVYQ Cybersecurity Intelligence' if security else 'AI Chat',
                'Current-session messages only · Not saved · Qwen3:4b')
            from zorvyq.security import SPECIALIST
            knowledge = QCheckBox('Use Approved Knowledge')
            knowledge.setChecked(security)
            if not security:
                layout.addWidget(knowledge)
            model = QComboBox()
            model.addItem('Qwen3:4b', DEFAULT_MODEL)
            model.addItem('Foundation-Sec-8B-Instruct — experimental', SPECIALIST)
            model.setCurrentIndex(max(0, model.findData(self.preferences.values['selected_model'])))
            if security:
                self.cyber_mode = QComboBox()
                self.cyber_mode.addItems(['Approved Knowledge', 'Specialist Chat'])
                layout.addWidget(self.cyber_mode)
                model.setCurrentIndex(0)
                model.setEnabled(False)
                self.security_model = model
                def change_cyber_mode(index):
                    knowledge.setChecked(index == 0)
                    model.setCurrentIndex(0 if index == 0 else 1)
                    model.setEnabled(False)  # Each explicit workspace mode names its model.
                self.cyber_mode.currentIndexChanged.connect(change_cyber_mode)
                layout.addWidget(label('Approved Knowledge: Qwen with exact one-time permission and verified citations. '
                    'Specialist Chat: experimental Foundation-Sec model knowledge; answers are not source-verified. Automatic routing OFF.', 'muted'))
                layout.addWidget(button('Explore approved knowledge', lambda: self.navigate('Knowledge')))
                layout.addWidget(button('Cybersecurity Operations', lambda: self.navigate('Cybersecurity Operations')))
            else:
                self.chat_model = model
                model.currentIndexChanged.connect(lambda: self.preferences.save(selected_model=model.currentData()))
            layout.addWidget(label('Model'))
            layout.addWidget(model)
            message_body = QWidget()
            messages = QVBoxLayout(message_body)
            messages.setSpacing(12)
            messages.setAlignment(Qt.AlignmentFlag.AlignTop)
            conversation = QScrollArea()
            conversation.setWidgetResizable(True)
            conversation.setMinimumHeight(210)
            conversation.setWidget(message_body)
            conversation.setFrameShape(QFrame.Shape.NoFrame)
            layout.addWidget(conversation, 1)
            composer = Composer()
            composer.setPlaceholderText('Ask ZORVYQ…  Enter to send · Shift+Enter for a new line')
            composer.setMinimumHeight(90)
            composer.setMaximumHeight(160)
            composer.setAccessibleName('Message to ZORVYQ')
            depth = QHBoxLayout()
            modes = QButtonGroup(self)
            modes.setExclusive(True)
            for title in ('Short', 'Medium', 'Deep Analysis'):
                control = QPushButton(title)
                control.setCheckable(True)
                control.setChecked(title == self.preferences.values['response_mode'])
                control.clicked.connect(lambda checked=False, value=title: self.select_depth(value))
                modes.addButton(control)
                depth.addWidget(control)
            layout.addLayout(depth)
            layout.addWidget(label('Response depth preference; internal chain of thought is never displayed.', 'muted'))
            layout.addWidget(composer)
            controls = QHBoxLayout()
            send = button('Send', lambda: self.send_chat(name))
            controls.addWidget(send)
            talk = button('Talk to ZORVYQ', self.microphone)
            talk.setProperty('runtimeAction', True)
            controls.addWidget(talk)
            cancel = button('Cancel knowledge retrieval')
            cancel.setEnabled(False)
            cancel.setToolTip('Cancels vector/embedding waits. An already running generation still finishes within its provider timeout.')
            cancel.clicked.connect(self.controller.cancel_knowledge)
            controls.addWidget(cancel)
            controls.addStretch()
            state = label('Ready', 'muted')
            controls.addWidget(state)
            layout.addLayout(controls)
            self.chats[name] = {'input': composer, 'messages': messages, 'knowledge': knowledge, 'state': state,
                                'send': send, 'cancel':cancel, 'turns': [], 'scroll': conversation, 'model': model, 'modes': modes}
            diagnostic = QPlainTextEdit()
            diagnostic.setReadOnly(True); diagnostic.setMaximumHeight(130); diagnostic.hide()
            layout.addWidget(button('Technical status', lambda: diagnostic.setVisible(not diagnostic.isVisible())))
            layout.addWidget(diagnostic)
            self.chats[name]['diagnostic'] = diagnostic
            composer.send.connect(lambda: self.send_chat(name))

        def select_depth(self, value):
            from zorvyq.model_modes import MODE_LENGTH
            self.preferences.save(response_mode=value, answer_length=MODE_LENGTH[value])
            for chat in self.chats.values():
                for control in chat['modes'].buttons():
                    control.setChecked(control.text() == value)

        def bubble(self, page, role, text, verified=False):
            chat = self.chats[page]
            frame = QFrame(); frame.setObjectName('userBubble' if role == 'You' else 'card')
            layout = QVBoxLayout(frame)
            layout.addWidget(label(role, 'accent'))
            answer, marker, sources = text.partition('\n\nVerified sources:\n') if verified else (text, '', '')
            browser = SafeBrowser()
            browser.setOpenLinks(False)
            browser.setOpenExternalLinks(False)
            browser.setMinimumHeight(90)
            browser.setMaximumHeight(430)
            browser.setFrameShape(QFrame.Shape.NoFrame)
            browser.setMarkdown(answer)
            layout.addWidget(browser)
            if marker:
                for source in sources.split('\n['):
                    source = source if source.startswith('[') else '['+source
                    first = source.split('\n', 1)[0]
                    toggle = button(first)
                    detail = QPlainTextEdit(source)
                    detail.setReadOnly(True)
                    detail.setMaximumHeight(180)
                    detail.hide()
                    toggle.clicked.connect(lambda checked=False, d=detail: d.setVisible(not d.isVisible()))
                    layout.addWidget(toggle)
                    layout.addWidget(detail)
            if role != 'You':
                copy = button('Copy answer', lambda checked=False, value=text: QApplication.clipboard().setText(value))
                layout.addWidget(copy)
                layout.addWidget(button('Speak this answer…', lambda checked=False, value=text: self.speak_answer(value)))
            chat['messages'].addWidget(frame)
            chat['turns'].append(frame)
            QTimer.singleShot(0, lambda: chat['scroll'].verticalScrollBar().setValue(
                chat['scroll'].verticalScrollBar().maximum()))
            # Bound current-session widgets without writing history anywhere.
            if len(chat['turns']) > 40:
                old = chat['turns'].pop(0)
                chat['messages'].removeWidget(old)
                old.deleteLater()

        def send_chat(self, name):
            if self.busy or self.audio_unsafe:
                return
            chat = self.chats[name]
            text = chat['input'].toPlainText().strip()
            if not text:
                return
            from zorvyq.awareness.intelligence import intent as activity_intent
            activity_request = activity_intent(text)
            if activity_request:
                chat['input'].clear()
                if not self.awareness_panel.confirm('Allow this activity query once? Reads only the requested local records. Task titles are read only for an explicit completed-task query. No model receives these records.'):
                    self.status.setText('Activity access denied.')
                    return
                plan = self.activity_queries.plan(activity_request)
                ticket = self.operations.permissions.approve(plan, confirmed=True)
                self.run_task('activity_answer', lambda: self.activity_queries.run(plan, ticket), name)
                return
            from zorvyq.tasks import intent
            request = intent(text)
            if request:
                chat['input'].clear()
                # Task content stays in its dedicated store and task UI, not chat history.
                reply = self.tasks_panel.handle(request)
                self.status.setText(reply)
                self.say(reply)
                return
            import re
            normalized = re.sub(r'^(?:zorvyq|friday)[, ]+', '', text.casefold()).rstrip('.!?')
            if self.project_page is not None and self.project_page != name:
                self.projects.cancel()
                self.project_page = None
                self.close_project_dialog()
            if normalized in {'open vs code', 'open vscode', 'open visual studio code'}:
                chat['input'].clear()
                self.choose_projects(name)
                return
            if self.project_page == name:
                chat['input'].clear()
                self.project_page = None
                self.close_project_dialog()
                if text.isdecimal():
                    try:
                        number = int(text)
                        self.run_task('project', lambda: self.projects.select(number), name)
                    except ValueError as error:
                        self.bubble(name, 'ZORVYQ', str(error))
                    return
                self.projects.cancel()
                if normalized in {'cancel', 'cancel selection'}:
                    self.bubble(name, 'ZORVYQ', 'Project selection cancelled.')
                    return
            if len(text.encode()) > (2048 if chat['knowledge'].isChecked() else 8192):
                QMessageBox.information(self, 'Message limit', 'Shorten the message to the displayed mode’s input budget (knowledge: 2048 bytes; chat: 8192 bytes).')
                return
            self.bubble(name, 'You', text)
            chat['input'].clear()
            chat['state'].setText('Generating · '+DEFAULT_MODEL)
            use_knowledge = chat['knowledge'].isChecked()
            # Qt controls are read only on the GUI thread, before worker dispatch.
            model = chat['model'].currentData()
            mode = self.preferences.values['response_mode']
            self.active_model = model
            chat['state'].setText('Generating · '+model)
            self.run_task('chat', lambda: self.controller.ask(text, use_knowledge, model=model, mode=mode, progress=self.worker.progress.emit), name)

        def knowledge_page(self):
            layout = self.heading('Knowledge', 'Approved knowledge', 'Read-only source metadata · Document text requires separate knowledge approval')
            self.search = QLineEdit()
            self.search.setPlaceholderText('Search approved titles and topic metadata…')
            self.search.textChanged.connect(self.filter_knowledge)
            layout.addWidget(self.search)
            self.knowledge_state = label('Checking inventory…', 'muted')
            layout.addWidget(self.knowledge_state)
            self.knowledge_rows = QVBoxLayout()
            layout.addLayout(self.knowledge_rows)
            layout.addWidget(button('Refresh inventory', self.refresh))
            layout.addStretch()
            self.knowledge_widgets = []

        def filter_knowledge(self):
            query = self.search.text().casefold()
            matches = 0
            for haystack, widget in self.knowledge_widgets:
                shown = query in haystack
                widget.setVisible(shown)
                matches += shown
            if self.knowledge_widgets:
                self.knowledge_state.setText(f'{matches} metadata matches · Mentions do not establish comprehensive coverage. '
                    'No embeddings or private document content were read.')

        def tools_page(self):
            layout = self.heading('Desktop Tools', 'Installed desktop capabilities',
                'Invocations use the existing tool gateway through AI Chat. Exact permissions still apply.')
            layout.addWidget(label('Protected operations require existing local owner authentication and separate exact-operation approval. '
                'Approved project launches share the existing persistent recent-work store. Browser visibility requires live acceptance.', 'muted'))
            self.tool_rows = QVBoxLayout()
            layout.addLayout(self.tool_rows)
            layout.addWidget(button('Open tool conversation', lambda: self.navigate('AI Chat')))
            layout.addStretch()

        def voice_page(self):
            layout = self.heading('Voice', 'Settings → Voice', 'Microphone OFF · Explicit activation only')
            self.voice_state = label('Speech: checking executable · Audio output unverified\nMicrophone: disabled; activation requires confirmation', 'muted')
            layout.addWidget(self.voice_state)
            self.speech_toggle = QCheckBox('Enable speech output')
            self.speech_toggle.setChecked(self.preferences.values['speech_enabled'])
            self.speech_toggle.toggled.connect(self.set_speech_enabled)
            layout.addWidget(self.speech_toggle)
            welcome = QCheckBox('Speak Welcome Greeting')
            welcome.setChecked(self.preferences.values['speak_welcome'])
            welcome.toggled.connect(lambda value: self.preferences.save(speak_welcome=value))
            layout.addWidget(welcome)
            self.interaction_state = label('IDLE')
            layout.addWidget(self.interaction_state)
            layout.addWidget(button('Stop speaking', self.speech.stop))
            layout.addWidget(button('Stop recording / Cancel transcription', self.voice_interaction.cancelled.set))
            self.voice_choice = QComboBox()
            voices = self.speech.voices()
            for identifier, name in voices:
                self.voice_choice.addItem(name+' — '+identifier, identifier)
            if voices:
                selected = self.speech.resolve_voice()
                self.voice_choice.setCurrentIndex(self.voice_choice.findData(selected))
            self.voice_choice.currentIndexChanged.connect(lambda: self.preferences.save(voice=self.voice_choice.currentData()) if self.voice_choice.currentData() else None)
            layout.addWidget(label('Installed voices: '+str(len(voices))+(' (only one available)' if len(voices)==1 else '')+' · '+self.speech.notice))
            layout.addWidget(self.voice_choice)
            for key, title, low, high in [('speed','Speech speed',80,450), ('volume','Speech volume',0,200)]:
                layout.addWidget(label(title))
                control = QSpinBox(); control.setRange(low, high); control.setValue(self.preferences.values[key])
                control.valueChanged.connect(lambda value, k=key: self.preferences.save(**{k:value}))
                layout.addWidget(control)
            layout.addWidget(button('Test Voice', lambda: self.run_task('speech', lambda: self.speech.speak('Hello, I am ZORVYQ, your local AI assistant.')) if self.speech_toggle.isChecked() else self.voice_progress.setText('Enable speech output first.')))
            self.microphone_toggle = QCheckBox('Enable microphone actions for this session')
            layout.addWidget(self.microphone_toggle)
            for title in ('Input device', 'Output device'):
                selector = QComboBox(); selector.addItem('ALSA hw:CARD=Generic_1,DEV=0 — approved capture device' if title == 'Input device' else 'Desktop system default — backend does not support output selection'); selector.setEnabled(False)
                layout.addWidget(label(title)); layout.addWidget(selector)
            self.speech_text = QPlainTextEdit()
            self.speech_text.setPlaceholderText('Enter text to speak explicitly. Answers are never spoken automatically.')
            self.speech_text.setMaximumHeight(140)
            layout.addWidget(self.speech_text)
            layout.addWidget(button('Speak entered text', self.speak))
            layout.addWidget(button('Talk to ZORVYQ', self.microphone))
            self.voice_progress = label('No recording started', 'muted')
            layout.addWidget(self.voice_progress)
            layout.addStretch()

        def speak(self):
            text = self.speech_text.toPlainText().strip()
            if self.busy or not self.speech_toggle.isChecked() or not text:
                self.status.setText('Enable explicit speech and enter text first.')
                return
            self.run_task('speech', lambda: self.speech.speak(text.replace('\n', ' ')))

        def microphone(self):
            if not self.microphone_toggle.isChecked():
                self.voice_progress.setText('Enable microphone actions first; microphone remains OFF.')
                return
            if self.busy or self.audio_unsafe:
                return
            answer = QMessageBox.question(self, 'Activate microphone once',
                'Record up to eight seconds locally? Audio is removed before transcript review. '
                'Nothing is sent until you approve the transcript.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            from zorvyq.voice import VoiceState
            self.voice_interaction.begin(VoiceState.LISTENING)
            self.set_voice_state(VoiceState.LISTENING)
            self.run_task('microphone', self.capture)

        def capture(self):
            from tempfile import TemporaryDirectory
            from friday.voice.configuration import resolve_configuration
            from friday.voice.backend import LocalVoiceBackend
            configuration = resolve_configuration()
            if configuration is None:
                from friday.voice.backend import VoiceError
                error = VoiceError('Offline speech recognition is not configured.')
                error.category = 'stt_unavailable'
                raise error
            backend = LocalVoiceBackend(configuration, self.voice_interaction.cancelled)
            backend.verify()
            with TemporaryDirectory(prefix='zorvyq-voice-') as temporary:
                path = Path(temporary)/'capture.wav'
                backend.capture(path, self.worker.progress.emit)
                self.worker.progress.emit('TRANSCRIBING')
                transcript = backend.transcribe(path)
                backend.check_cancelled()
            if (type(transcript) is not str or not transcript.strip() or len(transcript.encode()) > 4096 or
                    any((ord(c)<32 and c not in '\n\t') or ord(c)==127 for c in transcript)):
                raise ValueError('Invalid transcript')
            return transcript.strip()

        def set_speech_enabled(self, enabled):
            self.preferences.save(speech_enabled=enabled)
            if not enabled:
                self.queued_speech = None
                self.speech.stop()

        def set_voice_state(self, state):
            self.voice_interaction.state = state
            self.interaction_state.setText(state.value)
            self.setWindowTitle('ZORVYQ — Local AI Assistant' + ('' if state.value == 'IDLE' else ' · '+state.value))

        def say(self, text):
            from zorvyq.voice import speech_summary
            if self.busy or self.close_requested or not self.preferences.values['speech_enabled']:
                return
            summary = speech_summary(text, self.preferences.values['response_mode'])
            if summary:
                self.run_task('speech', lambda: self.speech.speak(summary))

        def speak_answer(self, text):
            if self.busy:return
            if QMessageBox.question(self, 'Speak visible answer',
                    'Read this answer aloud? It may contain private information. Long or structured answers use a short summary.',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.say(text)

        def welcome_speech(self):
            if self.close_requested or not self.preferences.values['speak_welcome'] or not self.preferences.values['speech_enabled']:return
            # A bounded desktop-session wait; no microphone and no retry after playback failure.
            import os
            runtime = Path(os.environ.get('XDG_RUNTIME_DIR','/nonexistent'))
            ready = (runtime/'pulse/native').exists() or (runtime/'pipewire-0').exists()
            if (self.busy or not ready) and monotonic() < self.welcome_deadline:
                QTimer.singleShot(500, self.welcome_speech)
                return
            if self.voice_interaction.welcome(self.preferences.values) and ready and not self.busy:
                from zorvyq.projects import greeting
                count = len(self.tasks.rows(view='Active'))
                self.say(greeting()+f' Welcome back. You have {count} pending or in progress tasks. Would you like to resume your previous work?')

        def reminders(self):
            if self.close_requested:return
            import sqlite3
            try:
                rows = self.tasks.claim_reminders()
            except (sqlite3.Error, OSError, ValueError):
                self.status.setText('Reminder check failed; saved reminders remain in My Tasks. No notification confirmed.')
                return
            if rows:
                self.tasks_panel.refresh()
                # Persistent claim prevents duplicate notifications across restarts.
                dialog = QDialog(self)
                dialog.setWindowTitle('ZORVYQ task reminders')
                layout = QVBoxLayout(dialog)
                layout.addWidget(label('Due or missed reminders:'))
                for row in rows:layout.addWidget(label(row['title']))
                close = button('Dismiss', dialog.accept);layout.addWidget(close)
                dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                dialog.show()
                from PySide6.QtWidgets import QSystemTrayIcon
                if QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages():
                    if not hasattr(self, 'reminder_tray'):
                        self.reminder_tray = QSystemTrayIcon(self.windowIcon(), self)
                        self.reminder_tray.show()
                    self.reminder_tray.showMessage('ZORVYQ reminders', f'{len(rows)} task reminders are due. Review ZORVYQ.')

        def models_page(self):
            layout = self.heading('AI Models', 'Local model control',
                'Qwen3:4b is the default · Manual Foundation-Sec chat available · Automatic routing OFF')
            layout.addWidget(label('Residency is shared across Ollama clients. Loaded does not mean idle or owned by ZORVYQ. '
                'Conflicting models block inference; ZORVYQ never evicts them automatically.', 'muted'))
            layout.addWidget(button('Refresh installed and loaded models', self.refresh))
            self.model_rows = QVBoxLayout()
            layout.addLayout(self.model_rows)
            self.model_choice = QComboBox()
            layout.addWidget(self.model_choice)
            layout.addWidget(button('Unload selected resident model…', self.unload))
            layout.addWidget(button('View selected model details', self.model_details))
            load = button('Manual preload unavailable')
            load.setEnabled(False)
            load.setToolTip('This checkpoint loads Qwen on an explicit question only; loading candidates is not approved.')
            layout.addWidget(load)
            layout.addStretch()

        def unload(self):
            model = self.model_choice.currentText()
            if not model or self.busy:
                return
            choice = QMessageBox.warning(self, 'Shared Ollama workload',
                f'Unload {model}? Ollama does not expose other clients’ ownership or busy state. '
                'This may interrupt another active client. ZORVYQ has no active request. Approve this exact unload?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if choice == QMessageBox.StandardButton.Yes:
                self.run_task('unload', lambda: self.controller.unload(model, external_approved=True))

        def model_details(self):
            model = self.model_choice.currentText()
            if model and not self.busy:
                def details():
                    raw = self.controller.service.request('/api/show', {'model': model, 'verbose': False})
                    # Do not display templates, system prompts, local paths or model-file metadata.
                    return {k: raw.get(k) for k in ('details', 'capabilities')}
                self.run_task('details', details)

        def activity_page(self):
            layout = self.heading('Activity History', 'Local activity history', 'Owner-controlled collection · Monitoring OFF until opt-in')
            layout.addWidget(self.awareness_panel)
            self.activity = label('Waiting for subsystem checks…')
            layout.addWidget(self.activity)
            layout.addWidget(label('GUI RSS is separate from Ollama residency. Ollama memory may be shared with other clients. '
                'No prompts, retrieved evidence or answers are stored as telemetry.', 'muted'))
            layout.addStretch()

        def settings_page(self):
            layout = self.heading('Settings', 'Your workspace preferences', 'Answer length and voice preferences persist locally')
            light = QCheckBox('Light appearance')
            light.toggled.connect(self.apply_theme)
            layout.addWidget(light)
            large = QCheckBox('Larger text')
            def set_large_text(value):
                self.large_text = value
                self.apply_theme(self.light_mode)
            large.toggled.connect(set_large_text)
            layout.addWidget(large)
            poll = QCheckBox('Refresh local service metadata every 15 seconds')
            poll.setChecked(True)
            poll.toggled.connect(lambda value: setattr(self, 'poll_enabled', value))
            layout.addWidget(poll)
            adaptive = QCheckBox('Legacy adaptive classification (composer response depth takes precedence)')
            def set_adaptive(value):
                if self.busy:
                    adaptive.blockSignals(True); adaptive.setChecked(not value); adaptive.blockSignals(False)
                    return
                from dataclasses import replace
                configuration = replace(self.controller.configuration, adaptive_workloads=value)
                self.controller.configuration = configuration
                if self.controller.assistant is not None:
                    self.controller.assistant.workload_configuration = configuration
                    self.controller.assistant.adaptive_workloads = value
            adaptive.toggled.connect(set_adaptive)
            layout.addWidget(adaptive)
            layout.addWidget(label('Default model: qwen3:4b; AI Chat permits manual Foundation-Sec selection\n'
                'Approved Knowledge generation: Qwen only until separate specialist acceptance\n'
                'Local model service: loopback HTTP\nPrivacy: desktop messages are never persisted\n'
                'Knowledge: allow-once exact scope; no saved approvals\n'
                'Voice: explicit speech toggle and microphone confirmation on Voice page\n'
                'Startup: dashboard only; no inference, audio, document retrieval or browser\n'
                'Owner authentication: existing verifier and cooldown; hidden dialog on protected actions only\n'
                'Credentials and saved permissions: unchanged; no GUI credential editing\n'
                'Answer length and voice preferences persist locally; theme settings reset on close.', 'muted'))
            layout.addWidget(label('Answer Length'))
            lengths = QComboBox(); lengths.addItems(['Short', 'Balanced', 'Detailed'])
            lengths.setCurrentText(self.preferences.values['answer_length'])
            lengths.currentTextChanged.connect(lambda value: self.select_depth({'Short':'Short','Balanced':'Medium','Detailed':'Deep Analysis'}[value]))
            layout.addWidget(lengths)
            hidden = QCheckBox('Include hidden direct project folders')
            hidden.setChecked(self.preferences.values['hidden_projects'])
            hidden.toggled.connect(self.hidden_projects)
            layout.addWidget(hidden)
            from zorvyq.startup import Startup
            state = Startup().inventory()
            self.login_toggle = QCheckBox('Launch ZORVYQ when I log in')
            self.login_toggle.setChecked(state['enabled'] or state['legacy_enabled'])
            self.login_toggle.clicked.connect(self.change_startup)
            layout.addWidget(self.login_toggle)
            if state['legacy_enabled']:
                layout.addWidget(button('Replace legacy login startup with ZORVYQ…', lambda: self.change_startup(True)))
            layout.addWidget(label('Legacy login startup preserved pending exact-entry migration approval.' if state['legacy_enabled'] else 'Login startup changes require explicit confirmation.', 'muted'))
            layout.addWidget(button('Voice preferences', lambda: self.navigate('Voice')))
            layout.addStretch()

        def hidden_projects(self, enabled):
            self.preferences.save(hidden_projects=enabled)
            self.projects.hidden = enabled
            self.projects.cancel()
            self.project_page = None
            self.close_project_dialog()

        def change_startup(self, enabled):
            from zorvyq.startup import Startup
            startup = Startup(); state = startup.inventory()
            detail = ('Disable exactly '+state['legacy']+' with a reversible .desktop.zorvyq-backup, and ' if state['legacy_enabled'] else '')
            detail += ('enable' if enabled else 'disable')+' the ZORVYQ graphical login entry. Ordinary Ubuntu Terminal settings are untouched. Apply?'
            approved = QMessageBox.question(self, 'Approve login startup change', detail,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
            try:
                if approved:
                    startup.apply(enabled, approved=True, fingerprint=state['fingerprint'])
            except (OSError, ValueError, PermissionError):
                QMessageBox.information(self, 'Startup', 'Startup change could not complete. Review the startup migration guide and existing backup.')
            current = startup.inventory()
            self.login_toggle.setChecked(current['enabled'] or current['legacy_enabled'])

        def choose_projects(self, page):
            if self.busy: return
            self.close_project_dialog()
            self.projects.cancel()
            self.project_page = None
            try:
                rows = self.projects.enumerate()
            except (ValueError, OSError) as error:
                QMessageBox.information(self, 'VS Code projects', str(error)); return
            self.project_page = page
            self.navigate(page)
            if not rows:
                self.project_page = None
                self.bubble(page, 'ZORVYQ', 'No eligible project folders found under /home/vigneshwar/Projects.')
                return
            self.bubble(page, 'ZORVYQ', 'Which project would you like to open?\n\n'+'\n'.join(f'{i}. {p.name}' for i,p in enumerate(rows,1))+'\n\nType a number within two minutes, or cancel.')
            # The non-modal list and typed replies share this exact snapshot.
            dialog = QDialog(self); dialog.setWindowTitle('Select a numbered VS Code project')
            layout = QVBoxLayout(dialog)
            for i, path in enumerate(rows, 1):
                layout.addWidget(button(f'{i}. {path.name}', lambda checked=False, number=i, snapshot=rows: self.click_project(number, dialog, snapshot)))
            layout.addWidget(button('Use chat number / close chooser', dialog.close))
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.show()
            self.project_dialog = dialog

        def close_project_dialog(self):
            if self.project_dialog is not None:
                try:
                    self.project_dialog.close()
                except RuntimeError:
                    pass
                self.project_dialog = None

        def click_project(self, number, dialog, snapshot):
            if self.busy: return
            dialog.close()
            self.project_page = None
            self.run_task('project', lambda: self.projects.select_snapshot(number, snapshot))

        def render_recent(self):
            self.clear_layout(self.recent_rows)
            rows = self.projects.recent()
            if not rows:
                self.recent_rows.addWidget(label('No approved recent work saved yet.', 'muted'))
            for row, descriptor in rows:
                path = descriptor['path']
                self.recent_rows.addWidget(label(row['title'].replace('FRIDAY', 'ZORVYQ')+' · '+row['launched_at']))
                if row['application_id'] == 'vscode' and path:
                    self.recent_rows.addWidget(button('Continue '+Path(path).name+' in VS Code', lambda checked=False, p=path: self.run_task('project', lambda: self.projects.open(p))))
                else:
                    self.recent_rows.addWidget(label('Resume through approved Desktop Tools; saved target: '+str(path or row['application_id']), 'muted'))
                self.recent_rows.addWidget(button('Dismiss entry', lambda checked=False, entry=row['entry_id']: self.remove_recent(entry)))

        def remove_recent(self, entry):
            self.projects.remove(entry); self.render_recent()

        def clear_recent(self):
            self.projects.remove(); self.render_recent()

        def request_scan(self):
            self.navigate('Cybersecurity Operations')
            self.cyber_operations.open_details('network.discovery')

        def about_page(self):
            from zorvyq.features import features
            layout = self.heading('About', 'ZORVYQ', EXPANSION)
            layout.addWidget(label('A private, local-first intelligence workspace for Ubuntu.\n'
                'Phase 2A · Existing assistant services preserved behind a new desktop facade.', 'muted'))
            layout.addWidget(label('Installed capabilities', 'heading'))
            for feature in features():
                frame = QFrame(); frame.setObjectName('card')
                row = QVBoxLayout(frame)
                feature_label = label(feature.name+'  ·  '+feature.status, 'accent')
                self.feature_labels[feature.feature_id] = feature_label
                row.addWidget(feature_label)
                row.addWidget(label(feature.description))
                row.addWidget(label('ID: '+feature.feature_id+'\nImplementation: '+feature.implementation+
                    '\nPermission: '+feature.permission+'\nEvidence: '+feature.verification, 'muted'))
                row.addWidget(button('Open '+feature.action, lambda checked=False, p=feature.action: self.navigate(p)))
                layout.addWidget(frame)
            layout.addStretch()

        @Slot(object)
        def permission(self, ticket):
            if self.bridge.closing:
                ticket['event'].set()
                return
            if ticket.get('kind') == 'credential':
                secret, accepted = QInputDialog.getText(self, 'Owner authentication',
                    'Owner security passphrase for the current protected operation.\n'
                    'The existing local verifier checks it; no credential is saved by the desktop.',
                    QLineEdit.EchoMode.Password)
                ticket['secret'] = secret if accepted else None
                secret = None
                ticket['event'].set()
                return
            dialog = QDialog(self)
            dialog.setWindowTitle(ticket['title'])
            dialog.resize(620, 440)
            layout = QVBoxLayout(dialog)
            layout.addWidget(label(ticket['summary']))
            details = QPlainTextEdit(ticket['detail'])
            details.setReadOnly(True)
            details.hide()
            toggle = button('View detailed source / operation scope')
            toggle.clicked.connect(lambda: details.setVisible(not details.isVisible()))
            layout.addWidget(toggle)
            layout.addWidget(details)
            controls = QDialogButtonBox()
            deny = controls.addButton('Deny', QDialogButtonBox.ButtonRole.RejectRole)
            controls.addButton('Allow Once', QDialogButtonBox.ButtonRole.AcceptRole)
            deny.setDefault(True)
            controls.accepted.connect(dialog.accept)
            controls.rejected.connect(dialog.reject)
            layout.addWidget(controls)
            ticket['allowed'] = dialog.exec() == QDialog.DialogCode.Accepted
            ticket['event'].set()

        def run_task(self, action, operation, context=None):
            if self.busy or (self.audio_unsafe and action != 'shutdown'):
                return False
            if action in ('chat', 'speech'):
                from zorvyq.voice import VoiceState
                self.set_voice_state(VoiceState.PROCESSING if action == 'chat' else VoiceState.SPEAKING)
            self.busy = True
            self.pending = (action, context)
            self.started = monotonic()
            for control in self.findChildren(QPushButton):
                if control.property('runtimeAction'):
                    control.setEnabled(False)
            self.progress.show()
            self.status.setText('Working · '+action+(' · Cancel is available in the operation console' if action == 'operation' else ' · Waiting for bounded completion'))
            for chat in self.chats.values():
                chat['send'].setEnabled(False)
                chat['cancel'].setEnabled(action == 'chat' and chat is self.chats[context] and chat['knowledge'].isChecked())
                chat['model'].setEnabled(False)
                chat['knowledge'].setEnabled(False)
                for control in chat['modes'].buttons(): control.setEnabled(False)
            self.cyber_mode.setEnabled(False)
            self.worker = Worker(operation, self)
            self.worker.result.connect(self.task_result)
            self.worker.finished.connect(self.task_finished)
            self.worker.progress.connect(self.task_progress)
            self.worker.start()
            return True

        def task_progress(self, text):
            if text == 'TRANSCRIBING':
                from zorvyq.voice import VoiceState
                self.set_voice_state(VoiceState.TRANSCRIBING)
            if self.pending and self.pending[0] == 'chat':
                self.chats[self.pending[1]]['state'].setText(text)
            elif self.pending and self.pending[0] == 'operation':
                self.pending[1].on_progress(text)
            else:
                self.voice_progress.setText(text)

        def update_elapsed(self):
            if self.busy and self.started is not None:
                action = self.pending[0]
                elapsed = monotonic()-self.started
                self.status.setText(f'{action.capitalize()} · {elapsed:.0f}s'+(' · '+self.active_model if action in {'chat','analysis'} else '')+
                    (' · Waiting for bounded provider completion' if action == 'chat' else ''))
                if action == 'chat':
                    self.activity.setText(f'Current model: {self.active_model}\nInference: running\nElapsed: {elapsed:.0f}s\n'
                        'Resource and residency snapshot paused during the request.\nLast error: '+self.last_error)

        @Slot(object)
        def task_result(self, result):
            action, context = self.pending
            if not result['ok']:
                self.last_error = result['category']
                if action in ('speech','microphone','chat'):
                    from zorvyq.voice import VoiceState
                    self.set_voice_state(VoiceState.IDLE if self.last_error == 'cancelled' else VoiceState.ERROR)
                self.audio_unsafe = result['category'] == 'audio_cleanup_unconfirmed'
                from zorvyq.diagnostics import explanation
                text = explanation(self.last_error)
                self.status.setText(text)
                if action in {'speech', 'microphone'}:
                    self.voice_progress.setText('Microphone OFF · Last safe audio error: '+self.speech.last_error if action == 'speech' else 'Microphone OFF · Last safe audio error: '+self.last_error)
                    self.voice_state.setText('Offline audio remains unverified · Last safe audio error: '+self.speech.last_error if action == 'speech' else 'Microphone OFF · '+self.last_error)
                if action == 'chat':
                    self.chats[context]['state'].setText(self.last_error)
                    self.chats[context]['diagnostic'].setPlainText(json.dumps({'failure_category':self.last_error},indent=2))
                    self.bubble(context, 'ZORVYQ', text)
                elif action in {'operation', 'analysis'}:
                    context.status.setText(text+' Deterministic report retained.')
                elif action == 'shutdown':
                    self.shutdown_complete = True
                    self.status.setText('Shutdown cleanup unconfirmed; shared Ollama service was not stopped.')
                elif action not in ('refresh','speech','microphone'):
                    QMessageBox.information(self, 'ZORVYQ', text)
                return
            value = result['value']
            self.last_error = 'None'
            if action == 'refresh':
                self.render_status(value)
            elif action == 'activity_summary':
                context.summary.setText(value)
            elif action == 'activity_answer':
                self.bubble(context, 'ZORVYQ', value)
                self.queued_speech = value
            elif action == 'chat':
                status = value.get('knowledge_status') or {}
                verified = status.get('citation_validation_status') == 'verified'
                from zorvyq.diagnostics import explanation, safe_status
                category = status.get('failure_category')
                self.bubble(context, 'ZORVYQ', explanation(category) if category else value['answer'], verified)
                if not category and value.get('speech_eligible') and not status:
                    self.queued_speech = value['answer']
                self.chats[context]['diagnostic'].setPlainText(json.dumps(safe_status(status),indent=2))
                category = status.get('failure_category')
                self.last_error = category or 'None'
                self.chats[context]['state'].setText(status.get('status', 'Complete')+(' · '+category if category else ''))
            elif action == 'operation':
                context.finished(value)
            elif action == 'analysis':
                context.analyzed(value)
            elif action == 'shutdown':
                self.shutdown_complete = True
                self.status.setText(self.controller.residency.status)
            elif action == 'details':
                QMessageBox.information(self, 'Model details', json.dumps(value, indent=2))
            elif action == 'unload':
                self.render_models(value)
            elif action == 'microphone':
                self.voice_progress.setText('Microphone OFF · Audio removed · Transcript ready for review')
                dialog = QDialog(self); dialog.setWindowTitle('Review local transcript'); dialog.resize(560, 340)
                layout = QVBoxLayout(dialog)
                layout.addWidget(label('Send this transcript to AI Chat? It will not be saved.'))
                preview = QPlainTextEdit(value); layout.addWidget(preview)
                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self.chats['AI Chat']['input'].setPlainText(preview.toPlainText())
                    self.navigate('AI Chat')
                    # Final Send remains explicit after the worker has finished.
                    self.status.setText('Transcript approved · Press Send to submit')
                preview.clear()
                dialog.deleteLater()
            elif action == 'project':
                self.render_recent()
                self.status.setText('VS Code launch accepted; window visibility unverified')
            elif action == 'speech':
                self.voice_progress.setText('Speech cancelled.' if self.speech.cancelled.is_set() else 'Speech process finished · Audible output needs owner confirmation')
                self.voice_state.setText('Offline speech process finished · Playback unverified · Last safe audio error: '+self.speech.last_error)
            if action != 'microphone':
                self.status.setText(f'Completed · {monotonic()-self.started:.1f}s · Session messages not saved')

        @Slot()
        def task_finished(self):
            self.busy = False
            self.progress.hide()
            for chat in self.chats.values():
                chat['send'].setEnabled(not self.audio_unsafe)
                chat['cancel'].setEnabled(False)
                chat['model'].setEnabled(chat is self.chats['AI Chat'] and not self.audio_unsafe)
                chat['knowledge'].setEnabled(not self.audio_unsafe)
                for control in chat['modes'].buttons(): control.setEnabled(not self.audio_unsafe)
            self.cyber_mode.setEnabled(not self.audio_unsafe)
            for control in self.findChildren(QPushButton):
                if control.property('runtimeAction'):
                    control.setEnabled(not self.audio_unsafe)
            if self.pending[0] == 'chat':
                self.activity.setText(f'Current model: {self.active_model}\nInference: idle\n'
                    f'Last request elapsed: {monotonic()-self.started:.1f}s\nLast error: {self.last_error}\n'
                    'Resource snapshot refreshes on the next polling interval.')
            self.worker.deleteLater()
            self.worker = None
            from zorvyq.voice import VoiceState
            if self.voice_interaction.state != VoiceState.ERROR:
                self.set_voice_state(VoiceState.IDLE)
            utterance, self.queued_speech = self.queued_speech, None
            if utterance and not self.close_requested:
                QTimer.singleShot(0, lambda: self.say(utterance))
            if self.close_requested:
                QTimer.singleShot(0, self.close)

        def refresh(self):
            if self.busy or self.audio_unsafe:
                return
            # Manual refresh remains possible with background polling disabled.
            if self.sender() == self.timer and not self.poll_enabled:
                return
            def snapshot():
                result = {'resources': self.controller.resources.snapshot()}
                try:
                    result['models'] = self.controller.service.models()
                except Exception:
                    result['models'] = None
                try:
                    result['knowledge'] = knowledge_inventory()
                except Exception:
                    result['knowledge'] = None
                try:
                    result['tools'] = self.controller.tool_inventory()
                except Exception:
                    result['tools'] = ()
                result['speech'] = Path('/usr/bin/espeak-ng').is_file()
                result['audio_devices'] = Path('/dev/snd').is_dir()
                return result
            self.run_task('refresh', snapshot)

        def clear_layout(self, layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        def render_status(self, value):
            from zorvyq.features import features
            for feature in features(value):
                self.feature_labels[feature.feature_id].setText(feature.name+'  ·  '+feature.status)
            models = value['models']
            self.top_status.setText('Qwen3:4b  ·  Ollama '+('connected' if models is not None else 'disconnected')+
                '  ·  RAM '+str(value['resources']['system_memory_used_percent'])+'%')
            names = {m['name'] for m in models['installed']} if models else set()
            self.cards['engine'].setText('Qwen3:4b\n'+('Installed' if DEFAULT_MODEL in names else 'Service offline / model not found'))
            specialist = 'dr-ry/foundation-sec-8b-instruct-chat-GGUF:latest'
            self.security_model.setItemText(1, 'Foundation-Sec — '+('experimental, manual questions only' if specialist in names else 'unavailable (model/service not detected)'))
            self.security_model.model().item(1).setEnabled(specialist in names)
            for chat in self.chats.values():
                for index, identity in enumerate((DEFAULT_MODEL, specialist)):
                    chat['model'].model().item(index).setEnabled(identity in names)
                    chat['model'].setItemText(index, ('Qwen3:4b' if index==0 else 'Foundation-Sec-8B-Instruct — experimental')+(' · unavailable' if identity not in names else ''))
            self.cards['specialist'].setText('Foundation-Sec-8B\n'+('Installed — experimental manual selection' if specialist in names else 'Unverified / unavailable — Integration Pending'))
            self.render_models(models)
            knowledge = value['knowledge']
            self.clear_layout(self.knowledge_rows)
            self.knowledge_widgets = []
            if knowledge:
                runtime = knowledge.get('rag_runtime',{})
                dependency = ('Existing RAG environment: ChromaDB 1.5.9 · live retrieval acceptance pending' if runtime.get('available') else 'Compatible RAG runtime unavailable')
                self.cards['knowledge'].setText(f"{knowledge['sources']} approved sources · {knowledge['chunks']} indexed chunks\n"+dependency)
                self.knowledge_state.setText(knowledge['database']+' · '+knowledge['index'])
                for doc in knowledge['documents']:
                    frame = QFrame(); frame.setObjectName('card'); row = QVBoxLayout(frame)
                    row.addWidget(label(doc['title'], 'accent'))
                    row.addWidget(label('Topics: '+', '.join(doc['topics'])+'\nURL: '+doc['url']+
                        '\nRevision: '+str(doc['revision'])+'\nSource: '+doc['source_id']+
                        f"\nIndexed chunks: {doc['indexed']} · Ingested: {doc['ingested_at']}\nAccess: metadata only; retrieval asks separately", 'muted'))
                    self.knowledge_rows.addWidget(frame)
                    self.knowledge_widgets.append(((doc['title']+' '+' '.join(doc['topics'])).casefold(), frame))
                if self.search.text():
                    self.filter_knowledge()
            else:
                self.cards['knowledge'].setText('Metadata unavailable\nNo document content accessed')
                self.knowledge_state.setText('Approved metadata or database unavailable; no retrieval attempted.')
            self.cards['voice'].setText('Experimental / device-dependent\n'+('Speech executable present' if value['speech'] else 'Speech unavailable')+' · Microphone OFF')
            self.voice_state.setText('Speech: '+('executable present; audible output unverified' if value['speech'] else 'unavailable')+
                '\nAudio devices: '+('detected; access unverified' if value['audio_devices'] else 'not detected')+
                '\nVoice input: experimental; configured backend verified on explicit activation only\nMicrophone OFF · Last safe audio error: '+self.speech.last_error)
            self.clear_layout(self.tool_rows)
            tools = value['tools']
            self.cards['tools'].setText(f'{len(tools)} registered tools\nAvailability and permissions vary')
            for spec in tools:
                self.tool_rows.addWidget(label(spec.name+'\n'+spec.description+
                    '\nPermission/risk: '+spec.risk.value+' · Registered; live execution unverified', 'muted'))
            resources = value['resources']
            sync = self.controller.synchronization.backend_name if self.controller.synchronization else 'Not initialized'
            self.activity.setText('Model: '+DEFAULT_MODEL+'\nInference: idle during this snapshot\n'
                'Ollama: '+('connected' if models else 'disconnected')+'\nSynchronization: '+sync+'\n'+
                '\n'.join(k.replace('_',' ')+': '+str(v) for k,v in resources.items())+'\nLast error: '+self.last_error)

        def render_models(self, value):
            self.clear_layout(self.model_rows)
            self.model_choice.clear()
            if value is None:
                self.model_rows.addWidget(label('Ollama disconnected. The workspace remains available; retry when the local service is running.', 'muted'))
                return
            self.cached_models = value
            loaded = {m['name']:m for m in value['loaded']}
            for model in value['installed']:
                name = model['name']
                role = ('General conversation / default' if name == DEFAULT_MODEL else 'Embeddings' if name.startswith('nomic-embed-text') else
                        'Manual experimental specialist chat; specialist RAG blocked' if 'foundation-sec' in name else 'Unassigned; not routed')
                resident = loaded.get(name)
                size = model.get('size')
                detail = 'Installed · '+(f'{size/1024**3:.2f} GiB on disk' if type(size) is int else 'Disk size unavailable')
                if resident:
                    size, vram = resident.get('size'), resident.get('size_vram')
                    detail += ' · Resident '+(f'{size/1024**3:.2f} GiB' if type(size) is int else 'size unavailable')
                    detail += ' · VRAM '+(f'{vram/1024**3:.2f} GiB' if type(vram) is int else 'allocation unavailable')
                    detail += ' · Context '+str(resident.get('context_length', 'unavailable'))
                else:
                    detail += ' · Not resident'
                self.model_rows.addWidget(label(name+'\n'+role+'\n'+detail, 'muted'))
            for name in dict.fromkeys([m['name'] for m in value['installed']] + list(loaded)):
                self.model_choice.addItem(name)
            if not loaded:
                self.model_rows.addWidget(label('No resident models. Models load only for explicit requests.', 'muted'))

        def apply_theme(self, light):
            self.light_mode = light
            base_size = 18 if self.large_text else 14
            bg, surface, text, muted, border = ('#f1f5fa','#ffffff','#152239','#506178','#c3d2e3') if light else (
                '#0b1019','#141e2e','#e5edf8','#9aadc5','#28384d')
            self.setStyleSheet(f'''
                QWidget {{ background: {bg}; color: {text}; font-family: "Sans Serif"; font-size: {base_size}px; }}
                QScrollArea, QStackedWidget {{ border: none; }}
                QLabel {{ background: transparent; }}
                QLabel#brand {{ font-size: 22px; font-weight: 700; letter-spacing: 3px; }}
                QLabel#logo {{ background: #16c5e5; color: #081322; border-radius: 12px; font-size: 30px; font-weight: 800; qproperty-alignment: AlignCenter; }}
                QLabel#heading {{ font-size: 27px; font-weight: 700; }}
                QLabel#heroTitle {{ font-size: 25px; font-weight: 600; }}
                QLabel#muted {{ color: {muted}; }}
                QLabel#accent {{ color: {'#006d86' if light else '#53d6ed'}; font-weight: 600; }}
                QLabel#cardValue {{ font-size: 17px; font-weight: 600; }}
                QFrame#card, QFrame#userBubble {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; padding: 12px; }}
                QFrame#userBubble {{ border-left: 3px solid #16a7d1; }}
                QFrame#hero {{ background: {'#d8edf6' if light else '#112b40'}; border: 1px solid #215573; border-radius: 15px; padding: 20px; }}
                QListWidget#sidebar {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; padding: 5px; }}
                QListWidget::item {{ padding: 13px 9px; border-radius: 7px; margin-bottom: 3px; }}
                QListWidget::item:selected {{ background: {'#c7e9f4' if light else '#1b3b54'}; color: {'#005a72' if light else '#70e2f4'}; }}
                QPushButton {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 10px 14px; }}
                QPushButton:hover {{ border-color: #16a7d1; }}
                QPushButton:disabled {{ color: {muted}; }}
                QPushButton:focus, QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QCheckBox:focus, QListWidget:focus {{ border: 2px solid #00aacc; }}
                QTextEdit, QPlainTextEdit, QLineEdit, QComboBox {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 8px; selection-background-color: #236682; }}
                QTextBrowser {{ background: transparent; border: none; }}
                QProgressBar {{ border: 1px solid {border}; border-radius: 5px; max-height: 9px; }}
                QProgressBar::chunk {{ background: #16c5e5; }}
                QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; }}
            ''')

        def shutdown(self):
            self.monitoring.stop()
            self.operations.close()
            self.controller.close()

        def closeEvent(self, event):
            if self.shutdown_complete:
                event.accept()
                return
            self.awareness_panel.stop()
            self.monitoring.stop()
            self.close_requested = True
            self.bridge.closing = True  # Deny any unfinished one-time permission dialog.
            self.timer.stop()
            self.elapsed_timer.stop()
            self.reminder_timer.stop()
            self.voice_interaction.cancelled.set()
            self.speech.stop()
            self.queued_speech = None
            self.operations.cancel()
            self.controller.cancel_knowledge()
            self.nmap.cancelled.set()
            self.status.setText('Closing: waiting for bounded work, then unloading unchanged app-owned models…')
            if not self.busy:
                self.run_task('shutdown', self.shutdown)
            event.ignore()

    return Window()

if __name__ == '__main__':
    raise SystemExit(main())
