from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QMenu
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction


class OutlineTree(QTreeWidget):
    """大纲树组件，支持右键菜单、拖拽排序"""

    node_selected = pyqtSignal(str)  # 选中节点时发送节点ID
    node_created = pyqtSignal(str, str)  # 创建节点（父节点ID，新节点ID）
    node_deleted = pyqtSignal(str)  # 删除节点
    node_renamed = pyqtSignal(str, str)  # 重命名节点（节点ID，新标题）
    node_moved = pyqtSignal(str, str, int)  # 移动节点（节点ID，新父节点ID，新排序位置）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(20)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)

        # 连接信号
        self.itemClicked.connect(self._on_item_clicked)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

        # 右键菜单
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _on_item_clicked(self, item, column):
        """点击节点时发送选中信号"""
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        if node_id:
            self.node_selected.emit(node_id)

    def _on_item_double_clicked(self, item, column):
        """双击节点进行重命名"""
        self.editItem(item, column)

    def _show_context_menu(self, position):
        """显示右键菜单"""
        item = self.itemAt(position)
        menu = QMenu()

        if item:
            # 有选中项时的菜单
            new_child_action = QAction("新建子章节", self)
            new_child_action.triggered.connect(lambda: self._create_child_node(item))
            menu.addAction(new_child_action)

            new_sibling_action = QAction("新建同级章节", self)
            new_sibling_action.triggered.connect(lambda: self._create_sibling_node(item))
            menu.addAction(new_sibling_action)

            menu.addSeparator()

            delete_action = QAction("删除", self)
            delete_action.triggered.connect(lambda: self._delete_node(item))
            menu.addAction(delete_action)
        else:
            # 空白处右键，在根节点下创建
            new_root_child_action = QAction("新建章节", self)
            new_root_child_action.triggered.connect(self._create_root_child)
            menu.addAction(new_root_child_action)

        menu.exec(self.viewport().mapToGlobal(position))

    def _create_child_node(self, parent_item):
        """在选中节点下创建子节点"""
        parent_id = parent_item.data(0, Qt.ItemDataRole.UserRole)
        new_node_id = None  # 这个会在外部通过信号处理
        self.node_created.emit(parent_id, None)

    def _create_sibling_node(self, sibling_item):
        """在选中节点同级创建节点"""
        parent_item = sibling_item.parent()
        parent_id = parent_item.data(0, Qt.ItemDataRole.UserRole) if parent_item else None
        self.node_created.emit(parent_id, None)

    def _create_root_child(self):
        """在根节点下创建子节点"""
        self.node_created.emit(None, None)

    def _delete_node(self, item):
        """删除节点"""
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.node_deleted.emit(node_id)

    def add_node(self, parent_id, node_id, title):
        """添加节点到树中"""
        # 查找父节点
        parent_item = self._find_item_by_id(parent_id) if parent_id else None

        item = QTreeWidgetItem([title])
        item.setData(0, Qt.ItemDataRole.UserRole, node_id)

        if parent_item:
            parent_item.addChild(item)
        else:
            self.addTopLevelItem(item)

        # 展开父节点
        if parent_item:
            parent_item.setExpanded(True)

        return item

    def _find_item_by_id(self, node_id):
        """根据节点ID查找树节点"""

        def find_recursive(item):
            if item.data(0, Qt.ItemDataRole.UserRole) == node_id:
                return item
            for i in range(item.childCount()):
                result = find_recursive(item.child(i))
                if result:
                    return result
            return None

        for i in range(self.topLevelItemCount()):
            result = find_recursive(self.topLevelItem(i))
            if result:
                return result
        return None

    def update_node_title(self, node_id, new_title):
        """更新节点标题"""
        item = self._find_item_by_id(node_id)
        if item:
            item.setText(0, new_title)

    def remove_node(self, node_id):
        """从树中删除节点"""
        item = self._find_item_by_id(node_id)
        if item:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                self.takeTopLevelItem(self.indexOfTopLevelItem(item))

    def select_node(self, node_id):
        """选中指定节点"""
        item = self._find_item_by_id(node_id)
        if item:
            self.setCurrentItem(item)