"""
Remote Restart Server for VPS Deployment
This module provides an HTTP endpoint that allows authorized external services
(like a ping checker bot) to restart the music bot remotely.
"""

import asyncio
import os
import shutil

from aiohttp import web

import config
from AnonXMusic import LOGGER
from AnonXMusic.utils.database import (
    get_active_chats,
    remove_active_chat,
    remove_active_video_chat,
)


class RestartServer:
    def __init__(self):
        self.app = web.Application()
        self.runner = None
        self.site = None
        self._setup_routes()

    def _setup_routes(self):
        """Setup HTTP routes"""
        self.app.router.add_get("/", self.health_check)
        self.app.router.add_get("/health", self.health_check)
        self.app.router.add_post("/restart", self.restart_handler)
        self.app.router.add_get("/restart", self.restart_handler)

    async def health_check(self, request):
        """Health check endpoint - returns bot status"""
        return web.json_response({
            "status": "alive",
            "bot": "AnonXMusic",
            "message": "Bot is running"
        })

    async def restart_handler(self, request):
        """Handle restart requests"""
        # Get secret from query params or headers
        secret = request.query.get("secret") or request.headers.get("X-Restart-Secret")
        
        # Validate secret
        if not config.RESTART_SECRET:
            LOGGER(__name__).warning("Restart attempted but RESTART_SECRET is not configured")
            return web.json_response({
                "status": "error",
                "message": "Restart secret not configured on server"
            }, status=500)
        
        if secret != config.RESTART_SECRET:
            LOGGER(__name__).warning(f"Unauthorized restart attempt from {request.remote}")
            return web.json_response({
                "status": "error",
                "message": "Unauthorized - Invalid secret"
            }, status=401)
        
        LOGGER(__name__).info(f"Authorized restart request received from {request.remote}")
        
        # Send response before restarting
        response = web.json_response({
            "status": "success",
            "message": "Restart initiated"
        })
        
        # Schedule restart after response is sent
        asyncio.create_task(self._perform_restart())
        
        return response

    async def _perform_restart(self):
        """Perform the actual restart"""
        from AnonXMusic import app as bot_app
        
        LOGGER(__name__).info("Performing remote restart...")
        
        # Notify active chats
        try:
            ac_chats = await get_active_chats()
            for x in ac_chats:
                try:
                    await bot_app.send_message(
                        chat_id=int(x),
                        text=f"{bot_app.mention} ɪs ʀᴇsᴛᴀʀᴛɪɴɢ (ʀᴇᴍᴏᴛᴇ)...\n\nʏᴏᴜ ᴄᴀɴ sᴛᴀʀᴛ ᴩʟᴀʏɪɴɢ ᴀɢᴀɪɴ ᴀғᴛᴇʀ 15-20 sᴇᴄᴏɴᴅs.",
                    )
                    await remove_active_chat(x)
                    await remove_active_video_chat(x)
                except Exception as e:
                    LOGGER(__name__).warning(f"Failed to notify chat {x}: {e}")
        except Exception as e:
            LOGGER(__name__).error(f"Error notifying chats: {e}")

        # Clean up temp directories
        try:
            shutil.rmtree("raw_files", ignore_errors=True)
            shutil.rmtree("cache", ignore_errors=True)
            shutil.rmtree("downloads", ignore_errors=True)
        except Exception as e:
            LOGGER(__name__).warning(f"Error cleaning directories: {e}")

        # Log to logger group
        try:
            await bot_app.send_message(
                chat_id=config.LOGGER_ID,
                text="🔄 <b>Remote Restart Triggered</b>\n\nBot is restarting via remote API...",
            )
        except:
            pass

        # Small delay to ensure response is sent
        await asyncio.sleep(1)
        
        # Restart the bot process
        LOGGER(__name__).info("Executing restart command...")
        os.system(f"kill -9 {os.getpid()} && bash start")

    async def start(self, port: int = None):
        """Start the web server"""
        port = port or config.RESTART_PORT
        
        if not port:
            LOGGER(__name__).info("RESTART_PORT not configured, restart server disabled")
            return
        
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, "0.0.0.0", port)
            await self.site.start()
            LOGGER(__name__).info(f"Restart server started on port {port}")
            LOGGER(__name__).info(f"Health check: http://0.0.0.0:{port}/health")
            LOGGER(__name__).info(f"Restart endpoint: http://0.0.0.0:{port}/restart?secret=YOUR_SECRET")
        except Exception as e:
            LOGGER(__name__).error(f"Failed to start restart server: {e}")

    async def stop(self):
        """Stop the web server"""
        if self.runner:
            await self.runner.cleanup()
            LOGGER(__name__).info("Restart server stopped")


# Global instance
restart_server = RestartServer()
