#!/bin/bash
#
# Register Bot Script
# Run this in each bot's directory to register it with the bot manager.
# Safe to run multiple times - will update existing entry.
#
# Usage: bash scripts/register_bot.sh
#
# Prerequisites:
#   - BOT_ID must be set in .env file
#   - Bot manager must be installed and running
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Bot Registration Script             ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Get the bot's working directory (where this script is called from or parent of scripts/)
if [ -f ".env" ]; then
    WORKING_DIR="$(pwd)"
elif [ -f "../.env" ]; then
    WORKING_DIR="$(cd .. && pwd)"
else
    echo -e "${RED}Error: .env file not found${NC}"
    echo "Please run this script from the bot's root directory"
    exit 1
fi

# Load .env file
set -a
source "$WORKING_DIR/.env"
set +a

# Check BOT_ID
if [ -z "$BOT_ID" ]; then
    echo -e "${RED}Error: BOT_ID is not set in .env${NC}"
    echo ""
    echo "Add BOT_ID to your .env file:"
    echo "  BOT_ID=mybot1"
    echo ""
    exit 1
fi

echo "Bot ID: $BOT_ID"
echo "Working Directory: $WORKING_DIR"
echo ""

# Configuration
MANAGER_URL="${MANAGER_URL:-http://localhost:6969}"
ENV_FILE="/etc/bot-manager.env"
REGISTRY_FILE="/var/lib/bot-manager/bots.json"
START_COMMAND="${START_COMMAND:-bash start}"

# Try to get MANAGER_SECRET from environment or config file
if [ -z "$MANAGER_SECRET" ] && [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

# Method 1: Use API if manager is running
if curl -s "$MANAGER_URL/health" > /dev/null 2>&1; then
    echo -e "${YELLOW}Registering via API...${NC}"
    
    if [ -z "$MANAGER_SECRET" ]; then
        echo -e "${RED}Error: MANAGER_SECRET not found${NC}"
        echo "Set MANAGER_SECRET environment variable or ensure /etc/bot-manager.env exists"
        exit 1
    fi
    
    # Use Python to safely create JSON (prevents injection)
    JSON_PAYLOAD=$(python3 -c "
import json
import sys
print(json.dumps({
    'bot_id': sys.argv[1],
    'working_dir': sys.argv[2],
    'start_command': sys.argv[3]
}))
" "$BOT_ID" "$WORKING_DIR" "$START_COMMAND")
    
    RESPONSE=$(curl -s -X POST "$MANAGER_URL/bots" \
        -H "Content-Type: application/json" \
        -H "X-Manager-Secret: $MANAGER_SECRET" \
        -d "$JSON_PAYLOAD")
    
    if echo "$RESPONSE" | grep -q '"success": true'; then
        echo -e "${GREEN}✓ Bot '$BOT_ID' registered successfully via API${NC}"
    else
        echo -e "${RED}✗ API registration failed: $RESPONSE${NC}"
        exit 1
    fi
else
    # Method 2: Direct file manipulation if manager not running
    echo -e "${YELLOW}Manager not running, registering directly to file...${NC}"
    
    # Check if we have write access
    if [ ! -d "/var/lib/bot-manager" ]; then
        echo -e "${YELLOW}Creating bot-manager directories (requires sudo)...${NC}"
        sudo mkdir -p /var/lib/bot-manager/pids
        sudo chmod 755 /var/lib/bot-manager
        sudo chmod 755 /var/lib/bot-manager/pids
    fi
    
    # Initialize registry file if it doesn't exist
    if [ ! -f "$REGISTRY_FILE" ]; then
        echo '{"bots": {}}' | sudo tee "$REGISTRY_FILE" > /dev/null
    fi
    
    # Use Python to safely update the JSON (handles concurrent access better)
    # Pass variables as arguments to avoid shell injection
    sudo python3 - "$REGISTRY_FILE" "$BOT_ID" "$WORKING_DIR" "$START_COMMAND" << 'PYEOF'
import json
import fcntl
import sys

registry_file = sys.argv[1]
bot_id = sys.argv[2]
working_dir = sys.argv[3]
start_command = sys.argv[4]

bot_data = {
    "bot_id": bot_id,
    "working_dir": working_dir,
    "start_command": start_command,
    "pid_file": f"/var/lib/bot-manager/pids/{bot_id}.pid"
}

with open(registry_file, "r+") as f:
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    try:
        data = json.load(f)
        if "bots" not in data:
            data["bots"] = {}
        data["bots"][bot_id] = bot_data
        f.seek(0)
        f.truncate()
        json.dump(data, f, indent=2)
        print("Bot registered successfully")
    finally:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
PYEOF
    
    echo -e "${GREEN}✓ Bot '$BOT_ID' registered directly to registry${NC}"
fi

echo ""
echo -e "${GREEN}Registration complete!${NC}"
echo ""
echo "To verify registration:"
echo "  cat /var/lib/bot-manager/bots.json"
echo ""
echo "To restart this bot via API:"
echo "  curl -X POST http://your-server/api/bots/$BOT_ID/restart \\"
echo "       -H 'X-Manager-Secret: YOUR_SECRET'"
echo ""
