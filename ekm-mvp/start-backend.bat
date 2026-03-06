@echo off
:: ─── EKM Backend — Conda Setup & Run (Windows) ───────────────────────────────
cd /d "%~dp0backend"

echo.
echo ╔══════════════════════════════════════╗
echo ║   EKM Backend — Conda Setup          ║
echo ╚══════════════════════════════════════╝
echo.

set ENV_NAME=ekm

:: Check conda
conda --version >nul 2>&1
if errorlevel 1 (
    echo ✗ conda not found.
    echo   Install Miniconda: https://docs.conda.io/en/latest/miniconda.html
    pause
    exit /b 1
)
echo ✓ conda found

:: Create env if needed
conda env list | findstr /B "%ENV_NAME% " >nul 2>&1
if errorlevel 1 (
    echo → Creating conda env '%ENV_NAME%' with Python 3.11...
    conda create -n %ENV_NAME% python=3.11 -y
    echo ✓ Conda env '%ENV_NAME%' created
) else (
    echo ✓ Conda env '%ENV_NAME%' already exists
)

:: Install dependencies
echo → Installing dependencies...
conda run -n %ENV_NAME% pip install -q --upgrade pip
conda run -n %ENV_NAME% pip install -q -r requirements.txt
echo ✓ Dependencies installed

:: Check .env
if not exist ".env" (
    echo.
    echo ⚠  No .env found. Creating from template...
    copy ..\env.example .env
    echo → Edit backend\.env with your credentials, then re-run.
    pause
    exit /b 1
)
echo ✓ .env found

:: Run
echo.
echo → Starting FastAPI on http://localhost:8000
echo    API docs: http://localhost:8000/docs
echo    Running inside conda env: %ENV_NAME%
echo.
conda run -n %ENV_NAME% uvicorn main:app --host 0.0.0.0 --port 8000 --reload
