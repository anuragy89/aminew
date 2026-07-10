import random
import time as _time
from typing import Dict, List, Union

from AnonXMusic import userbot
from AnonXMusic.core.mongo import mongodb

authdb = mongodb.adminauth
authuserdb = mongodb.authuser
autoenddb = mongodb.autoend
assdb = mongodb.assistants
asslrudb = mongodb.assistant_lru
blacklist_chatdb = mongodb.blacklistChat
blockeddb = mongodb.blockedusers
chatsdb = mongodb.chats
channeldb = mongodb.cplaymode
countdb = mongodb.upcount
gbansdb = mongodb.gban
langdb = mongodb.language
onoffdb = mongodb.onoffper
playmodedb = mongodb.playmode
playtypedb = mongodb.playtypedb
skipdb = mongodb.skipmode
sudoersdb = mongodb.sudoers
usersdb = mongodb.tgusersdb
modeldb = mongodb.model

# Shifting to memory [mongo sucks often]
active = set()
activevideo = set()
assistantdict = {}
autoend = {}
autoplay = {}
count = {}
channelconnect = {}
langm = {}
loop = {}
maintenance = []
nonadmin = {}
pause = {}
playmode = {}
playtype = {}
skipmode = {}

# Negative caches — avoid hitting Mongo on every membership check
_autoend_cache = {"value": None}
_gbanned_users = set()
_gbanned_loaded = False
_banned_users = set()
_banned_loaded = False
_served_chats = set()
_served_chats_loaded = False
_nonadmin_authset = set()
_nonadmin_authloaded = False
_onoff_cache = {}

# LRU touch debounce — avoid one Mongo write per add/remove active
_lru_touch_at: Dict[tuple, float] = {}
LRU_TOUCH_DEBOUNCE_SEC = 300


async def get_assistant_number(chat_id: int) -> str:
    assistant = assistantdict.get(chat_id)
    return assistant


async def get_client(assistant: int):
    if int(assistant) == 1:
        return userbot.one
    elif int(assistant) == 2:
        return userbot.two
    elif int(assistant) == 3:
        return userbot.three
    elif int(assistant) == 4:
        return userbot.four
    elif int(assistant) == 5:
        return userbot.five


async def set_assistant_new(chat_id, number):
    number = int(number)
    await assdb.update_one(
        {"chat_id": chat_id},
        {"$set": {"assistant": number}},
        upsert=True,
    )


async def set_assistant(chat_id):
    from AnonXMusic.core.userbot import assistants

    ran_assistant = random.choice(assistants)
    assistantdict[chat_id] = ran_assistant
    await assdb.update_one(
        {"chat_id": chat_id},
        {"$set": {"assistant": ran_assistant}},
        upsert=True,
    )
    userbot = await get_client(ran_assistant)
    return userbot


async def get_assistant(chat_id: int) -> str:
    from AnonXMusic.core.userbot import assistants

    assistant = assistantdict.get(chat_id)
    if not assistant:
        dbassistant = await assdb.find_one({"chat_id": chat_id})
        if not dbassistant:
            userbot = await set_assistant(chat_id)
            return userbot
        else:
            got_assis = dbassistant["assistant"]
            if got_assis in assistants:
                assistantdict[chat_id] = got_assis
                userbot = await get_client(got_assis)
                return userbot
            else:
                userbot = await set_assistant(chat_id)
                return userbot
    else:
        if assistant in assistants:
            userbot = await get_client(assistant)
            return userbot
        else:
            userbot = await set_assistant(chat_id)
            return userbot


async def set_calls_assistant(chat_id):
    from AnonXMusic.core.userbot import assistants

    ran_assistant = random.choice(assistants)
    assistantdict[chat_id] = ran_assistant
    await assdb.update_one(
        {"chat_id": chat_id},
        {"$set": {"assistant": ran_assistant}},
        upsert=True,
    )
    return ran_assistant


async def group_assistant(self, chat_id: int) -> int:
    from AnonXMusic.core.userbot import assistants

    assistant = assistantdict.get(chat_id)
    if not assistant:
        dbassistant = await assdb.find_one({"chat_id": chat_id})
        if not dbassistant:
            assis = await set_calls_assistant(chat_id)
        else:
            assis = dbassistant["assistant"]
            if assis in assistants:
                assistantdict[chat_id] = assis
                assis = assis
            else:
                assis = await set_calls_assistant(chat_id)
    else:
        if assistant in assistants:
            assis = assistant
        else:
            assis = await set_calls_assistant(chat_id)
    if int(assis) == 1:
        return self.one
    elif int(assis) == 2:
        return self.two
    elif int(assis) == 3:
        return self.three
    elif int(assis) == 4:
        return self.four
    elif int(assis) == 5:
        return self.five


async def is_skipmode(chat_id: int) -> bool:
    if chat_id in skipmode:
        return skipmode[chat_id]
    user = await skipdb.find_one({"chat_id": chat_id})
    val = user is None
    skipmode[chat_id] = val
    return val


async def skip_on(chat_id: int):
    skipmode[chat_id] = True
    user = await skipdb.find_one({"chat_id": chat_id})
    if user:
        return await skipdb.delete_one({"chat_id": chat_id})


async def skip_off(chat_id: int):
    skipmode[chat_id] = False
    user = await skipdb.find_one({"chat_id": chat_id})
    if not user:
        return await skipdb.insert_one({"chat_id": chat_id})


async def get_upvote_count(chat_id: int) -> int:
    mode = count.get(chat_id)
    if not mode:
        mode = await countdb.find_one({"chat_id": chat_id})
        if not mode:
            return 5
        count[chat_id] = mode["mode"]
        return mode["mode"]
    return mode


async def set_upvotes(chat_id: int, mode: int):
    count[chat_id] = mode
    await countdb.update_one(
        {"chat_id": chat_id}, {"$set": {"mode": mode}}, upsert=True
    )


async def is_autoend() -> bool:
    if _autoend_cache["value"] is not None:
        return _autoend_cache["value"]
    user = await autoenddb.find_one({"chat_id": 1234})
    val = user is not None
    _autoend_cache["value"] = val
    return val


async def autoend_on():
    _autoend_cache["value"] = True
    await autoenddb.update_one(
        {"chat_id": 1234}, {"$set": {"chat_id": 1234}}, upsert=True
    )


async def autoend_off():
    _autoend_cache["value"] = False
    await autoenddb.delete_one({"chat_id": 1234})


async def get_loop(chat_id: int) -> int:
    lop = loop.get(chat_id)
    if not lop:
        return 0
    return lop


async def set_loop(chat_id: int, mode: int):
    loop[chat_id] = mode


async def is_autoplay(chat_id: int) -> bool:
    return autoplay.get(chat_id, False)


async def autoplay_on(chat_id: int):
    autoplay[chat_id] = True


async def autoplay_off(chat_id: int):
    autoplay[chat_id] = False


async def get_cmode(chat_id: int) -> int:
    mode = channelconnect.get(chat_id)
    if not mode:
        mode = await channeldb.find_one({"chat_id": chat_id})
        if not mode:
            return None
        channelconnect[chat_id] = mode["mode"]
        return mode["mode"]
    return mode


async def set_cmode(chat_id: int, mode: int):
    channelconnect[chat_id] = mode
    await channeldb.update_one(
        {"chat_id": chat_id}, {"$set": {"mode": mode}}, upsert=True
    )


async def get_playtype(chat_id: int) -> str:
    mode = playtype.get(chat_id)
    if not mode:
        mode = await playtypedb.find_one({"chat_id": chat_id})
        if not mode:
            playtype[chat_id] = "Everyone"
            return "Everyone"
        playtype[chat_id] = mode["mode"]
        return mode["mode"]
    return mode


async def set_playtype(chat_id: int, mode: str):
    playtype[chat_id] = mode
    await playtypedb.update_one(
        {"chat_id": chat_id}, {"$set": {"mode": mode}}, upsert=True
    )


async def get_playmode(chat_id: int) -> str:
    mode = playmode.get(chat_id)
    if not mode:
        mode = await playmodedb.find_one({"chat_id": chat_id})
        if not mode:
            playmode[chat_id] = "Direct"
            return "Direct"
        playmode[chat_id] = mode["mode"]
        return mode["mode"]
    return mode


async def set_playmode(chat_id: int, mode: str):
    playmode[chat_id] = mode
    await playmodedb.update_one(
        {"chat_id": chat_id}, {"$set": {"mode": mode}}, upsert=True
    )


async def get_lang(chat_id: int) -> str:
    mode = langm.get(chat_id)
    if not mode:
        lang = await langdb.find_one({"chat_id": chat_id})
        if not lang:
            langm[chat_id] = "en"
            return "en"
        langm[chat_id] = lang["lang"]
        return lang["lang"]
    return mode


async def set_lang(chat_id: int, lang: str):
    langm[chat_id] = lang
    await langdb.update_one({"chat_id": chat_id}, {"$set": {"lang": lang}}, upsert=True)


async def is_music_playing(chat_id: int) -> bool:
    mode = pause.get(chat_id)
    if not mode:
        return False
    return mode


async def music_on(chat_id: int):
    pause[chat_id] = True


async def music_off(chat_id: int):
    pause[chat_id] = False


async def get_active_chats() -> list:
    return list(active)


async def is_active_chat(chat_id: int) -> bool:
    return chat_id in active


async def add_active_chat(chat_id: int):
    active.add(chat_id)
    assistant = assistantdict.get(chat_id)
    if assistant:
        await touch_assistant_chat(assistant, chat_id)


async def remove_active_chat(chat_id: int):
    active.discard(chat_id)
    assistant = assistantdict.get(chat_id)
    if assistant:
        await touch_assistant_chat(assistant, chat_id)


async def touch_assistant_chat(assistant: int, chat_id: int):
    now = _time.time()
    key = (int(assistant), chat_id)
    last = _lru_touch_at.get(key, 0.0)
    if now - last < LRU_TOUCH_DEBOUNCE_SEC:
        return
    _lru_touch_at[key] = now
    try:
        await asslrudb.update_one(
            {"assistant": int(assistant), "chat_id": chat_id},
            {"$set": {"last_used": now}},
            upsert=True,
        )
    except Exception:
        pass


async def forget_assistant_chat(assistant: int, chat_id: int):
    _lru_touch_at.pop((int(assistant), chat_id), None)
    try:
        await asslrudb.delete_one(
            {"assistant": int(assistant), "chat_id": chat_id}
        )
    except Exception:
        pass


async def _bulk_forget_assistant_chats(assistant: int, chat_ids: List[int]):
    if not chat_ids:
        return
    a = int(assistant)
    for cid in chat_ids:
        _lru_touch_at.pop((a, cid), None)
    try:
        await asslrudb.delete_many(
            {"assistant": a, "chat_id": {"$in": list(chat_ids)}}
        )
    except Exception:
        pass


async def get_lru_chats(assistant: int, limit: int = 25) -> List[int]:
    try:
        cursor = asslrudb.find(
            {"assistant": int(assistant)},
            {"chat_id": 1, "_id": 0},
        ).sort("last_used", 1).limit(limit)
        return [doc["chat_id"] async for doc in cursor]
    except Exception:
        return []


async def evict_lru_for_assistant(client, assistant: int, batch: int = 10) -> int:
    from pyrogram.errors import FloodWait
    import asyncio as _aio
    import config as _cfg

    chats = await get_lru_chats(assistant, limit=batch * 4)
    evicted = 0
    forget_ids: List[int] = []
    logger_id = getattr(_cfg, "LOGGER_ID", None)
    for cid in chats:
        if cid in active or cid == logger_id:
            continue
        try:
            await client.leave_chat(cid)
            evicted += 1
        except FloodWait as fw:
            forget_ids.append(cid)
            try:
                await _aio.sleep(int(getattr(fw, "value", 5)))
            except Exception:
                pass
            continue
        except Exception:
            pass
        forget_ids.append(cid)
        if evicted >= batch:
            break
    await _bulk_forget_assistant_chats(assistant, forget_ids)
    return evicted


async def get_active_video_chats() -> list:
    return list(activevideo)


async def is_active_video_chat(chat_id: int) -> bool:
    return chat_id in activevideo


async def add_active_video_chat(chat_id: int):
    activevideo.add(chat_id)


async def remove_active_video_chat(chat_id: int):
    activevideo.discard(chat_id)


async def _ensure_nonadmin_loaded():
    global _nonadmin_authloaded
    if _nonadmin_authloaded:
        return
    try:
        async for doc in authdb.find({"chat_id": {"$lt": 0}}):
            _nonadmin_authset.add(doc["chat_id"])
    except Exception:
        pass
    _nonadmin_authloaded = True


async def check_nonadmin_chat(chat_id: int) -> bool:
    await _ensure_nonadmin_loaded()
    return chat_id in _nonadmin_authset


async def is_nonadmin_chat(chat_id: int) -> bool:
    mode = nonadmin.get(chat_id)
    if not mode:
        user = await authdb.find_one({"chat_id": chat_id})
        if not user:
            nonadmin[chat_id] = False
            return False
        nonadmin[chat_id] = True
        return True
    return mode


async def add_nonadmin_chat(chat_id: int):
    nonadmin[chat_id] = True
    await _ensure_nonadmin_loaded()
    if chat_id in _nonadmin_authset:
        return
    _nonadmin_authset.add(chat_id)
    return await authdb.insert_one({"chat_id": chat_id})


async def remove_nonadmin_chat(chat_id: int):
    nonadmin[chat_id] = False
    await _ensure_nonadmin_loaded()
    if chat_id not in _nonadmin_authset:
        return
    _nonadmin_authset.discard(chat_id)
    return await authdb.delete_one({"chat_id": chat_id})


async def is_on_off(on_off: int) -> bool:
    if on_off in _onoff_cache:
        return _onoff_cache[on_off]
    onoff = await onoffdb.find_one({"on_off": on_off})
    val = onoff is not None
    _onoff_cache[on_off] = val
    return val


async def add_on(on_off: int):
    if _onoff_cache.get(on_off):
        return
    _onoff_cache[on_off] = True
    return await onoffdb.update_one(
        {"on_off": on_off}, {"$set": {"on_off": on_off}}, upsert=True
    )


async def add_off(on_off: int):
    if _onoff_cache.get(on_off) is False:
        return
    _onoff_cache[on_off] = False
    return await onoffdb.delete_one({"on_off": on_off})


async def is_maintenance():
    if not maintenance:
        get = await onoffdb.find_one({"on_off": 1})
        if not get:
            maintenance.clear()
            maintenance.append(2)
            return True
        else:
            maintenance.clear()
            maintenance.append(1)
            return False
    else:
        if 1 in maintenance:
            return False
        else:
            return True


async def maintenance_off():
    maintenance.clear()
    maintenance.append(2)
    is_off = await is_on_off(1)
    if not is_off:
        return
    return await onoffdb.delete_one({"on_off": 1})


async def maintenance_on():
    maintenance.clear()
    maintenance.append(1)
    is_on = await is_on_off(1)
    if is_on:
        return
    return await onoffdb.insert_one({"on_off": 1})


async def is_served_user(user_id: int) -> bool:
    user = await usersdb.find_one({"user_id": user_id})
    if not user:
        return False
    return True


async def get_served_users() -> list:
    users_list = []
    async for user in usersdb.find({"user_id": {"$gt": 0}}):
        users_list.append(user)
    return users_list


async def add_served_user(user_id: int):
    is_served = await is_served_user(user_id)
    if is_served:
        return
    return await usersdb.insert_one({"user_id": user_id})


async def get_served_chats() -> list:
    chats_list = []
    async for chat in chatsdb.find({"chat_id": {"$lt": 0}}):
        chats_list.append(chat)
    return chats_list


async def _ensure_served_chats_loaded():
    global _served_chats_loaded
    if _served_chats_loaded:
        return
    try:
        async for doc in chatsdb.find({"chat_id": {"$lt": 0}}, {"chat_id": 1, "_id": 0}):
            _served_chats.add(doc["chat_id"])
    except Exception:
        pass
    _served_chats_loaded = True


async def is_served_chat(chat_id: int) -> bool:
    await _ensure_served_chats_loaded()
    return chat_id in _served_chats


async def add_served_chat(chat_id: int):
    await _ensure_served_chats_loaded()
    if chat_id in _served_chats:
        return
    _served_chats.add(chat_id)
    return await chatsdb.insert_one({"chat_id": chat_id})


async def blacklisted_chats() -> list:
    chats_list = []
    async for chat in blacklist_chatdb.find({"chat_id": {"$lt": 0}}):
        chats_list.append(chat["chat_id"])
    return chats_list


async def blacklist_chat(chat_id: int) -> bool:
    if not await blacklist_chatdb.find_one({"chat_id": chat_id}):
        await blacklist_chatdb.insert_one({"chat_id": chat_id})
        return True
    return False


async def whitelist_chat(chat_id: int) -> bool:
    if await blacklist_chatdb.find_one({"chat_id": chat_id}):
        await blacklist_chatdb.delete_one({"chat_id": chat_id})
        return True
    return False


async def _get_authusers(chat_id: int) -> Dict[str, int]:
    _notes = await authuserdb.find_one({"chat_id": chat_id})
    if not _notes:
        return {}
    return _notes["notes"]


async def get_authuser_names(chat_id: int) -> List[str]:
    _notes = []
    for note in await _get_authusers(chat_id):
        _notes.append(note)
    return _notes


async def get_authuser(chat_id: int, name: str) -> Union[bool, dict]:
    name = name
    _notes = await _get_authusers(chat_id)
    if name in _notes:
        return _notes[name]
    else:
        return False


async def save_authuser(chat_id: int, name: str, note: dict):
    name = name
    _notes = await _get_authusers(chat_id)
    _notes[name] = note

    await authuserdb.update_one(
        {"chat_id": chat_id}, {"$set": {"notes": _notes}}, upsert=True
    )


async def delete_authuser(chat_id: int, name: str) -> bool:
    notesd = await _get_authusers(chat_id)
    name = name
    if name in notesd:
        del notesd[name]
        await authuserdb.update_one(
            {"chat_id": chat_id},
            {"$set": {"notes": notesd}},
            upsert=True,
        )
        return True
    return False


async def get_gbanned() -> list:
    results = []
    async for user in gbansdb.find({"user_id": {"$gt": 0}}):
        user_id = user["user_id"]
        results.append(user_id)
    return results


async def _ensure_gbanned_loaded():
    global _gbanned_loaded
    if _gbanned_loaded:
        return
    try:
        async for doc in gbansdb.find({"user_id": {"$gt": 0}}, {"user_id": 1, "_id": 0}):
            _gbanned_users.add(doc["user_id"])
    except Exception:
        pass
    _gbanned_loaded = True


async def is_gbanned_user(user_id: int) -> bool:
    await _ensure_gbanned_loaded()
    return user_id in _gbanned_users


async def add_gban_user(user_id: int):
    await _ensure_gbanned_loaded()
    if user_id in _gbanned_users:
        return
    _gbanned_users.add(user_id)
    return await gbansdb.insert_one({"user_id": user_id})


async def remove_gban_user(user_id: int):
    await _ensure_gbanned_loaded()
    if user_id not in _gbanned_users:
        return
    _gbanned_users.discard(user_id)
    return await gbansdb.delete_one({"user_id": user_id})


async def get_sudoers() -> list:
    sudoers = await sudoersdb.find_one({"sudo": "sudo"})
    if not sudoers:
        return []
    return sudoers["sudoers"]


async def add_sudo(user_id: int) -> bool:
    sudoers = await get_sudoers()
    sudoers.append(user_id)
    await sudoersdb.update_one(
        {"sudo": "sudo"}, {"$set": {"sudoers": sudoers}}, upsert=True
    )
    return True


async def remove_sudo(user_id: int) -> bool:
    sudoers = await get_sudoers()
    sudoers.remove(user_id)
    await sudoersdb.update_one(
        {"sudo": "sudo"}, {"$set": {"sudoers": sudoers}}, upsert=True
    )
    return True


async def get_banned_users() -> list:
    results = []
    async for user in blockeddb.find({"user_id": {"$gt": 0}}):
        user_id = user["user_id"]
        results.append(user_id)
    return results


async def get_banned_count() -> int:
    users = blockeddb.find({"user_id": {"$gt": 0}})
    users = await users.to_list(length=100000)
    return len(users)


async def _ensure_banned_loaded():
    global _banned_loaded
    if _banned_loaded:
        return
    try:
        async for doc in blockeddb.find({"user_id": {"$gt": 0}}, {"user_id": 1, "_id": 0}):
            _banned_users.add(doc["user_id"])
    except Exception:
        pass
    _banned_loaded = True


async def is_banned_user(user_id: int) -> bool:
    await _ensure_banned_loaded()
    return user_id in _banned_users


async def add_banned_user(user_id: int):
    await _ensure_banned_loaded()
    if user_id in _banned_users:
        return
    _banned_users.add(user_id)
    return await blockeddb.insert_one({"user_id": user_id})


async def remove_banned_user(user_id: int):
    await _ensure_banned_loaded()
    if user_id not in _banned_users:
        return
    _banned_users.discard(user_id)
    return await blockeddb.delete_one({"user_id": user_id})


async def get_model_settings() -> dict:
    settings = await modeldb.find_one({"model": "settings"})
    if not settings:
        return {"tts": "athena", "image": "stable-diffusion", "ai": "GPT4"}
    return settings["settings"]


async def update_model_settings(settings: dict) -> bool:
    current_settings = await get_model_settings()

    updated_settings = {**current_settings, **settings}

    await modeldb.update_one(
        {"model": "settings"},
        {"$set": {"settings": updated_settings}},
        upsert=True
    )
    return True
