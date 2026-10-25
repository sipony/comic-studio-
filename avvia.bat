@echo off
chcp 65001 >nul
title Comic Studio
cd /d "%~dp0"

rem Cerca Python 3.13, 3.12, 3.11 o 3.10 (launcher "py" di Windows), poi "python"
set "PY="
for %%V in (3.13 3.12 3.11 3.10) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo  Python 3.10 o piu' recente non trovato.
  echo  Installalo da https://www.python.org/downloads/ spuntando "Add python.exe to PATH", poi rilancia.
  echo.
  pause
  exit /b 1
)

%PY% avvio.py %*
if errorlevel 1 pause
