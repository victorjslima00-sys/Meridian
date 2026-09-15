#!/usr/bin/env bash
set -euo pipefail

echo "=== Meridian Developer Bootstrap (Linux/macOS) ==="

EXPECTED_PYTHON="3.12"
ACTUAL_PYTHON=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "not_found")

if [ "$ACTUAL_PYTHON" != "$EXPECTED_PYTHON" ]; then
    echo "⚠️ Warning: Expected Python $EXPECTED_PYTHON, found $ACTUAL_PYTHON. Recommended to use pyenv."
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv..."
    python3 -m venv .venv
fi

echo "Activating virtualenv..."
# shellcheck source=/dev/null
source .venv/bin/activate

echo "Upgrading pip to pinned version..."
python -m pip install pip==25.0.1

if [ -f "requirements-dev.lock" ]; then
    echo "Installing development dependencies from requirements-dev.lock..."
    pip install -r requirements-dev.lock
elif [ -f "requirements.lock" ]; then
    echo "Installing locked Python dependencies from requirements.lock..."
    pip install -r requirements.lock
else
    echo "Installing development dependencies from requirements-dev.txt..."
    pip install -r requirements-dev.txt
fi

echo "Bootstrapping frontend..."
cd frontend
if command -v nvm &> /dev/null; then
    nvm use
fi
npm ci
cd ..

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "Copying .env.example to .env..."
    cp .env.example .env
    echo "⚠️ Please fill in secret keys in .env before launching the API."
fi

echo "Running pre-flight test verification..."
pytest tests/ --collect-only -q
cd frontend && npm run lint && cd ..

echo "✅ Meridian Bootstrap complete!"
