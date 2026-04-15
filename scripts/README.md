# Scripts — Bot Manager & Registration

A standalone HTTP service for managing multiple music bot instances on a single VPS. The bot manager runs independently of bot processes, allowing you to start, stop, restart, register, and unregister bots remotely via a REST API.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Directory Structure](#directory-structure)
- [Prerequisites](#prerequisites)
- [Installation (One-Time Setup)](#installation-one-time-setup)
- [Registering a Bot](#registering-a-bot)
- [Unregistering / Removing a Bot](#unregistering--removing-a-bot)
- [API Reference](#api-reference)
  - [Health Check](#1-health-check)
  - [List All Bots](#2-list-all-bots)
  - [Register a Bot](#3-register-a-bot)
  - [Get Bot Status](#4-get-bot-status)
  - [Start a Bot](#5-start-a-bot)
  - [Stop a Bot](#6-stop-a-bot)
  - [Restart a Bot](#7-restart-a-bot)
  - [Unregister a Bot](#8-unregister-a-bot-delete)
- [Nginx (Optional Reverse Proxy)](#nginx-optional-reverse-proxy)
- [Logs & Debugging](#logs--debugging)
- [File Locations Reference](#file-locations-reference)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                        VPS                           │
│                                                      │
│   ┌─────────────────┐     ┌──────────────────────┐   │
│   │   Bot Manager   │────▶│  /var/lib/bot-manager │   │
│   │  (port 6969)    │     │  ├── bots.json        │   │
│   │  aiohttp server │     │  └── pids/            │   │
│   └────────┬────────┘     └──────────────────────┘   │
│            │                                         │
│   ┌────────┴────────────────────────┐                │
│   │            │                    │                │
│   ▼            ▼                    ▼                │
│ ┌──────┐  ┌──────┐           ┌──────┐               │
│ │ Bot1 │  │ Bot2 │    ...    │ BotN │               │
│ └──────┘  └──────┘           └──────┘               │
│                                                      │
│   ┌─────────────┐ (optional)                         │
│   │   Nginx     │──▶ reverse proxy to :6969          │
│   │  (port 80)  │                                    │
│   └─────────────┘                                    │
└──────────────────────────────────────────────────────┘
```

- **Bot Manager** — A Python `aiohttp` server that runs as a systemd service. It manages bot lifecycle (start/stop/restart) and maintains a JSON registry of all bots.
- **Registry** (`bots.json`) — Stores each bot's ID, working directory, start command, and PID file path. Uses file locking for safe concurrent access.
- **PID files** — Each running bot gets a `.pid` file in `/var/lib/bot-manager/pids/` so the manager can track and kill processes.

---

## Directory Structure

```
scripts/
├── register_bot.sh              # Per-bot registration script
└── bot_manager/
    ├── install.sh               # One-time VPS installation script
    ├── manager.py               # Main HTTP server (aiohttp)
    ├── registry.py              # Bot registry module (JSON + file locking)
    ├── bot-manager.service      # Systemd unit file
    └── nginx.conf               # Optional Nginx reverse proxy config
```

---

## Prerequisites

- **Linux VPS** (Ubuntu/Debian recommended)
- **Python 3.10+** with `aiohttp` package
- **Root/sudo access** (for systemd service and `/var/lib/` directories)
- **Nginx** (optional, for reverse proxy)
- Each bot must have a `BOT_ID` set in its `.env` file

---

## Installation (One-Time Setup)

Run this **once** on your VPS to install the bot manager service:

```bash
# 1. Clone the repo (if not already done)
git clone https://github.com/sparrow9616/music_bot.git
cd music_bot

# 2. Run the installer as root
sudo bash scripts/bot_manager/install.sh
```

### What the installer does (step by step):

| Step | Action |
|------|--------|
| 1 | Creates directories: `/opt/bot-manager`, `/var/lib/bot-manager`, `/var/lib/bot-manager/pids` |
| 2 | Copies `manager.py` and `registry.py` to `/opt/bot-manager/` |
| 3 | Generates a `MANAGER_SECRET` token and saves it to `/etc/bot-manager.env` |
| 4 | Installs the `aiohttp` Python dependency |
| 5 | Creates and enables the `bot-manager` systemd service |
| 6 | Sets up Nginx reverse proxy (if Nginx is installed) |
| 7 | Starts the bot manager service |

> **Important:** Save the `MANAGER_SECRET` printed at the end — you need it for all API calls.

### Verify installation:

```bash
# Check service status
systemctl status bot-manager

# Test health endpoint
curl http://localhost:6969/health
```

Expected response:
```json
{
  "status": "alive",
  "service": "bot-manager",
  "timestamp": "2026-04-15T12:00:00.000000"
}
```

---

## Registering a Bot

Each bot instance needs to be registered with the manager so it can be controlled remotely.

### Step 1: Set `BOT_ID` in the bot's `.env` file

```env
BOT_ID=mybot1
```

### Step 2: Run the registration script from the bot's root directory

```bash
cd /path/to/bot/directory
bash scripts/register_bot.sh
```

### How registration works:

1. The script reads `BOT_ID` from the `.env` file in the current directory.
2. **If the manager is running** — it registers via the API (`POST /bots`) using the `MANAGER_SECRET`.
3. **If the manager is not running** — it writes directly to `/var/lib/bot-manager/bots.json` (requires sudo).
4. The script is **idempotent** — safe to run multiple times; it updates existing entries.

### Verify registration:

```bash
# Check the registry file directly
cat /var/lib/bot-manager/bots.json

# Or query the API
curl -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots
```

### Optional environment variables for registration:

| Variable | Default | Description |
|----------|---------|-------------|
| `BOT_ID` | *(required)* | Unique identifier for the bot |
| `MANAGER_URL` | `http://localhost:6969` | URL of the bot manager |
| `MANAGER_SECRET` | Read from `/etc/bot-manager.env` | Auth token |
| `START_COMMAND` | `bash start` | Command used to start the bot |

---

## Unregistering / Removing a Bot

There are **two methods** to unregister (remove) a bot from the manager:

### Method 1: Via API (Recommended)

Send a `DELETE` request to the manager:

```bash
# Stop the bot first (optional but recommended)
curl -X POST http://localhost:6969/bots/mybot1/stop \
     -H "X-Manager-Secret: YOUR_SECRET"

# Unregister the bot
curl -X DELETE http://localhost:6969/bots/mybot1 \
     -H "X-Manager-Secret: YOUR_SECRET"
```

**Response (success):**
```json
{
  "success": true,
  "message": "Bot 'mybot1' unregistered"
}
```

**Response (not found):**
```json
{
  "success": false,
  "error": "Bot 'mybot1' not found"
}
```

### Method 2: Direct file edit (if manager is down)

```bash
# 1. Stop the bot process manually
kill -9 $(cat /var/lib/bot-manager/pids/mybot1.pid)

# 2. Remove the PID file
sudo rm -f /var/lib/bot-manager/pids/mybot1.pid

# 3. Edit the registry to remove the bot entry
sudo python3 -c "
import json
with open('/var/lib/bot-manager/bots.json', 'r+') as f:
    data = json.load(f)
    data['bots'].pop('mybot1', None)
    f.seek(0)
    f.truncate()
    json.dump(data, f, indent=2)
print('Bot removed from registry')
"
```

### Full cleanup checklist:

- [x] Stop the bot process (`POST /bots/{id}/stop` or `kill -9`)
- [x] Unregister from manager (`DELETE /bots/{id}` or edit `bots.json`)
- [x] Remove PID file (`/var/lib/bot-manager/pids/{id}.pid`) — done automatically by API
- [ ] *(Optional)* Delete the bot's directory from disk

---

## API Reference

**Base URL:** `http://localhost:6969` (direct) or `http://your-server/api` (via Nginx)

**Authentication:** All endpoints except `/health` require the `X-Manager-Secret` header.

```
X-Manager-Secret: YOUR_SECRET_TOKEN
```

---

### 1. Health Check

Check if the bot manager is running. **No authentication required.**

```
GET /health
```

**Response:**
```json
{
  "status": "alive",
  "service": "bot-manager",
  "timestamp": "2026-04-15T12:00:00.000000"
}
```

**curl example:**
```bash
curl http://localhost:6969/health
```

---

### 2. List All Bots

Get all registered bots with their current status.

```
GET /bots
```

**Response:**
```json
{
  "success": true,
  "bots": {
    "mybot1": {
      "bot_id": "mybot1",
      "running": true,
      "pid": 12345,
      "uptime_seconds": 3600.5,
      "working_dir": "/home/user/bots/mybot1"
    },
    "mybot2": {
      "bot_id": "mybot2",
      "running": false,
      "pid": null,
      "uptime_seconds": null,
      "working_dir": "/home/user/bots/mybot2"
    }
  }
}
```

**curl example:**
```bash
curl -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots
```

---

### 3. Register a Bot

Add a new bot to the manager or update an existing one.

```
POST /bots
Content-Type: application/json
```

**Request body:**
```json
{
  "bot_id": "mybot1",
  "working_dir": "/home/user/bots/mybot1",
  "start_command": "bash start"
}
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `bot_id` | Yes | — | Unique identifier for the bot |
| `working_dir` | Yes | — | Absolute path to the bot's root directory |
| `start_command` | No | `bash start` | Shell command to start the bot |

**Response:**
```json
{
  "success": true,
  "message": "Bot 'mybot1' registered",
  "bot_id": "mybot1"
}
```

**curl example:**
```bash
curl -X POST http://localhost:6969/bots \
     -H "Content-Type: application/json" \
     -H "X-Manager-Secret: YOUR_SECRET" \
     -d '{"bot_id": "mybot1", "working_dir": "/home/user/bots/mybot1"}'
```

---

### 4. Get Bot Status

Get detailed status of a specific bot.

```
GET /bots/{bot_id}
GET /bots/{bot_id}/status
```

**Response:**
```json
{
  "success": true,
  "bot_id": "mybot1",
  "running": true,
  "pid": 12345,
  "uptime_seconds": 7200.0,
  "working_dir": "/home/user/bots/mybot1",
  "start_command": "bash start"
}
```

**curl example:**
```bash
curl -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots/mybot1
```

---

### 5. Start a Bot

Start a bot that is currently stopped.

```
POST /bots/{bot_id}/start
```

**Response (started):**
```json
{
  "success": true,
  "message": "Bot 'mybot1' started",
  "pid": 12345
}
```

**Response (already running):**
```json
{
  "success": true,
  "message": "Bot 'mybot1' is already running",
  "pid": 12345,
  "already_running": true
}
```

**curl example:**
```bash
curl -X POST -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots/mybot1/start
```

---

### 6. Stop a Bot

Force stop a bot (sends `SIGKILL` to the process and its children).

```
POST /bots/{bot_id}/stop
```

**Response:**
```json
{
  "success": true,
  "message": "Bot 'mybot1' stopped",
  "previous_pid": 12345
}
```

**curl example:**
```bash
curl -X POST -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots/mybot1/stop
```

---

### 7. Restart a Bot

Force restart: kills the running process (`SIGKILL`) and starts it again.

```
POST /bots/{bot_id}/restart
```

**Response:**
```json
{
  "success": true,
  "message": "Bot 'mybot1' restarted successfully",
  "pid": 12346,
  "killed": true,
  "started": true
}
```

**curl example:**
```bash
curl -X POST -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots/mybot1/restart
```

---

### 8. Unregister a Bot (DELETE)

Remove a bot from the registry. **This does NOT stop the bot process** — stop it first if needed.

```
DELETE /bots/{bot_id}
```

**Response (success):**
```json
{
  "success": true,
  "message": "Bot 'mybot1' unregistered"
}
```

**Response (not found):**
```json
{
  "success": false,
  "error": "Bot 'mybot1' not found"
}
```

**curl example:**
```bash
# Stop first, then unregister
curl -X POST -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots/mybot1/stop
curl -X DELETE -H "X-Manager-Secret: YOUR_SECRET" http://localhost:6969/bots/mybot1
```

---

### API Error Responses

All error responses follow the same format:

```json
{
  "success": false,
  "error": "Error description here"
}
```

| HTTP Status | Meaning |
|-------------|---------|
| `200` | Success |
| `400` | Bad request (missing fields, invalid JSON) |
| `401` | Unauthorized (missing or wrong `X-Manager-Secret`) |
| `404` | Bot not found |
| `500` | Internal server error (failed to kill/start process) |

---

## Nginx (Optional Reverse Proxy)

If Nginx is installed, the installer sets up a reverse proxy that maps:

| Nginx Path | Manager Path | Description |
|------------|--------------|-------------|
| `/api/bots` | `/bots` | All bot API endpoints |
| `/api/health` | `/health` | Health check |
| `/manager/` | `/` | Direct pass-through (alternative) |

This lets you expose the API on port 80/443 instead of 6969.

### Enable HTTPS (recommended for production)

Edit `/etc/nginx/conf.d/bot-manager.conf` and uncomment the SSL lines:

```nginx
listen 443 ssl;
ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
```

> **Warning:** Without HTTPS, the `X-Manager-Secret` header is sent in plaintext over the network.

---

## Logs & Debugging

```bash
# View bot manager service logs (live)
journalctl -u bot-manager -f

# View bot manager service logs (last 100 lines)
journalctl -u bot-manager -n 100

# Check bot's startup log (created by manager when starting a bot)
cat /path/to/bot/directory/manager_start.log

# View registry contents
cat /var/lib/bot-manager/bots.json

# Check if a bot's PID file exists
ls -la /var/lib/bot-manager/pids/

# Restart the manager service itself
sudo systemctl restart bot-manager
```

---

## File Locations Reference

| File | Path | Description |
|------|------|-------------|
| Manager code | `/opt/bot-manager/manager.py` | Main server (copied by installer) |
| Registry module | `/opt/bot-manager/registry.py` | Bot registry logic |
| Bot registry | `/var/lib/bot-manager/bots.json` | JSON file with all registered bots |
| PID files | `/var/lib/bot-manager/pids/{bot_id}.pid` | One per running bot |
| Manager secret | `/etc/bot-manager.env` | Contains `MANAGER_SECRET` and `MANAGER_PORT` |
| Systemd service | `/etc/systemd/system/bot-manager.service` | Service unit file |
| Nginx config | `/etc/nginx/conf.d/bot-manager.conf` | Reverse proxy config |
| Bot startup log | `{bot_working_dir}/manager_start.log` | Per-bot log from manager starts |
