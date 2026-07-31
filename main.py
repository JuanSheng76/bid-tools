"""FastAPI 主入口"""
import os
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from database import init_db, async_session
from sqlalchemy import select
from models import BidSource, User
from config import DEMO_MODE, DISABLE_SCHEDULER

from auth import router as auth_router
from routers import dashboard, notices, company, tasks, results, sources, registrations, calendar, tender


async def scheduled_scrape_all():
    """定时爬取所有活跃来源"""
    from services.scraper import scrape_source
    async with async_session() as db:
        result = await db.execute(
            select(BidSource).where(BidSource.is_active == True)
        )
        sources_list = result.scalars().all()
        for src in sources_list:
            try:
                count = await scrape_source(src, db)
                src.last_scraped_at = datetime.utcnow()
                src.last_status = "success" if count >= 0 else "failed"
                await db.commit()
                print(f"[Scheduler] {src.name}: {count} 条新标讯")
            except Exception as e:
                print(f"[Scheduler] {src.name} 爬取失败: {e}")


async def _seed_demo_if_needed(app: FastAPI):
    """演示模式或无用户时自动填充演示数据"""
    async with async_session() as db:
        result = await db.execute(select(User).limit(1))
        has_users = result.scalar_one_or_none() is not None

    if DEMO_MODE or not has_users:
        print("[Demo] 正在填充演示数据...")
        import asyncio
        from seed_demo import seed_demo
        await seed_demo()
        print("[Demo] 演示数据填充完成")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # 设置演示模式标记
    app.state.demo_mode = DEMO_MODE

    # 填充演示数据
    await _seed_demo_if_needed(app)

    # 定时爬取调度器（云环境可禁用）
    if not DISABLE_SCHEDULER:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            scheduled_scrape_all,
            "interval",
            minutes=30,
            id="scrape_all",
            next_run_time=None,  # 启动后不立即执行
        )
        scheduler.start()
        print("[Scheduler] 定时爬取已启动（每30分钟）")
    else:
        scheduler = None
        print("[Scheduler] 定时爬取已禁用（DISABLE_SCHEDULER=1）")

    yield

    if scheduler:
        scheduler.shutdown(wait=False)
        print("[Scheduler] 已停止")


app = FastAPI(title="标策台", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(dashboard.router)
app.include_router(notices.router)
app.include_router(company.router)
app.include_router(tasks.router)
app.include_router(results.router)
app.include_router(sources.router)
app.include_router(registrations.router)
app.include_router(calendar.router)
app.include_router(tender.router)

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    reload = os.environ.get("RELOAD", "").lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=reload)
