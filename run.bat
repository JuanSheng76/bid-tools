@echo off
chcp 65001 >nul
echo ========================================
echo   标策台 - 启动
echo ========================================
echo.

:: 检查 Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    where py >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo [错误] 未找到 Python，请先安装 Python 3.12+
        echo 下载地址: https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

echo [1/4] 检查依赖...
%PYTHON% -c "import fastapi" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [安装] 正在安装依赖包...
    %PYTHON% -m pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
) else (
    echo [跳过] 依赖已安装
)

echo [2/4] 初始化数据库...
%PYTHON% -c "import asyncio; from database import init_db; asyncio.run(init_db())"
echo [完成] 数据库就绪

echo [3/4] 初始化标讯来源...
%PYTHON% seed_sources.py
echo [完成] 标讯来源就绪

echo [4/4] 启动服务器...
echo.
echo   浏览器打开: http://127.0.0.1:8000
echo   按 Ctrl+C 停止
echo ========================================
echo.
%PYTHON% main.py
pause
