from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtGui import QFont, QTextCursor, QTextCharFormat, QFontMetrics
from PyQt6.QtCore import Qt


class RichTextEditor(QTextEdit):
    """自定义富文本编辑器，支持快捷操作"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(True)
        self.setFont(QFont("微软雅黑", 12))

        # 设置内边距，让文字不贴边
        self.document().setDocumentMargin(10)

    def set_font_size(self, size):
        """设置当前选中文本或光标所在位置的字体大小"""
        cursor = self.textCursor()
        if cursor.hasSelection():
            # 如果有选中文本，只改选中的
            char_format = QTextCharFormat()
            char_format.setFontPointSize(size)
            cursor.mergeCharFormat(char_format)
        else:
            # 没有选中，改默认字体大小
            font = self.font()
            font.setPointSize(size)
            self.setFont(font)

    def set_font_family(self, family):
        """设置字体族"""
        font = self.font()
        font.setFamily(family)
        self.setFont(font)

    def get_word_count(self):
        """获取字数统计（去除HTML标签）"""
        text = self.toPlainText()
        # 去除空白字符后统计
        words = [w for w in text if w.strip() and not w.isspace()]
        return len(words)