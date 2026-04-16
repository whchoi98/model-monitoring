#!/usr/bin/env bash
# Project setup script for new developers
set -euo pipefail

echo "=== Bedrock LLM Monitor — Setup ==="
echo ""

# Check prerequisites
echo "Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: node not found"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm not found"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found"; exit 1; }
echo "All prerequisites met."
echo ""

# Start PostgreSQL
echo "Starting PostgreSQL..."
docker compose up -d
sleep 2
docker exec monitoring-postgres pg_isready -U postgres || { echo "ERROR: PostgreSQL not ready"; exit 1; }
echo "PostgreSQL is ready."
echo ""

# Backend setup
echo "Setting up backend..."
cd backend
if [ ! -f .env ]; then
  echo "Creating .env from .env.example..."
  cp ../.env.example .env
  echo "IMPORTANT: Edit backend/.env with your actual values before starting!"
fi
pip install -r requirements.txt
cd ..
echo "Backend dependencies installed."
echo ""

# Frontend setup
echo "Setting up frontend..."
cd frontend
npm install
cd ..
echo "Frontend dependencies installed."
echo ""

# Install git hooks
if [ -f scripts/install-hooks.sh ]; then
  bash scripts/install-hooks.sh
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To start development:"
echo "  Backend:  cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000"
echo "  Frontend: cd frontend && npm run dev"
echo "  Dashboard: http://localhost:3000"
