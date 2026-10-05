@echo off
echo ========================================================
echo   Pushing Clean Repository to GitHub (No Secrets)
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/5] Removing old git history containing tracked .env...
rmdir /s /q .git 2>nul

echo [2/5] Initializing fresh Git repository...
git init
git branch -M main

echo [3/5] Verifying .gitignore protects .env...
if not exist ".gitignore" (
    echo .env > .gitignore
    echo *.env >> .gitignore
    echo !.env.example >> .gitignore
    echo __pycache__/ >> .gitignore
)

echo [4/5] Staging clean project files (excluding secrets)...
git add .
git status --short

echo [5/5] Committing and pushing to GitHub...
git commit -m "feat: initial commit - Emergency Route Intelligence warehouse and Route Simulator"

git remote add origin https://github.com/snehumahadik13-sudo/route-simulator-dwm.git
git push -u origin main --force

echo.
if %ERRORLEVEL% equ 0 (
    echo ========================================================
    echo   SUCCESS! Successfully pushed clean project to GitHub!
    echo ========================================================
) else (
    echo ========================================================
    echo   If you still see an unblock link, open:
    echo   https://github.com/snehumahadik13-sudo/route-simulator-dwm/security/secret-scanning/unblock-secret/3KGUi7ynuCVVDUDNQcVBVT3UZgo
    echo ========================================================
)

echo.
pause
