import sqlite3
from sqlite3 import Error
from typing import Optional
import os
from pathlib import Path
from common.log import logger
import time


class UserSessionManager:
    def __init__(self, db_path: str = "sessions.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """初始化数据库和表结构"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            try:
                conn.execute("""PRAGMA foreign_keys = ON""")
                conn.execute("""PRAGMA journal_mode = WAL""")
                conn.execute("""PRAGMA synchronous = NORMAL""")

                conn.execute(
                    """CREATE TABLE IF NOT EXISTS user_sessions (
                                user_id TEXT PRIMARY KEY,
                                conversation_id TEXT NOT NULL,
                                created_at INTEGER NOT NULL
                            )"""
                )
                conn.commit()
            except Error as e:
                logger.error(f"初始化数据库失败: {str(e)}")

    def _get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def create_session(self, user_id: str, conversation_id: str) -> bool:
        """创建或更新用户会话"""
        with self._get_connection() as conn:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO user_sessions 
                             (user_id, conversation_id, created_at)
                             VALUES (?, ?, ?)""",
                    (user_id, conversation_id, int(time.time())),
                )
                conn.commit()
                return True
            except Error as e:
                logger.error(f"创建会话失败: {str(e)}")
                return False

    def get_session(self, user_id: str) -> Optional[str]:
        """获取用户会话ID"""
        with self._get_connection() as conn:
            try:
                cursor = conn.execute(
                    """SELECT conversation_id 
                                      FROM user_sessions 
                                      WHERE user_id = ?""",
                    (user_id,),
                )
                result = cursor.fetchone()
                return result[0] if result else None
            except Error as e:
                logger.error(f"获取会话失败: {str(e)}")
                return None

    def delete_session(self, user_id: str) -> bool:
        """删除用户会话"""
        with self._get_connection() as conn:
            try:
                conn.execute(
                    """DELETE FROM user_sessions 
                             WHERE user_id = ?""",
                    (user_id,),
                )
                conn.commit()
                return True
            except Error as e:
                logger.error(f"删除会话失败: {str(e)}")
                return False
