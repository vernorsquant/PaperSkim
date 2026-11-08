@echo off
setlocal enabledelayedexpansion
title PaperSkim Setup
cd /d "%~dp0"

echo ==============================================
echo   PaperSkim setup - installs everything needed
echo ==============================================
echo.

REM ---------- 0. winget (used to install system tools) ----------
set "WINGET="
where winget >nul 2>nul && set "WINGET=1"
if "%WINGET%"=="" (
    echo WARNING: winget not found. It ships with Windows 11 and with
    echo   "App Installer" from the Microsoft Store on Windows 10.
    echo Setup will try direct downloads where possible, but some tools
    echo   must be installed by hand. See the messages below.
)

REM ---------- 1. Python 3.11+ ----------
set "PYOK="
where python >nul 2>nul && (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PYOK=1"
)
if "%PYOK%"=="" (
    echo [1/6] Installing Python 3.12 via winget...
    if "%WINGET%"=="1" (
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        REM make the fresh install visible to THIS session
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    ) else (
        echo   Install Python 3.11+ from https://www.python.org/downloads/
        echo   ^(tick "Add python.exe to PATH"^), then re-run this setup.
    )
)
where python >nul 2>nul && (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PYOK=1"
)
if "%PYOK%"=="" (
    echo ERROR: Python 3.11+ is required but not available. Install it, then re-run setup.
    pause
    exit /b 1
)
echo       Python OK.

REM ---------- 2. uv (fast Python dependency manager) ----------
set "UVOK="
where uv >nul 2>nul && set "UVOK=1"
if "%UVOK%"=="" (
    echo [2/6] Installing uv...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>nul && set "UVOK=1"
)
if "%UVOK%"=="" (
    echo   uv installer failed - trying pip instead...
    python -m pip install --quiet --disable-pip-version-check uv && set "UVOK=1"
)
echo       uv OK.

REM ---------- 3. backend dependencies ----------
echo [3/6] Installing backend dependencies...
set "BACKEND_OK="
if "%UVOK%"=="1" (
    if not exist .venv uv venv
    uv sync --no-dev && set "BACKEND_OK=1"
)
if "%BACKEND_OK%"=="1" goto backend_done
echo   uv unavailable or failed - falling back to pip...
if not exist .venv python -m venv .venv
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check fastapi "uvicorn[standard]" httpx python-multipart && set "BACKEND_OK=1"
:backend_done
if "%BACKEND_OK%"=="" (
    echo ERROR: could not install backend dependencies. See the messages above.
    pause
    exit /b 1
)
echo       Backend OK.

REM ---------- 4. tectonic (LaTeX) + poppler (pdftotext/pdfinfo) ----------
echo [4/6] Installing LaTeX ^(tectonic^) and poppler...
where tectonic >nul 2>nul || (
    if "%WINGET%"=="1" (
        winget install -e --id Tectonic.Tectonic --accept-package-agreements --accept-source-agreements
    ) else (
        echo   Install tectonic: scoop install tectonic   OR   cargo install tectonic
    )
)
where pdftotext >nul 2>nul || (
    if "%WINGET%"=="1" (
        winget install -e --id oschwartz10612.Poppler --accept-package-agreements --accept-source-agreements
    ) else (
        echo   Install poppler for Windows:
        echo     https://github.com/oschwartz10612/poppler-windows/releases
        echo     ^(unzip and add the Library\bin folder to PATH^)
    )
)
REM refresh PATH for tools winget just installed, so the checks below can see them
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\oschwartz10612.Poppler_*") do (
    for /d %%P in ("%%D\poppler-*") do set "PATH=%%P\Library\bin;!PATH!"
)
set "TEXOK=1"
where tectonic >nul 2>nul || set "TEXOK="
where pdftotext >nul 2>nul || set "TEXOK="
if "%TEXOK%"=="" (
    echo   NOTE: tectonic/pdftotext were installed but may need a NEW terminal
    echo   window ^(or a sign-out^) before they appear on PATH. PDF jobs will
    echo   fail until then. Re-run this setup to verify.
) else (
    echo       LaTeX + poppler OK.
)

REM ---------- 5. Node.js + frontend dependencies ----------
echo [5/6] Installing Node.js and frontend dependencies...
where npm >nul 2>nul || (
    if "%WINGET%"=="1" (
        echo   Installing Node.js LTS via winget ^(accept the UAC prompt if one appears^)...
        winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
        set "PATH=%ProgramFiles%\nodejs;%PATH%"
    ) else (
        echo   Install Node.js LTS from https://nodejs.org ^(includes npm^)
    )
)
where npm >nul 2>nul || (
    echo   NOTE: npm may need a NEW terminal window before it appears on PATH.
    echo   After that, re-run this setup to install frontend packages.
    goto key_prompt
)
if not exist frontend\node_modules (
    pushd frontend
    call npm i --include=dev
    popd
)
echo       Frontend OK.

:key_prompt
REM ---------- 6. OpenRouter key ----------
echo.
echo [6/6] OpenRouter API key.
if exist backend\paperskim.toml (
    echo A saved key was found.
) else (
    echo Get one at https://openrouter.ai/keys
)
set "KEY="
set /p KEY="Paste a key to save/replace it, or press Enter to keep existing: "
if not "!KEY!"=="" (
    > backend\paperskim.toml echo [openrouter]
    >> backend\paperskim.toml echo api_key = "!KEY!"
    echo Key saved to backend\paperskim.toml.
)

REM ---------- summary ----------
echo.
echo ==============================================
echo   Setup summary
echo ==============================================
call :check python   "Python 3.11+"
call :check uv       "uv"
call :check tectonic "tectonic (LaTeX)"
call :check pdftotext "poppler (pdftotext)"
call :check npm      "npm"
echo.
echo Done. Double-click run.bat to start PaperSkim.
echo If any check above failed, open a NEW terminal window and re-run setup.bat.
pause
exit /b 0

:check
where %~1 >nul 2>nul && (
    echo   [OK]   %~2
) || (
    echo   [FAIL] %~2 - open a new terminal and re-run setup.bat
)
exit /b 0
