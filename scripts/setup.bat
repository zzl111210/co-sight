@echo off
chcp 65001 >nul
echo ============================================
echo  NetHeal-Agent 一键安装 (Windows)
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 未安装，请先安装 Python 3.11+
    pause
    exit /b 1
)

echo [1/4] 创建虚拟环境...
python -m venv .venv
if %errorlevel% neq 0 (
    echo [ERROR] 创建虚拟环境失败
    pause
    exit /b 1
)

echo [2/4] 安装依赖...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARNING] 部分依赖安装失败，尝试继续...
)

echo [3/4] 应用兼容性补丁...
.venv\Scripts\python scripts\patch_deps.py
if %errorlevel% neq 0 (
    echo [WARNING] 补丁应用失败，尝试继续...
)

echo [4/4] 配置环境...
if not exist .env (
    copy .env_template .env >nul
    echo   已从模板创建 .env 文件
    echo   [重要] 请编辑 .env，填入你的 API_KEY ！
) else (
    echo   .env 文件已存在，跳过
)

echo.
echo ============================================
echo  安装完成！
echo ============================================
echo.
echo  下一步：
echo    1. 编辑 .env 文件，填入 API_KEY
echo    2. 运行: .venv\Scripts\python cosight_server\deep_research\main.py
echo    3. 打开: http://localhost:7788/cosight/netheal.html
echo.
echo  或者用 Docker 一键启动（无需安装 Python）：
echo    docker build -t netheal-agent .
echo    docker run -d -p 7788:7788 -v .\.env:/app/.env:ro netheal-agent
echo.
pause
