import asyncio
from datetime import datetime

import config
from AnonXMusic import app
from AnonXMusic.core.call import Anony, autoend
from AnonXMusic.utils.database import get_client, is_active_chat
from pyrogram.enums import ChatType

async def auto_leave():
    if config.AUTO_LEAVING_ASSISTANT:
        while not await asyncio.sleep(config.ASSISTANT_LEAVE_TIME):
            from AnonXMusic.core.userbot import assistants

            for num in assistants:
                client = await get_client(num)
                left = 0
                try:
                    async for i in client.get_dialogs():
                        if i.chat.type in [
                            ChatType.SUPERGROUP,
                            ChatType.GROUP,
                            ChatType.CHANNEL,
                        ]:
                            if (
                                i.chat.id != config.LOGGER_ID
                                and i.chat.id != -1001580005596
                                and i.chat.id != -1001866745564
                            ):
                                if left == 20:
                                    continue
                                if not await is_active_chat(i.chat.id):
                                    try:
                                        await client.leave_chat(i.chat.id)
                                        left += 1
                                    except:
                                        continue
                except:
                    pass


asyncio.create_task(auto_leave())
