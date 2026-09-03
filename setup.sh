#!/usr/bin/env bash
set -e

echo "=========================================="
echo "       🚀 systatus Quick Setup            "
echo "=========================================="

# 1. Verify Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed. Please install Python 3.10+."
    exit 1
fi

# 2. Verify Node.js & npm
if ! command -v npm &> /dev/null; then
    echo "❌ npm is required but not installed. Please install Node.js 18+ and npm."
    exit 1
fi

# 3. Environment configuration (.env)
echo "⚙️  [1/3] Preparing environment configuration..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "   ✅ Created .env from .env.example"
    else
        echo "   ⚠️  .env.example not found, skipping .env creation."
    fi
else
    echo "   ℹ️  Existing .env detected, keeping current settings."
fi

# 4. Backend Dependencies
echo "🐍 [2/3] Installing backend dependencies..."
python3 -m pip install -r requirements.txt

# 5. Frontend Dependencies
echo "⚛️  [3/3] Installing frontend dependencies in web/..."
if [ -d "web" ]; then
    (cd web && npm install)
else
    echo "❌ 'web' directory not found!"
    exit 1
fi

echo ""
echo "=========================================="
echo "  🎉 systatus is ready to run!"
echo "=========================================="
echo "👉 Start both backend and frontend with:"
echo "   python main.py"
echo "=========================================="
