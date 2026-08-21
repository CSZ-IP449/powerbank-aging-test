@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set APP_DIR=%~dp0

echo ============================================
echo   Build Desktop Aging Test App
echo ============================================
echo.

echo [1/3] Building frontend...
cd /d "%APP_DIR%frontend"
call npm install
if errorlevel 1 (
    echo npm install failed
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo npm run build failed
    pause
    exit /b 1
)

echo.
echo [2/3] Checking frontend dist...
if not exist "%APP_DIR%frontend\dist\index.html" (
    echo frontend dist not found, build failed
    pause
    exit /b 1
)

echo.
echo [3/3] Running PyInstaller...
cd /d "%APP_DIR%backend"
pyinstaller desktop.spec --noconfirm --clean
if errorlevel 1 (
    echo PyInstaller failed
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build success
echo   Output: %APP_DIR%backend\dist\aging-test.exe
echo ============================================
pause
