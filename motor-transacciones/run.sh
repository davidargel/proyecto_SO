#!/usr/bin/env bash
# Crea el entorno virtual (la primera vez), instala dependencias y arranca el motor.
set -e
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo "Creando entorno virtual .venv ..."
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt
fi
exec ./.venv/bin/python app.py "$@"
