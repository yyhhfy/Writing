import html
import ctypes
import ctypes.wintypes
import json
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QKeySequenceEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QCheckBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from database import Database
from ghost_save import GhostSaveManager
from text_editor import RichTextEditor


def resource_dir():
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def runtime_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class GlobalHotkeyListener(QObject):
    activated = pyqtSignal()

    MODIFIERS = {
        "CTRL": 0x0002,
        "CONTROL": 0x0002,
        "SHIFT": 0x0004,
        "ALT": 0x0001,
        "WIN": 0x0008,
        "META": 0x0008,
    }

    SPECIAL_KEYS = {
        "UP": 0x26,
        "DOWN": 0x28,
        "LEFT": 0x25,
        "RIGHT": 0x27,
        "ESC": 0x1B,
        "ESCAPE": 0x1B,
        "SPACE": 0x20,
        "TAB": 0x09,
        "ENTER": 0x0D,
        "RETURN": 0x0D,
    }

    def __init__(self, sequence, parent=None):
        super().__init__(parent)
        self.sequence = sequence
        self.hotkey_id = 42001
        self.thread_id = None
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        self.stop()
        parsed = self._parse_sequence(self.sequence)
        if not parsed:
            return
        modifiers, key_code = parsed
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._message_loop,
            args=(modifiers, key_code),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread_id = None

    def _parse_sequence(self, sequence):
        parts = [part.strip().upper() for part in sequence.split("+") if part.strip()]
        if not parts:
            return None
        modifiers = 0
        key = None
        for part in parts:
            if part in self.MODIFIERS:
                modifiers |= self.MODIFIERS[part]
            else:
                key = part
        if not key:
            return None
        if len(key) == 1:
            return modifiers, ord(key)
        if key.startswith("F") and key[1:].isdigit():
            number = int(key[1:])
            if 1 <= number <= 24:
                return modifiers, 0x70 + number - 1
        key_code = self.SPECIAL_KEYS.get(key)
        if key_code:
            return modifiers, key_code
        return None

    def _message_loop(self, modifiers, key_code):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, self.hotkey_id, modifiers, key_code):
            return
        try:
            msg = ctypes.wintypes.MSG()
            while not self._stop_event.is_set() and user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0
            ) != 0:
                if msg.message == 0x0312 and msg.wParam == self.hotkey_id:
                    self.activated.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self.hotkey_id)


DEFAULT_SHORTCUTS = {
    "close": "Ctrl+Shift+Q",
    "toggle_visibility": "Ctrl+Shift+H",
    "save": "Ctrl+S",
    "export": "Ctrl+E",
    "switch_mode": "Ctrl+Shift+M",
    "opacity_up": "Ctrl+Up",
    "opacity_down": "Ctrl+Down",
    "font_up": "Ctrl+]",
    "font_down": "Ctrl+[",
    "theme": "Ctrl+T",
    "toggle_status_bar": "Ctrl+Shift+B",
}

SHORTCUT_LABELS = {
    "close": "关闭窗口",
    "toggle_visibility": "隐藏 / 显示",
    "save": "保存（幽灵保存）",
    "export": "导出",
    "switch_mode": "模式切换",
    "opacity_up": "透明度增加",
    "opacity_down": "透明度降低",
    "font_up": "文字大小增加",
    "font_down": "文字大小降低",
    "theme": "主题切换",
    "toggle_status_bar": "状态栏隐藏",
}

DEFAULT_SETTINGS = {
    "opacity": 0.9,
    "font_size": 16,
    "theme": "dark",
    "window_width": 550,
    "window_height": 550,
    "status_bar_hidden": False,
    "background_resident": True,
    "shortcuts": DEFAULT_SHORTCUTS,
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resource_dir = resource_dir()
        self.runtime_dir = runtime_dir()
        self.settings_path = self.runtime_dir / "settings.json"
        self.db_path = self.runtime_dir / "writing_data.db"
        self._ensure_runtime_files()

        self.db = Database(str(self.db_path))
        self.root_node_id = self._ensure_root_node()
        self.settings = self._load_settings()
        self.shortcuts = []
        self.shortcut_edits = {}
        self.visibility_hotkey = None
        self._mouse_inside_creation = False
        self._resize_start_geometry = None
        self._resize_start_global = None
        self._resize_edges = set()
        self._force_quit = False
        self._syncing_content = False

        self.setWindowTitle("Writing")
        self.setWindowIcon(self._make_pen_icon())
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(260, 180)
        self.resize(
            max(360, int(self.settings["window_width"])),
            max(260, int(self.settings["window_height"])),
        )

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home_page = self._build_home_page()
        self.settings_page = self._build_settings_page()
        self.creation_page = self._build_creation_page()
        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.creation_page)

        self._setup_tray()
        self._load_content()
        self._apply_settings_to_window()
        self._apply_creation_chrome_state()
        self._bind_shortcuts()
        self._bind_global_visibility_hotkey()

        self.creation_save = GhostSaveManager(self.creation_editor, self._save_content)
        self.creation_save.save_requested.connect(self._save_content)
        self.settings_save = GhostSaveManager(self.content_editor, self._save_content)
        self.settings_save.save_requested.connect(self._save_content)

        self.word_timer = QTimer(self)
        self.word_timer.timeout.connect(self._update_word_count)
        self.word_timer.start(500)

        self.creation_idle_timer = QTimer(self)
        self.creation_idle_timer.setSingleShot(True)
        self.creation_idle_timer.timeout.connect(self._dim_creation_window)

    def _ensure_runtime_files(self):
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        default_settings = self.resource_dir / "settings.json"
        default_db = self.resource_dir / "writing_data.db"
        if not self.settings_path.exists() and default_settings.exists():
            shutil.copyfile(default_settings, self.settings_path)
        if not self.db_path.exists() and default_db.exists():
            shutil.copyfile(default_db, self.db_path)

    def _ensure_root_node(self):
        root = self.db.get_root_node()
        if root:
            return root[0]
        return None

    def _load_settings(self):
        data = {}
        if self.settings_path.exists():
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        merged = DEFAULT_SETTINGS.copy()
        merged.update({k: v for k, v in data.items() if k != "shortcuts"})
        shortcuts = DEFAULT_SHORTCUTS.copy()
        shortcuts.update(data.get("shortcuts", {}))
        merged["shortcuts"] = shortcuts
        return merged

    def _save_settings(self):
        self.settings["window_width"] = self.width()
        self.settings["window_height"] = self.height()
        self.settings_path.write_text(
            json.dumps(self.settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _make_pen_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#f5f7fb"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(22, 44, 44, 22)
        painter.drawLine(39, 17, 48, 26)
        painter.drawLine(18, 48, 24, 44)
        painter.drawPoint(50, 49)
        painter.end()
        return QIcon(pixmap)

    def _build_home_page(self):
        page = QWidget()
        page.setObjectName("homePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 42, 48, 42)
        layout.addStretch()

        icon = QLabel("✎")
        icon.setObjectName("heroIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("Writing")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        actions = QHBoxLayout()
        actions.setSpacing(16)
        settings_btn = QPushButton("⚙  设置模式")
        settings_btn.setObjectName("modeButton")
        settings_btn.clicked.connect(self.show_settings_mode)
        create_btn = QPushButton("✎  创作模式")
        create_btn.setObjectName("modeButton")
        create_btn.clicked.connect(self.show_creation_mode)
        actions.addStretch()
        actions.addWidget(settings_btn)
        actions.addWidget(create_btn)
        actions.addStretch()
        layout.addSpacing(24)
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def _build_settings_page(self):
        page = QWidget()
        page.setObjectName("settingsPage")
        root = QHBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("settingsSidebar")
        sidebar.setFixedWidth(150)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 46, 10, 16)
        side_layout.setSpacing(8)
        self.general_tab_btn = self._side_button("通用设置")
        self.shortcuts_tab_btn = self._side_button("快捷键设置")
        self.about_tab_btn = self._side_button("关于")
        side_layout.addWidget(self.general_tab_btn)
        side_layout.addWidget(self.shortcuts_tab_btn)
        side_layout.addWidget(self.about_tab_btn)
        side_layout.addStretch()
        root.addWidget(sidebar)

        self.settings_stack = QStackedWidget()
        self.settings_stack.setMinimumWidth(420)
        self.settings_stack.addWidget(self._build_general_settings())
        self.settings_stack.addWidget(self._build_shortcut_settings())
        self.settings_stack.addWidget(self._build_about_page())

        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.settings_stack)
        root.addWidget(scroll, 1)

        self.general_tab_btn.clicked.connect(lambda: self._show_settings_tab(0))
        self.shortcuts_tab_btn.clicked.connect(lambda: self._show_settings_tab(1))
        self.about_tab_btn.clicked.connect(lambda: self._show_settings_tab(2))
        self._show_settings_tab(0)
        return page

    def _side_button(self, text):
        button = QPushButton(text)
        button.setObjectName("sideButton")
        button.setCheckable(True)
        return button

    def _show_settings_tab(self, index):
        self.settings_stack.setCurrentIndex(index)
        for i, button in enumerate(
            [self.general_tab_btn, self.shortcuts_tab_btn, self.about_tab_btn]
        ):
            button.setChecked(i == index)

    def _build_general_settings(self):
        page = QWidget()
        page.setMinimumWidth(420)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 12)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("通用设置"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(50, 100)
        self.opacity_slider.setValue(round(self.settings["opacity"] * 100))
        self.opacity_slider.setMinimumWidth(120)
        self.opacity_value = QLabel(f"{self.opacity_slider.value()}%")
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        grid.addWidget(QLabel("透明度"), 0, 0)
        grid.addWidget(self.opacity_slider, 0, 1, 1, 3)
        grid.addWidget(self.opacity_value, 0, 4)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(10, 42)
        self.font_size_spin.setFixedWidth(88)
        self.font_size_spin.setValue(self.settings["font_size"])
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        grid.addWidget(QLabel("文字大小"), 1, 0)
        grid.addWidget(self.font_size_spin, 1, 1)
        grid.addWidget(QLabel("px"), 1, 2)

        self.theme_combo = QComboBox()
        self.theme_combo.setFixedWidth(130)
        self.theme_combo.addItem("黑夜模式", "dark")
        self.theme_combo.addItem("白天模式", "light")
        self.theme_combo.setCurrentIndex(0 if self.settings["theme"] == "dark" else 1)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        grid.addWidget(QLabel("主题"), 2, 0)
        grid.addWidget(self.theme_combo, 2, 1, 1, 2)

        self.background_resident_check = QCheckBox("后台常驻")
        self.background_resident_check.setChecked(
            bool(self.settings.get("background_resident", True))
        )
        self.background_resident_check.toggled.connect(
            self._on_background_resident_changed
        )
        grid.addWidget(QLabel("运行方式"), 3, 0)
        grid.addWidget(self.background_resident_check, 3, 1, 1, 3)

        layout.addLayout(grid)
        layout.addWidget(self._divider())
        layout.addWidget(self._section_title("窗口大小"))

        size_grid = QGridLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(120, 2400)
        self.width_spin.setFixedWidth(92)
        self.width_spin.setValue(self.settings["window_width"])
        self.width_spin.valueChanged.connect(self._on_window_size_changed)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(80, 1600)
        self.height_spin.setFixedWidth(92)
        self.height_spin.setValue(self.settings["window_height"])
        self.height_spin.valueChanged.connect(self._on_window_size_changed)
        size_grid.addWidget(QLabel("宽度"), 0, 0)
        size_grid.addWidget(self.width_spin, 0, 1)
        size_grid.addWidget(QLabel("px"), 0, 2)
        size_grid.addWidget(QLabel("高度"), 0, 3)
        size_grid.addWidget(self.height_spin, 0, 4)
        size_grid.addWidget(QLabel("px"), 0, 5)
        layout.addLayout(size_grid)

        layout.addWidget(self._divider())
        layout.addWidget(self._section_title("内容编辑"))
        self.content_editor = RichTextEditor()
        self.content_editor.setObjectName("settingsContentEditor")
        self.content_editor.setPlaceholderText("在这里输入或粘贴你的内容...")
        self.content_editor.textChanged.connect(self._sync_from_settings_editor)
        layout.addWidget(self.content_editor, 1)

        actions = QHBoxLayout()
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_settings)
        cancel_btn = QPushButton("返回首页")
        cancel_btn.clicked.connect(self.show_home)
        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_settings_clicked)
        actions.addWidget(reset_btn)
        actions.addStretch()
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        layout.addLayout(actions)
        return page

    def _build_shortcut_settings(self):
        page = QWidget()
        page.setMinimumWidth(420)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 12)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("快捷设置"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        for row, (key, label) in enumerate(SHORTCUT_LABELS.items()):
            edit = QKeySequenceEdit(QKeySequence(self.settings["shortcuts"][key]))
            edit.setObjectName("shortcutEdit")
            self.shortcut_edits[key] = edit
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(edit, row, 1)
        layout.addLayout(grid)
        layout.addStretch()

        actions = QHBoxLayout()
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(self._reset_shortcuts)
        cancel_btn = QPushButton("返回首页")
        cancel_btn.clicked.connect(self.show_home)
        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save_shortcuts)
        actions.addWidget(reset_btn)
        actions.addStretch()
        actions.addWidget(cancel_btn)
        actions.addWidget(save_btn)
        layout.addLayout(actions)
        return page

    def _build_about_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 28, 24, 24)
        layout.addWidget(self._section_title("关于"))
        about = QLabel(
            "Writing 是一个轻量写作窗口。关闭后会隐藏到系统托盘，"
            "内容会在停止输入 1.5 秒后自动保存。"
        )
        about.setWordWrap(True)
        about.setObjectName("mutedLabel")
        layout.addWidget(about)
        layout.addStretch()
        return page

    def _section_title(self, text):
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _divider(self):
        line = QFrame()
        line.setObjectName("divider")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def _build_creation_page(self):
        page = QWidget()
        page.setObjectName("creationPage")
        page.setMouseTracking(True)
        page.installEventFilter(self)
        layout = QVBoxLayout(page)
        self.creation_layout = layout
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.creation_editor = RichTextEditor()
        self.creation_editor.setObjectName("creationEditor")
        self.creation_editor.setPlaceholderText("开始输入你的内容...")
        self.creation_editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.creation_editor.customContextMenuRequested.connect(
            self._show_creation_context_menu
        )
        self.creation_editor.textChanged.connect(self._sync_from_creation_editor)
        layout.addWidget(self.creation_editor, 1)

        footer = QFrame()
        footer.setObjectName("creationFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 0, 8, 0)
        self.save_status_label = QLabel("已自动保存")
        self.save_status_label.setObjectName("saveStatusLabel")
        self.word_count_label = QLabel("字数：0")
        self.word_count_label.setObjectName("wordCountLabel")
        footer_layout.addWidget(self.save_status_label)
        footer_layout.addStretch()
        footer_layout.addWidget(self.word_count_label)
        layout.addWidget(footer)
        self.creation_footer = footer
        return page

    def _show_creation_context_menu(self, position):
        menu = self.creation_editor.createStandardContextMenu(position)
        menu.addSeparator()
        title_action = QAction("设为标题", self)
        title_action.setEnabled(self.creation_editor.textCursor().hasSelection())
        title_action.triggered.connect(self._format_selection_as_title)
        body_action = QAction("设为正文", self)
        body_action.setEnabled(self.creation_editor.textCursor().hasSelection())
        body_action.triggered.connect(self._format_selection_as_body)
        toggle_action = QAction("隐藏状态栏" if not self.settings.get("status_bar_hidden") else "显示状态栏", self)
        menu.addAction(title_action)
        menu.addAction(body_action)
        menu.addSeparator()
        toggle_action.triggered.connect(self.toggle_status_bar)
        menu.addAction(toggle_action)
        menu.exec(self.creation_editor.viewport().mapToGlobal(position))

    def _format_selection_as_title(self):
        self._format_selection(font_size_delta=8, bold=True)

    def _format_selection_as_body(self):
        self._format_selection(font_size_delta=0, bold=False)

    def _format_selection(self, font_size_delta, bold):
        cursor = self.creation_editor.textCursor()
        if not cursor.hasSelection():
            return
        char_format = QTextCharFormat()
        char_format.setFontPointSize(max(10, int(self.settings["font_size"]) + font_size_delta))
        char_format.setFontWeight(700 if bold else 400)
        cursor.mergeCharFormat(char_format)
        self.creation_editor.setTextCursor(cursor)
        self._save_content()

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Writing")
        menu = QMenu()
        show_action = QAction("显示窗口", self)
        show_action.triggered.connect(self.show_creation_mode)
        settings_action = QAction("设置模式", self)
        settings_action.triggered.connect(self.show_settings_mode)
        save_action = QAction("保存", self)
        save_action.triggered.connect(self._save_content)
        export_action = QAction("导出", self)
        export_action.triggered.connect(self._export_dialog)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(show_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(save_action)
        menu.addAction(export_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_creation_mode()

    def _load_content(self):
        node = self.db.get_node(self.root_node_id) if self.root_node_id else None
        content = node[3] if node and node[3] else "<p></p>"
        self._syncing_content = True
        self.creation_editor.setHtml(content)
        self.content_editor.setHtml(content)
        self._syncing_content = False

    def _current_editor(self):
        focus = QApplication.focusWidget()
        if focus in (self.content_editor, self.creation_editor):
            return focus
        return self.creation_editor if self.stack.currentWidget() == self.creation_page else self.content_editor

    def _save_content(self):
        if not self.root_node_id or self._syncing_content:
            return
        editor = self._current_editor()
        content = editor.toHtml()
        self.db.save_node_content(self.root_node_id, content)
        self.save_status_label.setText(f"已自动保存  {time.strftime('%H:%M:%S')}")
        self._sync_editor_content(editor, content)

    def _sync_editor_content(self, source, html_content):
        target = self.content_editor if source == self.creation_editor else self.creation_editor
        self._syncing_content = True
        source_scroll = source.verticalScrollBar().value()
        target.setHtml(html_content)
        source.verticalScrollBar().setValue(source_scroll)
        self._syncing_content = False

    def _sync_from_creation_editor(self):
        if not self._syncing_content:
            self._update_word_count()

    def _sync_from_settings_editor(self):
        if not self._syncing_content:
            self._update_word_count()

    def _apply_settings_to_window(self):
        self.setWindowOpacity(float(self.settings["opacity"]))
        self._apply_theme(self.settings["theme"])
        font_size = int(self.settings["font_size"])
        self.creation_editor.set_font_size(font_size)
        self.content_editor.set_font_size(font_size)

    def _apply_creation_chrome_state(self):
        hidden = bool(self.settings.get("status_bar_hidden", False))
        in_creation = self.stack.currentWidget() == self.creation_page
        self.creation_footer.setVisible(True)
        self.save_status_label.setVisible(not (hidden and in_creation))
        if hasattr(self, "creation_layout"):
            margin = 4 if hidden and in_creation else 0
            self.creation_layout.setContentsMargins(margin, margin, margin, margin if hidden and in_creation else 0)
        self.creation_footer.setFixedHeight(16 if hidden and in_creation else 30)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        target_frameless = hidden and in_creation
        current_frameless = bool(
            self.windowFlags() & Qt.WindowType.FramelessWindowHint
        )
        if current_frameless != target_frameless:
            geometry = self.geometry()
            was_visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, target_frameless)
            self.setGeometry(geometry)
            if was_visible:
                self.show()

    def toggle_status_bar(self):
        self.settings["status_bar_hidden"] = not bool(
            self.settings.get("status_bar_hidden", False)
        )
        self._apply_creation_chrome_state()
        self._save_settings()

    def _hidden_creation_active(self):
        return (
            hasattr(self, "creation_page")
            and hasattr(self, "stack")
            and hasattr(self, "creation_editor")
            and hasattr(self, "settings")
            and self.stack.currentWidget() == self.creation_page
            and bool(self.settings.get("status_bar_hidden", False))
        )

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "creation_page")
            and watched == self.creation_page
            and self._hidden_creation_active()
        ):
            if event.type() == QEvent.Type.MouseButtonPress:
                return self._handle_hidden_mouse_press(event)
            if event.type() == QEvent.Type.MouseMove:
                return self._handle_hidden_mouse_move(event)
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._resize_start_geometry = None
                self._resize_start_global = None
                self._resize_edges = set()
                self.creation_page.unsetCursor()
                return False
        return super().eventFilter(watched, event)

    def _handle_hidden_mouse_press(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        edges = self._resize_edges_for_pos(event.position().toPoint())
        if edges:
            self._resize_edges = edges
            self._resize_start_geometry = self.geometry()
            self._resize_start_global = event.globalPosition().toPoint()
            return True

        window = self.windowHandle()
        if window:
            window.startSystemMove()
        return True

    def _handle_hidden_mouse_move(self, event):
        if self._resize_start_geometry is not None:
            self._resize_hidden_window(event.globalPosition().toPoint())
            return True
        edges = self._resize_edges_for_pos(event.position().toPoint())
        if edges:
            self._set_resize_cursor(edges)
        else:
            self.creation_page.setCursor(Qt.CursorShape.SizeAllCursor)
        return False

    def _resize_edges_for_pos(self, pos):
        margin = 4
        rect = self.creation_page.rect()
        edges = set()
        if pos.x() <= margin:
            edges.add("left")
        elif pos.x() >= rect.width() - margin:
            edges.add("right")
        if pos.y() <= margin:
            edges.add("top")
        elif pos.y() >= rect.height() - margin:
            edges.add("bottom")
        return edges

    def _set_resize_cursor(self, edges):
        if {"left", "top"}.issubset(edges) or {"right", "bottom"}.issubset(edges):
            self.creation_page.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif {"right", "top"}.issubset(edges) or {"left", "bottom"}.issubset(edges):
            self.creation_page.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif "left" in edges or "right" in edges:
            self.creation_page.setCursor(Qt.CursorShape.SizeHorCursor)
        elif "top" in edges or "bottom" in edges:
            self.creation_page.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.creation_page.unsetCursor()

    def _resize_hidden_window(self, global_pos):
        geometry = self._resize_start_geometry
        delta = global_pos - self._resize_start_global
        min_width = self.minimumWidth()
        min_height = self.minimumHeight()
        new_geometry = geometry.adjusted(0, 0, 0, 0)

        if "left" in self._resize_edges:
            new_left = min(geometry.right() - min_width, geometry.left() + delta.x())
            new_geometry.setLeft(new_left)
        if "right" in self._resize_edges:
            new_geometry.setWidth(max(min_width, geometry.width() + delta.x()))
        if "top" in self._resize_edges:
            new_top = min(geometry.bottom() - min_height, geometry.top() + delta.y())
            new_geometry.setTop(new_top)
        if "bottom" in self._resize_edges:
            new_geometry.setHeight(max(min_height, geometry.height() + delta.y()))

        self.setGeometry(new_geometry)

    def _apply_theme(self, theme):
        qss_path = self.resource_dir / f"{theme}_theme.qss"
        if qss_path.exists():
            self.setStyleSheet(qss_path.read_text(encoding="utf-8"))
        else:
            self.setStyleSheet("")

    def _creation_mode_active(self):
        return self.stack.currentWidget() == self.creation_page

    def _restore_creation_window_opacity(self):
        self.creation_idle_timer.stop()
        self.setWindowOpacity(float(self.settings["opacity"]))

    def _dim_creation_window(self):
        if not self._creation_mode_active() or self._mouse_inside_creation:
            return
        base_opacity = float(self.settings["opacity"])
        self.setWindowOpacity(max(0.2, base_opacity * 0.55))

    def _bind_shortcuts(self):
        for shortcut in self.shortcuts:
            shortcut.setParent(None)
        self.shortcuts = []

        mapping = {
            "close": self.hide_to_tray,
            "save": self._save_content,
            "export": self._export_dialog,
            "switch_mode": self.toggle_mode,
            "opacity_up": lambda: self._change_opacity(0.05),
            "opacity_down": lambda: self._change_opacity(-0.05),
            "font_up": lambda: self._change_font_size(1),
            "font_down": lambda: self._change_font_size(-1),
            "theme": self.toggle_theme,
            "toggle_status_bar": self.toggle_status_bar,
        }
        for key, callback in mapping.items():
            seq = self.settings["shortcuts"].get(key, DEFAULT_SHORTCUTS[key])
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)

    def _bind_global_visibility_hotkey(self):
        if self.visibility_hotkey:
            self.visibility_hotkey.stop()
        sequence = self.settings["shortcuts"].get(
            "toggle_visibility", DEFAULT_SHORTCUTS["toggle_visibility"]
        )
        self.visibility_hotkey = GlobalHotkeyListener(sequence, self)
        self.visibility_hotkey.activated.connect(self.toggle_visibility)
        self.visibility_hotkey.start()

    def _on_opacity_changed(self, value):
        self.settings["opacity"] = value / 100
        self.opacity_value.setText(f"{value}%")
        self._restore_creation_window_opacity()

    def _on_font_size_changed(self, value):
        self.settings["font_size"] = value
        self.creation_editor.set_font_size(value)
        self.content_editor.set_font_size(value)

    def _on_theme_changed(self):
        self.settings["theme"] = self.theme_combo.currentData()
        self._apply_theme(self.settings["theme"])

    def _on_background_resident_changed(self, checked):
        self.settings["background_resident"] = checked

    def _on_window_size_changed(self):
        self.resize(self.width_spin.value(), self.height_spin.value())

    def _save_settings_clicked(self):
        self._save_content()
        self._save_settings()
        QMessageBox.information(self, "保存设置", "设置已保存。")

    def _reset_settings(self):
        self.settings.update(
            {
                "opacity": DEFAULT_SETTINGS["opacity"],
                "font_size": DEFAULT_SETTINGS["font_size"],
                "theme": DEFAULT_SETTINGS["theme"],
                "window_width": DEFAULT_SETTINGS["window_width"],
                "window_height": DEFAULT_SETTINGS["window_height"],
                "status_bar_hidden": DEFAULT_SETTINGS["status_bar_hidden"],
                "background_resident": DEFAULT_SETTINGS["background_resident"],
            }
        )
        self.opacity_slider.setValue(round(self.settings["opacity"] * 100))
        self.font_size_spin.setValue(self.settings["font_size"])
        self.theme_combo.setCurrentIndex(0)
        self.background_resident_check.setChecked(self.settings["background_resident"])
        self.width_spin.setValue(self.settings["window_width"])
        self.height_spin.setValue(self.settings["window_height"])
        self._apply_settings_to_window()
        self.resize(self.settings["window_width"], self.settings["window_height"])

    def _reset_shortcuts(self):
        for key, edit in self.shortcut_edits.items():
            edit.setKeySequence(QKeySequence(DEFAULT_SHORTCUTS[key]))

    def _save_shortcuts(self):
        for key, edit in self.shortcut_edits.items():
            seq = edit.keySequence().toString(QKeySequence.SequenceFormat.NativeText)
            self.settings["shortcuts"][key] = seq or DEFAULT_SHORTCUTS[key]
        self._bind_shortcuts()
        self._bind_global_visibility_hotkey()
        self._save_settings()
        QMessageBox.information(self, "保存设置", "快捷键已保存。")

    def _change_opacity(self, delta):
        value = max(0.5, min(1.0, self.settings["opacity"] + delta))
        self.settings["opacity"] = value
        self._restore_creation_window_opacity()
        self.opacity_slider.setValue(round(value * 100))
        self._save_settings()

    def _change_font_size(self, delta):
        value = max(10, min(42, self.settings["font_size"] + delta))
        self.settings["font_size"] = value
        self.font_size_spin.setValue(value)
        self._save_settings()

    def toggle_theme(self):
        self.settings["theme"] = "light" if self.settings["theme"] == "dark" else "dark"
        self.theme_combo.setCurrentIndex(0 if self.settings["theme"] == "dark" else 1)
        self._apply_theme(self.settings["theme"])
        self._save_settings()

    def show_home(self):
        self.stack.setCurrentWidget(self.home_page)
        self.setMinimumSize(260, 180)
        self._apply_creation_chrome_state()
        self.creation_idle_timer.stop()
        self.setWindowOpacity(float(self.settings["opacity"]))
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_settings_mode(self):
        self.stack.setCurrentWidget(self.settings_page)
        self.setMinimumSize(260, 180)
        self._apply_creation_chrome_state()
        self.creation_idle_timer.stop()
        self.setWindowOpacity(float(self.settings["opacity"]))
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_creation_mode(self):
        self.stack.setCurrentWidget(self.creation_page)
        self.setMinimumSize(80, 50)
        self._apply_creation_chrome_state()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._restore_creation_window_opacity()
        self.creation_editor.setFocus()

    def toggle_mode(self):
        if self.stack.currentWidget() == self.creation_page:
            self.show_settings_mode()
        else:
            self.show_creation_mode()

    def hide_to_tray(self):
        self._save_content()
        if not self.settings.get("background_resident", True):
            self.quit_app()
            return
        self.hide()
        if self.tray.isVisible():
            self.tray.showMessage(
                "Writing",
                "已隐藏到系统托盘。",
                QSystemTrayIcon.MessageIcon.Information,
                1500,
            )

    def toggle_visibility(self):
        if self.isVisible():
            self.hide_to_tray()
        else:
            self.show_creation_mode()

    def quit_app(self):
        self._force_quit = True
        self._save_content()
        self._save_settings()
        if self.visibility_hotkey:
            self.visibility_hotkey.stop()
        QApplication.quit()

    def _update_word_count(self):
        text = self._current_editor().toPlainText()
        count = len([ch for ch in text if ch.strip()])
        self.word_count_label.setText(f"字数：{count}")

    def _export_dialog(self):
        self._save_content()
        file_path, selected = QFileDialog.getSaveFileName(
            self,
            "导出",
            "",
            "TXT 文件 (*.txt);;Markdown 文件 (*.md);;Word 文件 (*.docx)",
        )
        if not file_path:
            return
        suffix = Path(file_path).suffix.lower()
        if not suffix:
            if "Markdown" in selected:
                file_path += ".md"
                suffix = ".md"
            elif "Word" in selected:
                file_path += ".docx"
                suffix = ".docx"
            else:
                file_path += ".txt"
                suffix = ".txt"

        text = self.creation_editor.toPlainText()
        title = "Writing"
        if suffix == ".txt":
            Path(file_path).write_text(text, encoding="utf-8")
        elif suffix == ".md":
            Path(file_path).write_text(f"# {title}\n\n{text}", encoding="utf-8")
        elif suffix == ".docx":
            self._write_docx(file_path, title, text)
        else:
            QMessageBox.warning(self, "导出", "不支持的导出格式。")
            return
        QMessageBox.information(self, "导出成功", f"已导出到：{file_path}")

    def _write_docx(self, file_path, title, text):
        paragraphs = [title, *text.splitlines()]

        def paragraph_xml(value):
            escaped = html.escape(value)
            return f"<w:p><w:r><w:t xml:space=\"preserve\">{escaped}</w:t></w:r></w:p>"

        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{''.join(paragraph_xml(p) for p in paragraphs)}"
            '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" '
            'w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        )
        with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as docx:
            docx.writestr("[Content_Types].xml", content_types)
            docx.writestr("_rels/.rels", rels)
            docx.writestr("word/document.xml", document)

    def closeEvent(self, event):
        if self._force_quit:
            event.accept()
            return
        if self.settings.get("background_resident", True):
            self.hide_to_tray()
            event.ignore()
        else:
            self.quit_app()
            event.accept()

    def show_existing_instance(self):
        self.show_creation_mode()

    def enterEvent(self, event):
        if self._creation_mode_active():
            self._mouse_inside_creation = True
            self._restore_creation_window_opacity()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._creation_mode_active():
            self._mouse_inside_creation = False
            self.creation_idle_timer.start(5000)
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
