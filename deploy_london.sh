#!/usr/bin/env bash
# ==============================================================================
# AgentQuant — London LD4 Low-Latency Deployment Script
# ==============================================================================
# Deploys the autonomous sniper engine close to cTrader's Equinix LD4 London matching engine.
# Run on Ubuntu/Debian London VPS (Hetzner Falkenstein/Frankfurt, AWS eu-west-2, DigitalOcean LON1).

set -e

echo "🚀 [AGENTQUANT] Initializing London LD4 Sniper Deployment..."

# 1. Check Latency to cTrader MCP
echo "📡 Checking ping latency to mcp.ctrader.com..."
ping -c 4 mcp.ctrader.com || true

# 2. Check Docker availability
if ! command -v docker &> /dev/null; then
    echo "⚠️ Docker not found. Installing Docker & Docker Compose..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
fi

# 3. Create required runtime directories
mkdir -p cache results data_store

# 4. Build and run London sniper container
echo "🏗️ Building and starting AgentQuant London Sniper container..."
docker compose -f docker-compose.london.yml down || true
docker compose -f docker-compose.london.yml build --pull
docker compose -f docker-compose.london.yml up -d

echo "✅ [SUCCESS] AgentQuant London Sniper is running!"
docker ps --filter "name=agentquant_london_daemon"
echo "📜 View live logs anytime with: docker compose -f docker-compose.london.yml logs -f"
