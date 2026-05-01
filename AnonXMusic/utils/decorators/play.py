import asyncio
import re
import time as _time
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import (
    ChannelsTooMuch,
    ChatAdminRequired,
    FloodWait,
    InviteRequestSent,
    UserAlreadyParticipant,
    UserNotParticipant,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from AnonXMusic import YouTube, app
from AnonXMusic.misc import SUDOERS
from AnonXMusic.utils.database import (
    assistantdict,
    evict_lru_for_assistant,
    get_assistant,
    get_client,
    get_cmode,
    get_lang,
    get_playmode,
    get_playtype,
    is_active_chat,
    is_maintenance,
    set_assistant_new,
    touch_assistant_chat,
)
from AnonXMusic.utils.inline import botplaylist_markup
from config import PLAYLIST_IMG_URL, SUPPORT_CHAT, adminlist
from strings import get_string

links = {}
chat_cache = {}
CHAT_CACHE_TTL = 60 * 60 * 12


async def get_chat_cached(app, chat_id):
    current_time = _time.time()
    if chat_id in chat_cache:
        cache_time, chat_data = chat_cache[chat_id]
        if current_time - cache_time < CHAT_CACHE_TTL:
            return chat_data
    chat_data = await app.get_chat(chat_id)
    chat_cache[chat_id] = (current_time, chat_data)
    return chat_data


def PlayWrapper(command):
    async def wrapper(client, message:Message):
        language = await get_lang(message.chat.id)
        _ = get_string(language)
        if message.sender_chat:
            upl = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="ʜᴏᴡ ᴛᴏ ғɪx ?",
                            callback_data="AnonymousAdmin",
                        ),
                    ]
                ]
            )
            return await message.reply_text(_["general_3"], reply_markup=upl)          

        if await is_maintenance() is False:
            if message.from_user.id not in SUDOERS:
                return await message.reply_text(
                    text=f"{app.mention} ɪs ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ, ᴠɪsɪᴛ <a href={SUPPORT_CHAT}>sᴜᴘᴘᴏʀᴛ ᴄʜᴀᴛ</a> ғᴏʀ ᴋɴᴏᴡɪɴɢ ᴛʜᴇ ʀᴇᴀsᴏɴ.",
                    disable_web_page_preview=True,
                )
            
        try:
            ch = await get_chat_cached(app, message.chat.id)
            if (message.chat.title and re.search(r'[\u1000-\u109F]', message.chat.title)) or \
                (ch.description and re.search(r'[\u1000-\u109F]', ch.description)) or \
                re.search(r'[\u1000-\u109F]', message.text or ''):
                return await message.reply_text("This group is not allowed to play songs")
        except:
            pass

        try:
            await message.delete()
        except:
            pass

        audio_telegram = (
            (message.reply_to_message.audio or message.reply_to_message.voice)
            if message.reply_to_message
            else None
        )
        video_telegram = (
            (message.reply_to_message.video or message.reply_to_message.document)
            if message.reply_to_message
            else None
        )
        url = await YouTube.url(message)
        if audio_telegram is None and video_telegram is None and url is None:
            if len(message.command) < 2:
                if "stream" in message.command:
                    return await message.reply_text(_["str_1"])
                buttons = botplaylist_markup(_)
                return await message.reply_photo(
                    photo=PLAYLIST_IMG_URL,
                    caption=_["play_18"],
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
        if message.command[0][0] == "c":
            chat_id = await get_cmode(message.chat.id)
            if chat_id is None:
                return await message.reply_text(_["setting_7"])
            try:
                chat = await app.get_chat(chat_id)
            except:
                return await message.reply_text(_["cplay_4"])
            channel = chat.title
        else:
            chat_id = message.chat.id
            channel = None
        playmode = await get_playmode(message.chat.id)
        playty = await get_playtype(message.chat.id)
        if playty != "Everyone":
            if message.from_user.id not in SUDOERS:
                admins = adminlist.get(message.chat.id)
                if not admins:
                    return await message.reply_text(_["admin_13"])
                else:
                    if message.from_user.id not in admins:
                        return await message.reply_text(_["play_4"])
        if message.command[0][0] == "v":
            video = True
        else:
            if "-v" in message.text:
                video = True
            else:
                video = True if message.command[0][1] == "v" else None
        if message.command[0][-1] == "e":
            if not await is_active_chat(chat_id):
                return await message.reply_text(_["play_16"])
            fplay = True
        else:
            fplay = None

        if not await is_active_chat(chat_id):
            from AnonXMusic.core.userbot import assistants as _all_assistants

            current_num = assistantdict.get(chat_id)
            order = []
            if current_num and current_num in _all_assistants:
                order.append(current_num)
            for n in _all_assistants:
                if n not in order:
                    order.append(n)

            invitelink = None
            if chat_id in links:
                invitelink = links[chat_id]
            elif message.chat.username:
                invitelink = message.chat.username
            else:
                try:
                    invitelink = await app.export_chat_invite_link(chat_id)
                except ChatAdminRequired:
                    return await message.reply_text(_["call_1"])
                except Exception as e:
                    return await message.reply_text(
                        _["call_3"].format(app.mention, type(e).__name__)
                    )
            if invitelink and invitelink.startswith("https://t.me/+"):
                invitelink = invitelink.replace(
                    "https://t.me/+", "https://t.me/joinchat/"
                )

            userbot = None
            joined_via_request = False
            myu = None
            last_err = None
            admin_required = False

            for assistant_num in order:
                cand = await get_client(assistant_num)
                if cand is None:
                    continue

                try:
                    try:
                        get = await app.get_chat_member(chat_id, int(cand.id))
                    except:
                        get = await app.get_chat_member(chat_id, cand.username)
                except ChatAdminRequired:
                    admin_required = True
                    continue
                except UserNotParticipant:
                    get = None
                except Exception as e:
                    last_err = e
                    continue

                if get is not None:
                    if get.status in (
                        ChatMemberStatus.BANNED,
                        ChatMemberStatus.RESTRICTED,
                    ):
                        last_err = "banned"
                        continue
                    userbot = cand
                    break

                if not invitelink:
                    last_err = "no_invite"
                    continue

                try:
                    await cand.resolve_peer(
                        invitelink if message.chat.username else chat_id
                    )
                except:
                    pass

                if myu is None:
                    myu = await message.reply_text(_["call_4"].format(app.mention))

                joined = False
                for attempt in range(2):
                    try:
                        await asyncio.sleep(1)
                        await cand.join_chat(invitelink)
                        joined = True
                        break
                    except InviteRequestSent:
                        try:
                            await app.approve_chat_join_request(chat_id, cand.id)
                            joined_via_request = True
                            joined = True
                        except Exception as e:
                            last_err = e
                        break
                    except UserAlreadyParticipant:
                        joined = True
                        break
                    except ChannelsTooMuch as e:
                        last_err = e
                        if attempt == 0:
                            await evict_lru_for_assistant(cand, assistant_num, batch=10)
                            continue
                        break
                    except FloodWait as fw:
                        last_err = fw
                        try:
                            await asyncio.sleep(int(getattr(fw, "value", 5)))
                        except Exception:
                            pass
                        if attempt == 0:
                            continue
                        break
                    except Exception as e:
                        last_err = e
                        break

                if joined:
                    userbot = cand
                    break

            if userbot is None:
                if admin_required and last_err is None:
                    return await message.reply_text(_["call_1"])
                if last_err == "banned":
                    bot = await get_client(order[0])
                    return await message.reply_text(
                        _["call_2"].format(
                            app.mention, bot.id, bot.name, bot.username
                        )
                    )
                err_name = (
                    type(last_err).__name__ if isinstance(last_err, Exception)
                    else "AssistantUnavailable"
                )
                return await message.reply_text(
                    _["call_3"].format(app.mention, err_name)
                )

            if assistantdict.get(chat_id) != assistant_num:
                assistantdict[chat_id] = assistant_num
                await set_assistant_new(chat_id, assistant_num)
                await touch_assistant_chat(assistant_num, chat_id)

            if joined_via_request and myu is not None:
                try:
                    await asyncio.sleep(3)
                    await myu.edit(_["call_5"].format(app.mention))
                except Exception:
                    pass

            if invitelink:
                links[chat_id] = invitelink

            try:
                await userbot.resolve_peer(chat_id)
            except:
                pass
        
        return await command(
            client,
            message,
            _,
            chat_id,
            video,
            channel,
            playmode,
            url,
            fplay,
        )

    return wrapper
