#!/bin/bash
# Quick start script for Convergence

set -e

echo "╔═══════════════════════════════════════════════════════╗"
echo "║         Convergence Quick Start Setup                 ║"
echo "║   AI-Driven Network Observability and Automation      ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed"
    echo "Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: Docker Compose is not installed"
    echo "Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose detected"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1-2)
echo "✅ Python $PYTHON_VERSION detected"
echo ""

# Setup .env file
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env file with your API keys before starting services"
    echo ""
    read -p "Press Enter to continue after editing .env, or Ctrl+C to exit..."
else
    echo "✅ .env file already exists"
fi
echo ""

# Start infrastructure
echo "🚀 Starting infrastructure services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to become healthy..."
sleep 5

# Check service health
echo ""
echo "📊 Service Status:"
docker-compose ps
echo ""

# Setup agent
echo "🤖 Setting up AI agent..."
cd agent
if [ ! -d "venv" ]; then
    ./setup.sh
else
    echo "✅ Virtual environment already exists"
fi
cd ..

echo ""
echo "╔═══════════════════════════════════════════════════════╗"
echo "║              Setup Complete! 🎉                       ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "Services are running at:"
echo "  • Nautobot:        http://localhost:8000 (admin/admin)"
echo "  • Grafana:         http://localhost:3000 (admin/admin)"
echo "  • VictoriaMetrics: http://localhost:8428"
echo ""
echo "To use the AI agent:"
echo "  cd agent"
echo "  source venv/bin/activate"
echo "  python -m agent.main --help"
echo ""
echo "Example commands:"
echo "  python -m agent.main discover 192.168.1.1 --device-type cisco_ios"
echo "  python -m agent.main query 'List all devices in Nautobot'"
echo ""
echo "To stop services:"
echo "  docker-compose down"
echo ""
echo "For more information, see README.md"
echo ""
