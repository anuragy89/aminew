"""
Bot Registry Module
Manages the shared registry of all bots on this VPS at /var/lib/bot-manager/bots.json
Provides thread-safe read/write operations with file locking.
"""

import fcntl
import json
import os
from pathlib import Path
from typing import Optional

REGISTRY_DIR = "/var/lib/bot-manager"
REGISTRY_FILE = f"{REGISTRY_DIR}/bots.json"
PIDS_DIR = f"{REGISTRY_DIR}/pids"


def ensure_directories():
    """Create required directories if they don't exist"""
    Path(REGISTRY_DIR).mkdir(parents=True, exist_ok=True)
    Path(PIDS_DIR).mkdir(parents=True, exist_ok=True)


def _read_registry_unsafe() -> dict:
    """Read registry without locking (internal use only)"""
    if not os.path.exists(REGISTRY_FILE):
        return {"bots": {}}
    try:
        with open(REGISTRY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"bots": {}}


def _write_registry_unsafe(data: dict):
    """Write registry without locking (internal use only)"""
    ensure_directories()
    with open(REGISTRY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def read_registry() -> dict:
    """Read the registry with file locking"""
    ensure_directories()
    if not os.path.exists(REGISTRY_FILE):
        return {"bots": {}}
    
    try:
        with open(REGISTRY_FILE, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return data
    except (json.JSONDecodeError, IOError):
        return {"bots": {}}


def write_registry(data: dict):
    """Write to registry with exclusive file locking"""
    ensure_directories()
    
    # Create file if it doesn't exist
    if not os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "w") as f:
            json.dump({"bots": {}}, f)
    
    with open(REGISTRY_FILE, "r+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def add_bot(bot_id: str, working_dir: str, start_command: str = "bash start") -> bool:
    """
    Add or update a bot in the registry.
    Safe to call multiple times - will update existing entry.
    
    Args:
        bot_id: Unique identifier for the bot (e.g., 'mybot1')
        working_dir: Absolute path to the bot's working directory
        start_command: Command to start the bot (default: 'bash start')
    
    Returns:
        True if added/updated successfully
    """
    ensure_directories()
    
    # Use exclusive lock for atomic read-modify-write
    if not os.path.exists(REGISTRY_FILE):
        with open(REGISTRY_FILE, "w") as f:
            json.dump({"bots": {}}, f)
    
    with open(REGISTRY_FILE, "r+") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            try:
                registry = json.load(f)
            except json.JSONDecodeError:
                registry = {"bots": {}}
            
            if "bots" not in registry:
                registry["bots"] = {}
            
            registry["bots"][bot_id] = {
                "bot_id": bot_id,
                "working_dir": working_dir,
                "start_command": start_command,
                "pid_file": f"{PIDS_DIR}/{bot_id}.pid"
            }
            
            f.seek(0)
            f.truncate()
            json.dump(registry, f, indent=2)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return True


def remove_bot(bot_id: str) -> bool:
    """
    Remove a bot from the registry.
    
    Args:
        bot_id: Unique identifier for the bot
    
    Returns:
        True if removed, False if not found
    """
    registry = read_registry()
    if bot_id in registry["bots"]:
        del registry["bots"][bot_id]
        write_registry(registry)
        return True
    return False


def get_bot(bot_id: str) -> Optional[dict]:
    """
    Get a specific bot's configuration.
    
    Args:
        bot_id: Unique identifier for the bot
    
    Returns:
        Bot configuration dict or None if not found
    """
    registry = read_registry()
    return registry["bots"].get(bot_id)


def list_bots() -> dict:
    """
    List all registered bots.
    
    Returns:
        Dictionary of all bots {bot_id: config}
    """
    registry = read_registry()
    return registry.get("bots", {})


def get_pid(bot_id: str) -> Optional[int]:
    """
    Get the PID of a running bot.
    
    Args:
        bot_id: Unique identifier for the bot
    
    Returns:
        PID as integer, or None if not running/no PID file
    """
    pid_file = f"{PIDS_DIR}/{bot_id}.pid"
    if not os.path.exists(pid_file):
        return None
    
    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
        # Check if process is actually running
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks
        return pid
    except (ValueError, ProcessLookupError, PermissionError, IOError):
        return None


def is_running(bot_id: str) -> bool:
    """
    Check if a bot is currently running.
    
    Args:
        bot_id: Unique identifier for the bot
    
    Returns:
        True if running, False otherwise
    """
    return get_pid(bot_id) is not None


def write_pid(bot_id: str, pid: int):
    """
    Write the PID file for a bot.
    
    Args:
        bot_id: Unique identifier for the bot
        pid: Process ID
    """
    ensure_directories()
    pid_file = f"{PIDS_DIR}/{bot_id}.pid"
    with open(pid_file, "w") as f:
        f.write(str(pid))


def remove_pid(bot_id: str):
    """
    Remove the PID file for a bot.
    
    Args:
        bot_id: Unique identifier for the bot
    """
    pid_file = f"{PIDS_DIR}/{bot_id}.pid"
    if os.path.exists(pid_file):
        os.remove(pid_file)
