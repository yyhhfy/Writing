import json
import os
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt


class ThemeManager:
    """主题和透明度管理器"""

    def __init__(self, window: QWidget, config_path="settings.json"):
        self.window = window
        self.config_path = config_path
        self.current_theme = "light"
        self.load_settings()

    def load_settings(self):
        """加载保存的设置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    opacity = data.get("opacity", 1.0)
                    theme = data.get("theme", "light")
            except:
                opacity, theme = 1.0, "light"
        else:
            opacity, theme = 1.0, "light"

        self.window.setWindowOpacity(opacity)
        self.apply_theme(theme)

    def save_settings(self):
        """保存当前设置"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({
                "opacity": self.window.windowOpacity(),
                "theme": self.current_theme
            }, f, ensure_ascii=False, indent=2)

    def set_opacity(self, value):
        """设置透明度 (0.5 ~ 1.0)"""
        # 限制范围
        value = max(0.5, min(1.0, value))
        self.window.setWindowOpacity(value)
        self.save_settings()

    def apply_theme(self, theme):
        """应用主题"""
        self.current_theme = theme
        theme_file = f"{theme}_theme.qss"

        if os.path.exists(theme_file):
            with open(theme_file, "r", encoding="utf-8") as f:
                self.window.setStyleSheet(f.read())
        else:
            self.window.setStyleSheet("")

        self.save_settings()

    def toggle_theme(self):
        """切换亮/暗主题"""
        new_theme = "dark" if self.current_theme == "light" else "light"
        self.apply_theme(new_theme)

    def get_current_theme(self):
        return self.current_theme