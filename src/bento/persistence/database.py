"""
Database connection management for Bento application.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

# 获取数据库文件路径
DB_PATH = os.environ.get("BENTO_DB_PATH", "bento.db")

# 创建SQLAlchemy引擎
engine = create_engine(f"sqlite:///{DB_PATH}", convert_unicode=True)

# 创建会话工厂
db_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=engine)
)

# 创建基础模型类
Base = declarative_base()
Base.query = db_session.query_property()


def init_db(check_same_thread=False):
    """
    初始化数据库，创建所有表

    Args:
        check_same_thread: 是否禁用SQLite的同一线程检查，对多线程应用有用

    Returns:
        数据库会话对象
    """
    # 导入所有模块，以便Base的子类都被正确导入

    # 如果存在旧连接，关闭它
    db_session.remove()

    # 如果需要禁用检查同一线程（针对多线程应用）
    if check_same_thread:
        global engine
        engine = create_engine(
            f"sqlite:///{DB_PATH}",
            convert_unicode=True,
            connect_args={"check_same_thread": False},
        )

        # 更新会话工厂
        global db_session
        db_session = scoped_session(
            sessionmaker(autocommit=False, autoflush=False, bind=engine)
        )
        Base.query = db_session.query_property()

    # 创建所有表
    Base.metadata.create_all(bind=engine)

    return db_session
