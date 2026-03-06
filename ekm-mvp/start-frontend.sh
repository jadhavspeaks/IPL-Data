#!/bin/bash
# ─── EKM Frontend — Local Setup & Run ────────────────────────────────────────
set -e

cd "$(dirname "$0")/frontend"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   EKM Frontend — Local Setup         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. Check Node ─────────────────────────────────────────────────────────────
if ! command -v node &> /dev/null; then
  echo "✗ Node.js not found. Install from https://nodejs.org (v18+)"
  exit 1
fi
echo "✓ Using $(node --version)"

# ── 2. Install npm packages ───────────────────────────────────────────────────
if [ ! -d "node_modules" ]; then
  echo "→ Installing npm packages..."
  npm install
else
  echo "✓ node_modules already installed"
fi

# ── 3. Start dev server ───────────────────────────────────────────────────────
echo ""
echo "→ Starting frontend on http://localhost:3000"
echo "   (API calls proxied to http://localhost:8000)"
echo ""
npm run dev
