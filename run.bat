@echo off
setlocal enabledelayedexpansion
title PaperSkim
cd /d "%~dp0"

echo ==========================================
echo   PaperSkim - condense papers into PDFs
echo ==========================================
echo.

REM ---------- 1. Python 3.11+ ----------
set "PYOK="
where python >nul 2>nul && (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PYOK=1"
)
if "%PYOK%"=="" (
    echo ERROR: Python 3.11+ is required ^(tomllib and syntax used by the backend^).
    echo        Install it from https://www.python.org/downloads/ and re-run.
    pause
    exit /b 1
)

REM ---------- 2. backend dependencies ----------
set "BACKEND_OK="
where uv >nul 2>nul && (
    echo [1/4] Setting up backend with uv...
    if not exist .venv uv venv
    uv sync --no-dev && set "BACKEND_OK=1"
)
if "%BACKEND_OK%"=="1" goto backend_done
echo uv unavailable or failed - falling back to pip...
if not exist .venv python -m venv .venv
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check fastapi "uvicorn[standard]" httpx python-multipart && set "BACKEND_OK=1"
:backend_done
if "%BACKEND_OK%"=="" (
    echo ERROR: could not install backend dependencies. See the messages above.
    pause
    exit /b 1
)

REM ---------- 3. OpenRouter key ----------
echo.
if exist backend\paperskim.toml (
    echo A saved OpenRouter API key was found.
) else (
    echo No OpenRouter API key saved yet. Get one at https://openrouter.ai/keys
)
set "KEY="
set /p KEY="Paste your key to save/replace it, or press Enter to keep existing: "
if not "!KEY!"=="" (
    > backend\paperskim.toml echo [openrouter]
    >> backend\paperskim.toml echo api_key = "!KEY!"
    echo Key saved to backend\paperskim.toml ^(it is verified live when you save from the app^).
)

REM ---------- 4. LaTeX / poppler ----------
echo.
echo [2/4] Checking LaTeX and poppler...
where tectonic >nul 2>nul || (
    echo WARNING: tectonic not found - PDFs cannot be compiled without it.
    echo   Install: winget install Tectonic.Tectonic   ^(or: scoop install tectonic^)
)
where pdftotext >nul 2>nul || (
    echo WARNING: poppler tools ^(pdftotext/pdfinfo^) not found - non-arXiv PDF jobs will fail.
    echo   Install: download poppler for Windows ^(e.g. https://github.com/oschwartz10612/poppler-windows/releases^) and add bin\ to PATH
)

REM ---------- 5. frontend dependencies ----------
echo [3/4] Setting up frontend...
where npm >nul 2>nul || (
    echo ERROR: npm not found. Install Node.js from https://nodejs.org
    pause
    exit /b 1
)
if not exist frontend\node_modules (
    pushd frontend
    call npm i --include=dev
    popd
)

REM ---------- 6. launch ----------
echo.
echo [4/4] Starting backend on http://localhost:8000 ...
start "PaperSkim backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app.main:app --port 8000"

echo Starting frontend on http://localhost:5173 ...
start "PaperSkim frontend" /D frontend cmd /k npm run dev

timeout /t 6 /nobreak >nul
start http://localhost:5173

echo.
echo PaperSkim is running. Close the two new windows to stop it.
echo (This launcher window can be closed.)
timeout /t 8 /nobreak >nul
