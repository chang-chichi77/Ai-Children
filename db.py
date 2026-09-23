"""數據庫訪問模塊 - MySQL 連接和操作"""

import os
import logging
from contextlib import contextmanager
import mysql.connector
from mysql.connector import Error

logger = logging.getLogger(__name__)


class DatabaseConfig:
    """數據庫配置"""

    def __init__(self):
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = int(os.getenv("DB_PORT", 3306))
        self.user = os.getenv("DB_USER", "root")
        self.password = os.getenv("DB_PASSWORD", "")
        self.database = os.getenv("DB_NAME", "aichildren")

    def to_dict(self):
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
        }


class MysqlAccess:
    """MySQL 數據庫訪問類"""

    _config = DatabaseConfig()

    @classmethod
    def set_config(cls, **kwargs):
        """設置數據庫配置"""
        for key, value in kwargs.items():
            setattr(cls._config, key, value)

    @classmethod
    @contextmanager
    def get_connection(cls):
        """取得數據庫連接（上下文管理器）"""
        conn = None
        try:
            conn = mysql.connector.connect(**cls._config.to_dict())
            yield conn
        except Error as e:
            logger.error(f"數據庫連接失敗: {e}")
            raise
        finally:
            if conn and conn.is_connected():
                conn.close()

    @classmethod
    def execute(cls, sql, params=None):
        """執行 INSERT/UPDATE/DELETE 語句

        Args:
            sql: SQL 語句
            params: 參數列表

        Returns:
            lastrowid 或受影響的行數
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params or [])
                conn.commit()
                affected_rows = cursor.rowcount
                lastrowid = cursor.lastrowid
                cursor.close()

                logger.debug(f"✅ SQL 執行成功 - 受影響行數: {affected_rows}")
                return lastrowid if lastrowid > 0 else affected_rows

        except Error as e:
            logger.error(f"❌ SQL 執行失敗: {e}\nSQL: {sql}\n參數: {params}")
            raise

    @classmethod
    def query(cls, sql, params=None):
        """執行 SELECT 語句

        Args:
            sql: SQL 語句
            params: 參數列表

        Returns:
            結果列表（字典格式）
        """
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(sql, params or [])
                results = cursor.fetchall()
                cursor.close()

                logger.debug(f"✅ 查詢成功 - 返回 {len(results)} 行")
                return results

        except Error as e:
            logger.error(f"❌ 查詢失敗: {e}\nSQL: {sql}")
            raise

    @classmethod
    def query_one(cls, sql, params=None):
        """執行 SELECT 語句，返回單條結果"""
        results = cls.query(sql, params)
        return results[0] if results else None

    @classmethod
    def init_db(cls):
        """初始化數據庫表結構"""
        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()

                # 創建 users 表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT UNIQUE NOT NULL,
                        role_str VARCHAR(50) NOT NULL,
                        email VARCHAR(100) UNIQUE,
                        password_hash VARCHAR(255),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                logger.info("✅ users 表已就位")

                # 創建 fall_events 表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS fall_events (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        event_time DATETIME NOT NULL,
                        confidence FLOAT DEFAULT 0.0,
                        location VARCHAR(100),
                        alert_sent BOOLEAN DEFAULT FALSE,
                        alert_time DATETIME,
                        status ENUM('detected', 'confirmed', 'resolved', 'false_alarm') DEFAULT 'detected',
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        INDEX idx_user_id (user_id),
                        INDEX idx_event_time (event_time),
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """)
                logger.info("✅ fall_events 表已就位")

                conn.commit()
                cursor.close()
                logger.info("✅ 數據庫初始化完成")
                return True

        except Error as e:
            logger.error(f"❌ 數據庫初始化失敗: {e}")
            raise
