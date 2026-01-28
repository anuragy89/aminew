#!/bin/bash
#
# Bot Manager Installation Script
# Run this once on your VPS to set up the bot manager service.
#
# Usage: sudo bash install.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Bot Manager Installation Script     ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configuration
MANAGER_DIR="/opt/bot-manager"
DATA_DIR="/var/lib/bot-manager"
PIDS_DIR="$DATA_DIR/pids"
ENV_FILE="/etc/bot-manager.env"
SERVICE_FILE="/etc/systemd/system/bot-manager.service"
NGINX_CONF="/etc/nginx/conf.d/bot-manager.conf"

echo -e "${YELLOW}Step 1: Creating directories...${NC}"
mkdir -p "$MANAGER_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$PIDS_DIR"
chmod 755 "$DATA_DIR"
chmod 755 "$PIDS_DIR"
echo -e "${GREEN}✓ Directories created${NC}"

echo -e "${YELLOW}Step 2: Copying manager files...${NC}"
cp "$SCRIPT_DIR/manager.py" "$MANAGER_DIR/"
cp "$SCRIPT_DIR/registry.py" "$MANAGER_DIR/"
chmod +x "$MANAGER_DIR/manager.py"
echo -e "${GREEN}✓ Files copied to $MANAGER_DIR${NC}"

echo -e "${YELLOW}Step 3: Setting up environment...${NC}"
if [ -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}Environment file already exists at $ENV_FILE${NC}"
    read -p "Do you want to keep the existing secret? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        echo "MANAGER_SECRET=$NEW_SECRET" > "$ENV_FILE"
        echo "MANAGER_PORT=6969" >> "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        echo -e "${GREEN}✓ New secret generated${NC}"
        echo -e "${YELLOW}Your MANAGER_SECRET is: $NEW_SECRET${NC}"
    fi
else
    NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "MANAGER_SECRET=$NEW_SECRET" > "$ENV_FILE"
    echo "MANAGER_PORT=6969" >> "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo -e "${GREEN}✓ Environment file created at $ENV_FILE${NC}"
    echo -e "${YELLOW}Your MANAGER_SECRET is: $NEW_SECRET${NC}"
    echo -e "${YELLOW}Save this secret! You'll need it for API calls.${NC}"
fi

echo -e "${YELLOW}Step 4: Installing Python dependencies...${NC}"
pip3 install aiohttp >/dev/null 2>&1 || pip install aiohttp >/dev/null 2>&1
echo -e "${GREEN}✓ Dependencies installed${NC}"

echo -e "${YELLOW}Step 5: Creating systemd service...${NC}"
cat > "$SERVICE_FILE" << 'EOF'
[Unit]
Description=Bot Manager Service
Documentation=https://github.com/your-repo
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/bot-manager
EnvironmentFile=/etc/bot-manager.env
ExecStart=/usr/bin/python3 /opt/bot-manager/manager.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=false
ProtectSystem=false
ProtectHome=false

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bot-manager
echo -e "${GREEN}✓ Systemd service created and enabled${NC}"

echo -e "${YELLOW}Step 6: Setting up nginx...${NC}"
if command -v nginx &> /dev/null; then
    if [ ! -f "$SCRIPT_DIR/nginx.conf" ]; then
        echo -e "${RED}✗ nginx.conf not found in $SCRIPT_DIR${NC}"
        echo -e "${YELLOW}Skipping nginx setup - you can configure it manually later${NC}"
    else
        if [ -f "$NGINX_CONF" ]; then
            echo -e "${YELLOW}Nginx config already exists, backing up...${NC}"
            cp "$NGINX_CONF" "$NGINX_CONF.bak"
        fi
        
        cp "$SCRIPT_DIR/nginx.conf" "$NGINX_CONF"
    
        # Test nginx config
        if nginx -t 2>/dev/null; then
            systemctl reload nginx
            echo -e "${GREEN}✓ Nginx configured and reloaded${NC}"
        else
            if [ -f "$NGINX_CONF.bak" ]; then
                cp "$NGINX_CONF.bak" "$NGINX_CONF"
                echo -e "${YELLOW}Restored previous nginx config from backup${NC}"
            fi
            echo -e "${RED}✗ Nginx config test failed, please check $NGINX_CONF${NC}"
        fi
    fi
else
    echo -e "${YELLOW}Nginx not installed, skipping nginx setup${NC}"
    echo -e "${YELLOW}You can access the manager directly on port 6969${NC}"
fi

echo -e "${YELLOW}Step 7: Starting bot manager service...${NC}"
systemctl start bot-manager
sleep 2

if systemctl is-active --quiet bot-manager; then
    echo -e "${GREEN}✓ Bot manager service started successfully${NC}"
else
    echo -e "${RED}✗ Failed to start bot manager service${NC}"
    echo "Check logs with: journalctl -u bot-manager -f"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Installation Complete!              ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Manager is running on port 6969"
echo ""
echo "Your MANAGER_SECRET is stored in: $ENV_FILE"
echo ""
echo "API Endpoints:"
echo "  GET  /health              - Health check (no auth)"
echo "  GET  /bots                - List all bots"
echo "  POST /bots                - Register a bot"
echo "  GET  /bots/{id}/status    - Get bot status"
echo "  POST /bots/{id}/restart   - Force restart bot"
echo "  POST /bots/{id}/stop      - Force stop bot"
echo "  POST /bots/{id}/start     - Start stopped bot"
echo ""
echo "All endpoints except /health require X-Manager-Secret header"
echo ""
echo "Example restart command:"
echo "  curl -X POST http://localhost:6969/bots/mybot/restart \\"
echo "       -H 'X-Manager-Secret: YOUR_SECRET'"
echo ""
echo "To view logs: journalctl -u bot-manager -f"
echo ""
