@echo off
setlocal enabledelayedexpansion
title PaperSkim
cd /d "%~dp0"

echo ==========================================
echo   PaperSkim - condense arXiv papers
echo ==========================================
echo.

REM ---------- 1. backend dependencies ----------
where uv >nul 2>nul
if %errorlevel%==0 (
    echo [1/4] Setting up backend with uv...
    if not exist .venv uv venv
    uv sync --no-dev
) else (
    echo [1/4] Setting up backend with python venv...
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Python not found. Install Python 3.10+ from https://python.org
        echo        (or install uv from https://docs.astral.sh/uv/ and re-run)
        pause
        exit /b 1
    )
    if not exist .venv python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check fastapi uvicorn httpx
)

REM ---------- 2. OpenRouter key ----------
echo.
if exist backend\paperskim.toml (
    echo A saved OpenRouter API key was found.
) else (
    echo No OpenRouter API key saved yet.
)
set "KEY="
set /p KEY="Paste your key to save/replace it, or press Enter to keep existing: "
if not "!KEY!"=="" (
    > backend\paperskim.toml echo [openrouter]
    >> backend\paperskim.toml echo api_key = "!KEY!"
    echo Key saved to backend\paperskim.toml
)

REM ---------- 3. frontend dependencies ----------
echo.
echo [2/4] Setting up frontend...
where npm >nul 2>nul
if errorlevel 1 (
    echo ERROR: npm not found. Install Node.js from https://nodejs.org
    pause
    exit /b 1
)
if not exist frontend\node_modules (
    pushd frontend
    call npm i --include=dev
    popd
)

REM ---------- 4. launch ----------
echo.
echo [3/4] Starting backend on http://localhost:8000 ...
start "PaperSkim backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000"

echo [4/4] Starting frontend on http://localhost:5173 ...
start "PaperSkim frontend" /D frontend cmd /k npm run dev

timeout /t 6 /nobreak >nul
start http://localhost:5173

echo.
echo PaperSkim is running. Close the two new windows to stop it.
echo (This launcher window can be closed.)
timeout /t 8 /nobreak >nul
