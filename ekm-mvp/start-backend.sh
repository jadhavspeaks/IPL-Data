#!/bin/bash
# ─── EKM Backend — Conda Setup & Run ─────────────────────────────────────────
set -e

cd "$(dirname "$0")/backend"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   EKM Backend — Conda Setup          ║"
echo "╚══════════════════════════════════════╝"
echo ""

ENV_NAME="ekm"

# ── 1. Check conda is available ───────────────────────────────────────────────
if ! command -v conda &> /dev/null; then
  echo "✗ conda not found."
  echo "  Install Miniconda: https://docs.conda.io/en/latest/miniconda.html"
  exit 1
fi
echo "✓ conda found: $(conda --version)"

# ── 2. Create conda env if it doesn't exist ───────────────────────────────────
if conda env list | grep -q "^$ENV_NAME "; then
  echo "✓ Conda env '$ENV_NAME' already exists"
else
  echo "→ Creating conda env '$ENV_NAME' with Python 3.11..."
  conda create -n "$ENV_NAME" python=3.11 -y
  echo "✓ Conda env '$ENV_NAME' created"
fi

# ── 3. Install dependencies inside the env ────────────────────────────────────
echo "→ Installing dependencies..."
conda run -n "$ENV_NAME" pip install -q --upgrade pip
conda run -n "$ENV_NAME" pip install -q -r requirements.txt
echo "✓ Dependencies installed"

# ── 4. Check .env ─────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo ""
  echo "⚠️  No .env file found in backend/"
  cp ../.env.example .env
  echo "→ Created backend/.env from template — please edit it with your credentials"
  echo "  Then re-run this script."
  exit 1
fi
echo "✓ .env found"

# ── 5. Start the API ──────────────────────────────────────────────────────────
echo ""
echo "→ Starting FastAPI on http://localhost:8000"
echo "   API docs: http://localhost:8000/docs"
echo "   Running inside conda env: $ENV_NAME"
echo ""
conda run -n "$ENV_NAME" uvicorn main:app --host 0.0.0.0 --port 8000 --reload
