@echo off
rem run-hook.cmd <hook_name>
rem Wrapper: explicitly sets MEMU_* env vars, then runs the named hook script.
rem Avoids env-inheritance race when Claude Code subprocess doesn't pick up
rem freshly-set HKCU env vars (which is what caused the 422 memorize bug
rem on 2026-05-02).
rem
rem Args:
rem   %1 = hook script basename without .py (e.g. session_start, user_prompt, stop)
rem
rem Stdin/stdout pass through to the Python hook script unchanged.

setlocal
set "MEMU_SERVER_URL=http://localhost:8000"
set "MEMU_USER_ID=willie"
set "MEMU_AGENT_ID=claude-code-rei"

set "VENV_PY=G:\projects\grimmjoww-memu-mcp\.venv\Scripts\python.exe"
set "HOOK_DIR=G:\projects\grimmjoww-memu-mcp\hooks"

if "%~1"=="" (
  echo run-hook.cmd: missing hook name argument >&2
  exit /b 2
)

if not exist "%HOOK_DIR%\%~1.py" (
  echo run-hook.cmd: hook script not found: %HOOK_DIR%\%~1.py >&2
  exit /b 2
)

"%VENV_PY%" "%HOOK_DIR%\%~1.py"
exit /b %ERRORLEVEL%
