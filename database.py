"""数据库连接管理"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """初始化数据库表 + 执行迁移"""
    from models import (
        User, Company, BidSource, BidNotice,
        Registration, Task, BidResult
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("数据库初始化完成")

    # 迁移：为已有数据库添加新字段
    await _migrate()


async def _migrate():
    """增量数据库迁移（幂等）"""
    import sqlite3
    import os
    from config import BASE_DIR

    db_path = os.path.join(BASE_DIR, "bid_tools.db")
    if not os.path.exists(db_path):
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.execute("PRAGMA table_info(bid_notices)")
    columns = [row[1] for row in cursor.fetchall()]

    # 添加 bid_decision 字段
    if "bid_decision" not in columns:
        conn.execute("ALTER TABLE bid_notices ADD COLUMN bid_decision VARCHAR(20)")
        conn.commit()
        print("[Migrate] 已添加 bid_notices.bid_decision 字段")

    # 添加 abandon_reason 字段
    if "abandon_reason" not in columns:
        conn.execute("ALTER TABLE bid_notices ADD COLUMN abandon_reason TEXT DEFAULT ''")
        conn.commit()
        print("[Migrate] 已添加 bid_notices.abandon_reason 字段")

    cursor.close()
    conn.close()
