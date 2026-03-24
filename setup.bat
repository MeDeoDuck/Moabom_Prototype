@echo off
REM Quick Start Script for YouTube Product Analysis Service (Windows)

echo.
echo 🚀 YouTube Product Analysis Service - Quick Start
echo ==================================================
echo.

REM Check Python version
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python not found. Please install Python 3.11+
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set python_version=%%i
echo ✓ Python version: %python_version%

REM Check if .env exists
if not exist .env (
    echo.
    echo ⚠️  .env file not found. Please create it with:
    echo    DATABASE_URL=postgresql://user:password@localhost:5432/techdb
    echo    YOUTUBE_API_KEY=your_api_key_here
    exit /b 1
)

echo ✓ .env file found

REM Install dependencies
echo.
echo 📦 Installing dependencies...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo ❌ Failed to install dependencies
    exit /b 1
)
echo ✓ Dependencies installed

REM Create templates directory
if not exist templates mkdir templates
echo ✓ Templates directory ready

echo.
echo ✅ Setup complete!
echo.
echo 📝 Next steps:
echo    1. Ensure PostgreSQL is running
echo    2. Update .env with your DATABASE_URL and YOUTUBE_API_KEY
echo    3. Run: python main_youtube_analysis.py
echo    4. Open: http://localhost:8000
echo.
echo 📖 For more info, see README_YOUTUBE_SERVICE.md
echo.
