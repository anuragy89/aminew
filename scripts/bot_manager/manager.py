#!/usr/bin/env python3
"""
Bot Manager Service
Standalone HTTP server for managing multiple music bots on a VPS.
Runs independently of bot processes so it can restart stalled bots.

Usage:
    python3 manager.py

Environment Variables:
    MANAGER_SECRET: Required. Secret token for API authentication.
    MANAGER_PORT: Optional. Port to run on (default: 6969).
"""

import asyncio
import os
import signal
import subprocess
import sys
from datetime import datetime
from typing import Optional

from aiohttp import web

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry

# Configuration
MANAGER_SECRET = os.getenv("MANAGER_SECRET")
MANAGER_PORT = int(os.getenv("MANAGER_PORT", 6969))

# Track bot start times for uptime calculation
bot_start_times: dict[str, datetime] = {}


def validate_secret(request) -> bool:
    """Validate the manager secret from request header"""
    secret = request.headers.get("X-Manager-Secret")
    if not MANAGER_SECRET:
        return False
    return secret == MANAGER_SECRET


def json_response(data: dict, status: int = 200):
    """Helper to create JSON response"""
    return web.json_response(data, status=status)


def error_response(message: str, status: int = 400):
    """Helper to create error response"""
    return json_response({"success": False, "error": message}, status=status)


def success_response(message: str, **extra):
    """Helper to create success response"""
    return json_response({"success": True, "message": message, **extra})


async def health_check(request):
    """Health check endpoint - no auth required"""
    return json_response({
        "status": "alive",
        "service": "bot-manager",
        "timestamp": datetime.now().isoformat()
    })


async def list_bots(request):
    """List all registered bots with their status"""
    if not validate_secret(request):
        return error_response("Unauthorized", 401)
    
    bots = registry.list_bots()
    result = {}
    
    for bot_id, config in bots.items():
        pid = registry.get_pid(bot_id)
        running = pid is not None
        uptime = None
        
        if running and bot_id in bot_start_times:
            uptime = (datetime.now() - bot_start_times[bot_id]).total_seconds()
        
        result[bot_id] = {
            "bot_id": bot_id,
            "running": running,
            "pid": pid,
            "uptime_seconds": uptime,
            "working_dir": config.get("working_dir"),
        }
    
    return json_response({"success": True, "bots": result})


async def get_bot_status(request):
    """Get status of a specific bot"""
    if not validate_secret(request):
        return error_response("Unauthorized", 401)
    
    bot_id = request.match_info.get("bot_id")
    bot = registry.get_bot(bot_id)
    
    if not bot:
        return error_response(f"Bot '{bot_id}' not found", 404)
    
    pid = registry.get_pid(bot_id)
    running = pid is not None
    uptime = None
    
    if running and bot_id in bot_start_times:
        uptime = (datetime.now() - bot_start_times[bot_id]).total_seconds()
    
    return json_response({
        "success": True,
        "bot_id": bot_id,
        "running": running,
        "pid": pid,
        "uptime_seconds": uptime,
        "working_dir": bot.get("working_dir"),
        "start_command": bot.get("start_command"),
    })


async def kill_bot_process(bot_id: str) -> tuple[bool, Optional[str]]:
    """
    Force kill a bot process.
    
    Returns:
        (success, error_message)
    """
    pid = registry.get_pid(bot_id)
    if not pid:
        return True, None  # Not running is success for kill
    
    try:
        # Force kill with SIGKILL (-9)
        os.kill(pid, signal.SIGKILL)
        # Wait a moment for process to die
        import time
        for _ in range(10):
            try:
                os.kill(pid, 0)  # Check if still alive
                time.sleep(0.1)
            except ProcessLookupError:
                break
        registry.remove_pid(bot_id)
        if bot_id in bot_start_times:
            del bot_start_times[bot_id]
        return True, None
    except ProcessLookupError:
        # Process already dead
        registry.remove_pid(bot_id)
        return True, None
    except PermissionError:
        return False, "Permission denied - manager may need to run as root or same user as bot"
    except Exception as e:
        return False, str(e)


async def start_bot_process(bot_id: str) -> tuple[bool, Optional[str], Optional[int]]:
    """
    Start a bot process.
    
    Returns:
        (success, error_message, pid)
    """
    bot = registry.get_bot(bot_id)
    if not bot:
        return False, f"Bot '{bot_id}' not found in registry", None
    
    # Check if already running
    existing_pid = registry.get_pid(bot_id)
    if existing_pid:
        return False, f"Bot is already running with PID {existing_pid}", existing_pid
    
    working_dir = bot.get("working_dir")
    start_command = bot.get("start_command", "bash start")
    
    if not os.path.exists(working_dir):
        return False, f"Working directory does not exist: {working_dir}", None
    
    try:
        # Start the bot process in background
        # We use nohup and redirect output to prevent blocking
        process = subprocess.Popen(
            start_command,
            shell=True,
            cwd=working_dir,
            start_new_session=True,  # Detach from this process
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        
        # The actual bot PID will be written by the start script
        # We record the start time
        bot_start_times[bot_id] = datetime.now()
        
        # Wait briefly and check if it started
        await_time = 2
        for _ in range(await_time * 10):
            pid = registry.get_pid(bot_id)
            if pid:
                return True, None, pid
            await asyncio.sleep(0.1)
        
        # If no PID file after 2 seconds, check if process is still alive
        if process.poll() is None:
            # Process is running but hasn't written PID yet
            return True, "Bot started but PID not yet written", process.pid
        else:
            return False, "Bot process exited immediately", None
            
    except Exception as e:
        return False, str(e), None


async def restart_bot(request):
    """Force restart a bot (kill -9 + start)"""
    if not validate_secret(request):
        return error_response("Unauthorized", 401)
    
    bot_id = request.match_info.get("bot_id")
    bot = registry.get_bot(bot_id)
    
    if not bot:
        return error_response(f"Bot '{bot_id}' not found", 404)
    
    # Kill the bot
    kill_success, kill_error = await kill_bot_process(bot_id)
    if not kill_success:
        return error_response(f"Failed to kill bot: {kill_error}", 500)
    
    # Wait a moment for cleanup
    await asyncio.sleep(0.5)
    
    # Start the bot
    start_success, start_error, pid = await start_bot_process(bot_id)
    if not start_success:
        return json_response({
            "success": False,
            "message": f"Bot killed but failed to start: {start_error}",
            "killed": True,
            "started": False,
        }, status=500)
    
    return success_response(
        f"Bot '{bot_id}' restarted successfully",
        pid=pid,
        killed=True,
        started=True,
    )


async def stop_bot(request):
    """Force stop a bot (kill -9)"""
    if not validate_secret(request):
        return error_response("Unauthorized", 401)
    
    bot_id = request.match_info.get("bot_id")
    bot = registry.get_bot(bot_id)
    
    if not bot:
        return error_response(f"Bot '{bot_id}' not found", 404)
    
    pid = registry.get_pid(bot_id)
    if not pid:
        return success_response(f"Bot '{bot_id}' is not running")
    
    kill_success, kill_error = await kill_bot_process(bot_id)
    if not kill_success:
        return error_response(f"Failed to stop bot: {kill_error}", 500)
    
    return success_response(f"Bot '{bot_id}' stopped", previous_pid=pid)


async def start_bot(request):
    """Start a stopped bot"""
    if not validate_secret(request):
        return error_response("Unauthorized", 401)
    
    bot_id = request.match_info.get("bot_id")
    bot = registry.get_bot(bot_id)
    
    if not bot:
        return error_response(f"Bot '{bot_id}' not found", 404)
    
    # Check if already running
    existing_pid = registry.get_pid(bot_id)
    if existing_pid:
        return json_response({
            "success": True,
            "message": f"Bot '{bot_id}' is already running",
            "pid": existing_pid,
            "already_running": True,
        })
    
    start_success, start_error, pid = await start_bot_process(bot_id)
    if not start_success:
        return error_response(f"Failed to start bot: {start_error}", 500)
    
    return success_response(f"Bot '{bot_id}' started", pid=pid)


async def register_bot(request):
    """Register a new bot (called by register_bot.sh)"""
    if not validate_secret(request):
        return error_response("Unauthorized", 401)
    
    try:
        data = await request.json()
    except:
        return error_response("Invalid JSON body", 400)
    
    bot_id = data.get("bot_id")
    working_dir = data.get("working_dir")
    start_command = data.get("start_command", "bash start")
    
    if not bot_id:
        return error_response("bot_id is required", 400)
    if not working_dir:
        return error_response("working_dir is required", 400)
    
    registry.add_bot(bot_id, working_dir, start_command)
    return success_response(f"Bot '{bot_id}' registered", bot_id=bot_id)


async def unregister_bot(request):
    """Unregister a bot"""
    if not validate_secret(request):
        return error_response("Unauthorized", 401)
    
    bot_id = request.match_info.get("bot_id")
    
    if registry.remove_bot(bot_id):
        return success_response(f"Bot '{bot_id}' unregistered")
    else:
        return error_response(f"Bot '{bot_id}' not found", 404)


def create_app():
    """Create the aiohttp application"""
    app = web.Application()
    
    # Routes
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    app.router.add_get("/bots", list_bots)
    app.router.add_post("/bots", register_bot)
    app.router.add_get("/bots/{bot_id}", get_bot_status)
    app.router.add_get("/bots/{bot_id}/status", get_bot_status)
    app.router.add_post("/bots/{bot_id}/restart", restart_bot)
    app.router.add_post("/bots/{bot_id}/stop", stop_bot)
    app.router.add_post("/bots/{bot_id}/start", start_bot)
    app.router.add_delete("/bots/{bot_id}", unregister_bot)
    
    return app


def main():
    if not MANAGER_SECRET:
        print("ERROR: MANAGER_SECRET environment variable is required")
        print("Generate one with: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        sys.exit(1)
    
    # Ensure directories exist
    registry.ensure_directories()
    
    print(f"Bot Manager starting on port {MANAGER_PORT}")
    print(f"Health check: http://0.0.0.0:{MANAGER_PORT}/health")
    print(f"List bots: GET /bots (requires X-Manager-Secret header)")
    print(f"Restart bot: POST /bots/{{bot_id}}/restart (requires X-Manager-Secret header)")
    
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=MANAGER_PORT, print=None)


if __name__ == "__main__":
    main()
