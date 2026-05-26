@echo off
cd /d "%~dp0"
title Asset Manager — Build
color 0A

echo ============================================================
echo   Asset Manager — Building All Components
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 ( echo [ERROR] Python not found. & pause & exit /b 1 )

echo [1/7] Installing dependencies...
pip install flask flask-cors requests pillow pystray pyinstaller openpyxl "cryptography>=42.0.0" pyopenssl pywin32 --quiet
if errorlevel 1 ( echo [ERROR] pip failed. & pause & exit /b 1 )
echo    Done.
echo.

if not exist "dist"   mkdir dist
if not exist "output" mkdir output

echo [2/7] Building AssetServer.exe...
pyinstaller --noconfirm --onefile --name "AssetServer" --hidden-import win32timezone server.py
if errorlevel 1 ( echo [ERROR] Server build failed. & pause & exit /b 1 )

echo [3/7] Building StorekeeperApp.exe...
pyinstaller --noconfirm --onefile --windowed --name "StorekeeperApp" storekeeper_app.py
if errorlevel 1 ( echo [ERROR] Storekeeper build failed. & pause & exit /b 1 )

echo [4/7] Building NotifierApp.exe...
pyinstaller --noconfirm --onefile --windowed --name "NotifierApp" notifier_app.py
if errorlevel 1 ( echo [ERROR] Notifier build failed. & pause & exit /b 1 )

echo [5/7] Building AssetManager_Setup.exe (unified installer)...
pyinstaller --noconfirm --onefile --windowed --uac-admin --name "AssetManager_Setup" ^
  --add-data "dist\AssetServer.exe;."    ^
  --add-data "dist\StorekeeperApp.exe;." ^
  --add-data "dist\NotifierApp.exe;."    ^
  installer.py
if errorlevel 1 ( echo [ERROR] Installer build failed. & pause & exit /b 1 )

echo [6/7] Copying deliverables to output\...
copy /Y "dist\AssetServer.exe"        "output\"
copy /Y "dist\StorekeeperApp.exe"     "output\"
copy /Y "dist\NotifierApp.exe"        "output\"
copy /Y "dist\AssetManager_Setup.exe" "output\"
copy /Y "config.json"                 "output\"
if exist "ssl_cert.pem" copy /Y "ssl_cert.pem" "output\"

echo [7/7] Cleaning up PyInstaller temp files...
rmdir /S /Q build 2>nul
del /Q *.spec    2>nul

echo.
echo ============================================================
echo   BUILD COMPLETE
echo ============================================================
echo.
echo   output\AssetManager_Setup.exe  ^<-- Give THIS to everyone
echo.
echo   What each installer option does:
echo     Server      -^> Install on asset-server (run permanently)
echo     Storekeeper -^> Install on Storekeeper User's PC
echo     Notifier    -^> Install on each engineer's laptop
echo                    (select engineer name -- no PIN needed)
echo.
echo   FIRST RUN defaults:
echo     Server URL    : https://asset-server:8081
echo     Admin password: admin  (change it on first login)
echo     Port          : 8081  (open in firewall -- see below)
echo.
echo   NOTE: asset_lookup.xlsx is embedded inside AssetServer.exe.
echo         It is extracted automatically on first run.
echo         To update the lookup sheet use Admin Upload Lookup File.
echo.
echo   ONE-TIME firewall rule on asset-server:
echo   netsh advfirewall firewall add rule name="Asset Manager" dir=in action=allow protocol=TCP localport=8081
echo.
pause
