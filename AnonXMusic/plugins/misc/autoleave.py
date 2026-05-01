import asyncio

import config
from pyrogram.errors import FloodWait

from AnonXMusic.utils.database import (
    forget_assistant_chat,
    get_client,
    get_lru_chats,
    is_active_chat,
)

PROTECTED_CHATS = {-1001580005596, -1001866745564}
LEAVE_BATCH = 20


async def _leave_batch_for_assistant(num: int):
    client = await get_client(num)
    if client is None:
        return
    candidates = await get_lru_chats(num, limit=LEAVE_BATCH * 4)
    left = 0
    for cid in candidates:
        if left >= LEAVE_BATCH:
            break
        if cid == config.LOGGER_ID or cid in PROTECTED_CHATS:
            continue
        if await is_active_chat(cid):
            continue
        try:
            await client.leave_chat(cid)
            left += 1
        except FloodWait as fw:
            try:
                await asyncio.sleep(int(getattr(fw, "value", 5)))
            except Exception:
                pass
            continue
        except Exception:
            pass
        await forget_assistant_chat(num, cid)


async def auto_leave():
    if not config.AUTO_LEAVING_ASSISTANT:
        return
    while True:
        try:
            await asyncio.sleep(config.ASSISTANT_LEAVE_TIME)
        except Exception:
            await asyncio.sleep(3600)
        from AnonXMusic.core.userbot import assistants

        for num in list(assistants):
            try:
                await _leave_batch_for_assistant(num)
            except Exception:
                continue


asyncio.create_task(auto_leave())
