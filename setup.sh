#!/bin/bash
# Quick Start Script for YouTube Product Analysis Service

set -e

echo "🚀 YouTube Product Analysis Service - Quick Start"
echo "=================================================="
echo ""

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Please create it with:"
    echo "   DATABASE_URL=postgresql://user:password@localhost:5432/techdb"
    echo "   YOUTUBE_API_KEY=your_api_key_here"
    exit 1
fi

echo "✓ .env file found"

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
pip install -q -r requirements.txt
echo "✓ Dependencies installed"

# Create templates directory
mkdir -p templates
echo "✓ Templates directory ready"

echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Ensure PostgreSQL is running"
echo "   2. Update .env with your DATABASE_URL and YOUTUBE_API_KEY"
echo "   3. Run: python main_youtube_analysis.py"
echo "   4. Open: http://localhost:8000"
echo ""
echo "📖 For more info, see README_YOUTUBE_SERVICE.md"
