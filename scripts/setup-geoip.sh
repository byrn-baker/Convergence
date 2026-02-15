#!/bin/bash
# GeoIP Setup Script for Grafana
# Downloads MaxMind GeoLite2 database for geographic IP visualization

set -e

echo "🌍 GeoIP Setup for pfSense Security Dashboard"
echo "=============================================="
echo ""

# Load environment variables from .env file
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Check if license key is provided (command line or .env)
if [ -n "$1" ]; then
    LICENSE_KEY="$1"
elif [ -n "$MAXMIND_LICENSE_KEY" ] && [ "$MAXMIND_LICENSE_KEY" != "your_license_key_here" ]; then
    LICENSE_KEY="$MAXMIND_LICENSE_KEY"
    echo "✅ Using MaxMind license key from .env file"
else
    echo "❌ Error: MaxMind license key required"
    echo ""
    echo "Option 1: Configure in .env file"
    echo "  Edit .env and set:"
    echo "    MAXMIND_ACCOUNT_ID=your_account_id"
    echo "    MAXMIND_LICENSE_KEY=your_license_key"
    echo "  Then run: ./scripts/setup-geoip.sh"
    echo ""
    echo "Option 2: Pass as command-line argument"
    echo "  ./scripts/setup-geoip.sh YOUR_LICENSE_KEY"
    echo ""
    echo "Get your FREE license key at:"
    echo "  https://www.maxmind.com/en/geolite2/signup"
    echo ""
    exit 1
fi

LICENSE_KEY="$LICENSE_KEY"
GEOIP_DIR="./data/geoip"

echo "📁 Creating GeoIP directory..."
mkdir -p "$GEOIP_DIR"

echo "⬇️  Downloading GeoLite2-City database..."
wget -q --show-progress -O "$GEOIP_DIR/GeoLite2-City.tar.gz" \
  "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=${LICENSE_KEY}&suffix=tar.gz"

if [ $? -ne 0 ]; then
    echo "❌ Download failed. Please check your license key."
    exit 1
fi

echo "📦 Extracting database..."
tar -xzf "$GEOIP_DIR/GeoLite2-City.tar.gz" -C "$GEOIP_DIR/" --strip-components=1

# Remove tarball
rm "$GEOIP_DIR/GeoLite2-City.tar.gz"

echo "✅ GeoIP database installed!"
echo ""
echo "📊 Next steps:"
echo "  1. Restart Grafana: docker-compose restart grafana"
echo "  2. Open dashboard: http://localhost:3000/d/pfsense-firewall-security"
echo "  3. View the '🌍 WAN Threats' panel"
echo ""
echo "💡 Tip: The map will only show public IPs blocked on your WAN interface (igc0.201)"
echo "   Private IPs (192.168.x.x) will not appear as they have no geographic location."
echo ""
