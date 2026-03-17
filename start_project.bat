@echo off
setlocal EnableDelayedExpansion

:: Resolve the directory containing this .bat file (handles spaces in paths)
set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"

echo.
echo =========================================
echo   G-Code Feature Extractor
echo =========================================
echo.

:: ---------- Pre-flight checks ----------

if not exist "%BACKEND%\.venv\Scripts\activate.bat" (
    echo [ERROR] Backend virtual environment not found.
    echo.
    echo  Fix: open a terminal and run:
    echo    cd /d "%BACKEND%"
    echo    python -m venv .venv
    echo    .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%FRONTEND%\node_modules" (
    echo [ERROR] Frontend node_modules not found.
    echo.
    echo  Fix: open a terminal and run:
    echo    cd /d "%FRONTEND%"
    echo    npm install
    echo.
    pause
    exit /b 1
)

:: ---------- Write temporary launchers (avoids nested-quote issues) ----------

set "TMP_BACK=%TEMP%\gcode_backend_start.bat"
set "TMP_FRONT=%TEMP%\gcode_frontend_start.bat"

(
    echo @echo off
    echo title GCode-Backend
    echo cd /d "%BACKEND%"
    echo call .venv\Scripts\activate.bat
    echo echo Backend starting on http://localhost:8000
    echo uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
) > "%TMP_BACK%"

(
    echo @echo off
    echo title GCode-Frontend
    echo cd /d "%FRONTEND%"
    echo echo Frontend starting on http://localhost:5173
    echo npm run dev
) > "%TMP_FRONT%"

:: ---------- Backend ----------

echo [1/3] Starting backend  ^(FastAPI  ^| http://localhost:8000^)...
start "GCode-Backend"  cmd /k "%TMP_BACK%"

echo      Waiting 4 s for backend to initialise...
timeout /t 4 /nobreak > nul

:: ---------- Frontend ----------

echo [2/3] Starting frontend ^(Vite     ^| http://localhost:5173^)...
start "GCode-Frontend" cmd /k "%TMP_FRONT%"

echo      Waiting 6 s for Vite to bundle...
timeout /t 6 /nobreak > nul

:: ---------- Browser ----------

echo [3/3] Opening http://localhost:5173 ...
start "" "http://localhost:5173"

echo.
echo =========================================
echo   Both services are running.
echo.
echo   App      :  http://localhost:5173
echo   API docs :  http://localhost:8000/docs
echo.
echo   Close the two titled terminal windows
echo   ^(GCode-Backend / GCode-Frontend^) to stop.
echo =========================================
echo.

:: Clean up temp launchers after a delay (optional — doesn't block)
ping -n 30 127.0.0.1 > nul
del "%TMP_BACK%"  2>nul
del "%TMP_FRONT%" 2>nul
endlocal
