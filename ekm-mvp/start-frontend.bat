@echo off
:: ─── EKM Frontend — Local Setup & Run (Windows) ──────────────────────────────
cd /d "%~dp0frontend"

echo.
echo ╔══════════════════════════════════════╗
echo ║   EKM Frontend — Local Setup         ║
echo ╚══════════════════════════════════════╝
echo.

:: Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo ✗ Node.js not found. Install from https://nodejs.org ^(v18+^)
    pause
    exit /b 1
)
echo ✓ Node found

:: Install
if not exist "node_modules" (
    echo → Installing npm packages...
    npm install
) else (
    echo ✓ node_modules already exists
)

echo.
echo → Starting frontend on http://localhost:3000
echo.
npm run dev
