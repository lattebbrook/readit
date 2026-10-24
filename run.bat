@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "READIT_BACKEND=%CD%\backend"
set "READIT_FRONTEND=%CD%\frontend"
set "READIT_VENV_PYTHON=%READIT_BACKEND%\.venv\Scripts\python.exe"

rem Keep the window open on failure when this script was double-clicked from
rem Explorer, otherwise the error scrolls past as the console closes.
set "READIT_PAUSE_ON_ERROR="
echo %cmdcmdline% | find /i "%~nx0" >nul 2>nul && set "READIT_PAUSE_ON_ERROR=1"

where npm >nul 2>nul
if errorlevel 1 (
  echo Error: Node.js and npm are required but npm was not found in PATH.
  goto :fail
)

if exist "%READIT_VENV_PYTHON%" goto :venv_ready

rem Resolve the bootstrap interpreter at the top level, not inside a
rem parenthesised block: cmd expands %VAR% for a whole block when it parses the
rem block, so a variable set inside a block reads back empty within that same
rem block.
set "BOOTSTRAP_PYTHON="
where py >nul 2>nul
if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -3"
if not defined BOOTSTRAP_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"
)
if not defined BOOTSTRAP_PYTHON (
  echo Error: Python 3 is required but neither py nor python was found in PATH.
  goto :fail
)

echo Creating the backend virtual environment...
%BOOTSTRAP_PYTHON% -m venv "%READIT_BACKEND%\.venv"
if errorlevel 1 goto :fail

if not exist "%READIT_VENV_PYTHON%" (
  echo Error: "%READIT_BACKEND%\.venv" exists but "%READIT_VENV_PYTHON%" is missing.
  echo Delete that folder and run this script again.
  goto :fail
)

:venv_ready

"%READIT_VENV_PYTHON%" -c "import fastapi, uvicorn, httpx, pydantic" >nul 2>nul
if errorlevel 1 (
  echo Installing backend dependencies...
  "%READIT_VENV_PYTHON%" -m pip install -r "%READIT_BACKEND%\requirements.txt"
  if errorlevel 1 goto :fail
)

rem Test for the launcher that "npm run dev" actually needs rather than for
rem node_modules alone: a node_modules copied from macOS/Linux arrives without
rem the .bin shims, which leaves "npm run dev" failing with "'vite' is not
rem recognized" while the directory-only check happily skips the install.
if not exist "%READIT_FRONTEND%\node_modules\.bin\vite.cmd" (
  echo Installing frontend dependencies...
  pushd "%READIT_FRONTEND%"
  call npm install
  if errorlevel 1 (
    popd
    goto :fail
  )
  popd
)

if not exist "%READIT_FRONTEND%\node_modules\.bin\vite.cmd" (
  echo Error: npm install finished but "%READIT_FRONTEND%\node_modules\.bin\vite.cmd" is missing.
  echo Delete the frontend\node_modules folder and run this script again.
  goto :fail
)

echo.
echo ReadIt is starting:
echo   App:     http://localhost:5173
echo   Backend: http://localhost:8000
echo Press Ctrl+C to stop both processes.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; $exitCode = 0; $backend = $null; $frontend = $null;" ^
  "try { $backend = Start-Process -FilePath $env:READIT_VENV_PYTHON -ArgumentList @('-m','uvicorn','app.main:app','--reload','--port','8000') -WorkingDirectory $env:READIT_BACKEND -NoNewWindow -PassThru; $frontend = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run','dev') -WorkingDirectory $env:READIT_FRONTEND -NoNewWindow -PassThru; while (-not $backend.HasExited -and -not $frontend.HasExited) { Start-Sleep -Milliseconds 500 }; if ($backend.HasExited) { $exitCode = $backend.ExitCode } else { $exitCode = $frontend.ExitCode } } finally { @($backend, $frontend) | Where-Object { $_ -and -not $_.HasExited } | ForEach-Object { taskkill.exe /PID $_.Id /T /F | Out-Null } }; exit $exitCode"

set "EXIT_CODE=%ERRORLEVEL%"
goto :done

:fail
set "EXIT_CODE=1"

:done
if not "%EXIT_CODE%"=="0" (
  if defined READIT_PAUSE_ON_ERROR pause
)
endlocal & exit /b %EXIT_CODE%
