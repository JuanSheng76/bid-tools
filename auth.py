"""认证模块：登录/注册/Session 管理"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import bcrypt
from database import get_db
from models import User, Company

router = APIRouter(prefix="/auth", tags=["auth"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

# 简单的内存 Session 存储（生产环境可用 Redis 替代）
SESSION_STORE: dict[str, dict] = {}


def create_session(user_id: str, username: str, full_name: str, role: str) -> str:
    """创建新 session"""
    import uuid
    session_id = str(uuid.uuid4())
    SESSION_STORE[session_id] = {
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "role": role,
        "created_at": datetime.utcnow(),
    }
    return session_id


def get_session(request: Request) -> dict | None:
    """从 cookie 获取 session"""
    session_id = request.cookies.get("session_id")
    if not session_id or session_id not in SESSION_STORE:
        return None
    return SESSION_STORE[session_id]


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    """获取当前登录用户（依赖注入）"""
    session = get_session(request)
    if not session:
        return None
    result = await db.execute(select(User).where(User.id == session["user_id"]))
    return result.scalar_one_or_none()


def require_auth(request: Request):
    """检查是否登录"""
    session = get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="请先登录")
    return session


def require_admin(request: Request):
    """检查是否管理员"""
    session = require_auth(request)
    if session["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return session


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """登录"""
    result = await db.execute(
        select(User).where(User.username == username, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        from fastapi.responses import HTMLResponse
        return HTMLResponse('<span class="text-danger">用户名或密码错误</span>')

    session_id = create_session(user.id, user.username, user.full_name, user.role)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("session_id", session_id, httponly=True, max_age=60*60*24*7)
    return response


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    """注册"""
    if len(username) < 2 or len(password) < 6:
        from fastapi.responses import HTMLResponse
        return HTMLResponse('<span class="text-danger">用户名至少2位，密码至少6位</span>')

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        from fastapi.responses import HTMLResponse
        return HTMLResponse('<span class="text-danger">用户名已存在</span>')

    user = User(
        username=username,
        password_hash=hash_password(password),
        full_name=full_name,
        role="admin" if not await _has_users(db) else "staff",
    )
    db.add(user)
    await db.commit()

    session_id = create_session(user.id, user.username, user.full_name, user.role)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie("session_id", session_id, httponly=True, max_age=60*60*24*7)
    return response


@router.get("/logout")
async def logout(request: Request):
    """登出"""
    session_id = request.cookies.get("session_id")
    if session_id and session_id in SESSION_STORE:
        del SESSION_STORE[session_id]
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_id")
    return response


async def _has_users(db: AsyncSession) -> bool:
    """检查是否有用户"""
    result = await db.execute(select(User).limit(1))
    return result.scalar_one_or_none() is not None
