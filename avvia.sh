#!/usr/bin/env bash
# Avvio di Comic Studio su Linux e macOS.
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"
    break
  fi
done

if [ -z "$PY" ]; then
  echo
  echo "Python 3.10 o più recente non trovato."
  echo "  Linux: installa python3 e python3-venv con il gestore pacchetti (es. sudo apt install python3 python3-venv)"
  echo "  macOS: scaricalo da https://www.python.org/downloads/ oppure: brew install python@3.12"
  exit 1
fi

if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
  echo "Manca il modulo venv di Python. Su Debian/Ubuntu: sudo apt install python3-venv"
  exit 1
fi

exec "$PY" avvio.py "$@"
