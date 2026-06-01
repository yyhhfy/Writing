import sqlite3
import time
import uuid


class Database:
    def __init__(self, db_path="writing_data.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        """获取数据库连接，启用 WAL 模式"""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")  # 性能与安全的平衡
        return conn

    def _init_db(self):
        """初始化数据库表结构"""
        conn = self._get_conn()
        conn.execute("""
                     CREATE TABLE IF NOT EXISTS outline_nodes
                     (
                         id
                         TEXT
                         PRIMARY
                         KEY,
                         parent_id
                         TEXT,
                         title
                         TEXT
                         NOT
                         NULL,
                         content
                         TEXT,
                         sort_order
                         INTEGER
                         DEFAULT
                         0,
                         created_at
                         INTEGER,
                         updated_at
                         INTEGER
                     )
                     """)
        # 创建默认根节点（如果不存在）
        root = self.get_root_node()
        if not root:
            root_id = str(uuid.uuid4())
            conn.execute("""
                         INSERT INTO outline_nodes (id, parent_id, title, content, sort_order, created_at, updated_at)
                         VALUES (?, NULL, '我的作品', '<p>开始写作吧...</p>', 0, ?, ?)
                         """, (root_id, int(time.time()), int(time.time())))
            conn.commit()
        conn.close()

    def get_root_node(self):
        """获取根节点（parent_id 为 NULL 的那个）"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT id, title FROM outline_nodes WHERE parent_id IS NULL LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row if row else None

    def get_children(self, parent_id):
        """获取某个节点的所有子节点"""
        conn = self._get_conn()
        cursor = conn.execute("""
                              SELECT id, title, sort_order
                              FROM outline_nodes
                              WHERE parent_id = ?
                              ORDER BY sort_order ASC
                              """, (parent_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_node(self, node_id):
        """获取单个节点信息"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT id, parent_id, title, content FROM outline_nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        conn.close()
        return row

    def save_node_content(self, node_id, html_content):
        """保存节点内容（事务保护）"""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                         UPDATE outline_nodes
                         SET content    = ?,
                             updated_at = ?
                         WHERE id = ?
                         """, (html_content, int(time.time()), node_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"保存失败: {e}")
        finally:
            conn.close()

    def save_node_title(self, node_id, title):
        """保存节点标题"""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                         UPDATE outline_nodes
                         SET title      = ?,
                             updated_at = ?
                         WHERE id = ?
                         """, (title, int(time.time()), node_id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"保存标题失败: {e}")
        finally:
            conn.close()

    def create_node(self, parent_id, title="新章节"):
        """创建新节点"""
        node_id = str(uuid.uuid4())
        now = int(time.time())
        # 获取当前 parent 下最大的 sort_order
        conn = self._get_conn()
        cursor = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM outline_nodes WHERE parent_id = ?",
                              (parent_id,))
        sort_order = cursor.fetchone()[0]

        conn.execute("""
                     INSERT INTO outline_nodes (id, parent_id, title, content, sort_order, created_at, updated_at)
                     VALUES (?, ?, ?, '<p>新章节内容...</p>', ?, ?, ?)
                     """, (node_id, parent_id, title, sort_order, now, now))
        conn.commit()
        conn.close()
        return node_id

    def delete_node(self, node_id):
        """删除节点及其所有子节点"""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 递归删除所有子节点
            self._delete_node_recursive(conn, node_id)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"删除失败: {e}")
        finally:
            conn.close()

    def _delete_node_recursive(self, conn, node_id):
        """递归删除节点及其子节点"""
        # 先获取所有子节点
        cursor = conn.execute("SELECT id FROM outline_nodes WHERE parent_id = ?", (node_id,))
        children = cursor.fetchall()
        for child in children:
            self._delete_node_recursive(conn, child[0])
        # 删除当前节点
        conn.execute("DELETE FROM outline_nodes WHERE id = ?", (node_id,))

    def update_node_sort_order(self, node_id, new_sort_order):
        """更新节点的排序顺序"""
        conn = self._get_conn()
        conn.execute("UPDATE outline_nodes SET sort_order = ? WHERE id = ?", (new_sort_order, node_id))
        conn.commit()
        conn.close()

    def update_node_parent(self, node_id, new_parent_id, new_sort_order):
        """移动节点到新的父节点下"""
        conn = self._get_conn()
        conn.execute("""
                     UPDATE outline_nodes
                     SET parent_id  = ?,
                         sort_order = ?,
                         updated_at = ?
                     WHERE id = ?
                     """, (new_parent_id, new_sort_order, int(time.time()), node_id))
        conn.commit()
        conn.close()

    def get_all_nodes(self):
        """获取所有节点（用于导出）"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT id, parent_id, title, content, sort_order FROM outline_nodes ORDER BY parent_id, sort_order")
        rows = cursor.fetchall()
        conn.close()
        return rows