import asyncio
import os
from datetime import datetime, timedelta
from typing import Union

from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup
from pytgcalls import PyTgCalls
from pytgcalls.exceptions import (
    NoActiveGroupCall,
    NoAudioSourceFound,
    NoVideoSourceFound,
)
from ntgcalls import TelegramServerError
from pytgcalls.types import Update, StreamEnded
from pytgcalls import filters as fl
from pytgcalls.types import AudioQuality, VideoQuality
from pytgcalls.types import MediaStream,ChatUpdate, GroupCallParticipant, UpdatedGroupCallParticipant

import config
from AnonXMusic import LOGGER, YouTube, app
from AnonXMusic.misc import db
from AnonXMusic.utils.database import (
    add_active_chat,
    add_active_video_chat,
    get_lang,
    get_loop,
    group_assistant,
    is_autoend,
    is_active_chat,
    music_on,
    remove_active_chat,
    remove_active_video_chat,
    set_loop,
)
from AnonXMusic.utils.exceptions import AssistantErr
from AnonXMusic.utils.formatters import check_duration, seconds_to_min, speed_converter
from AnonXMusic.utils.inline.play import stream_markup
from AnonXMusic.utils.thumbnails import get_thumb
from AnonXMusic.utils.stream.autoclear import auto_clean, clear_queue_files
from strings import get_string

logger = LOGGER(__name__)

autoend = {}
autoend_tasks = {}
counter = {}
AUTO_END_TIME = 0.5

async def _clear_(chat_id):
    queue = db.get(chat_id, [])
    await clear_queue_files(chat_id, queue)
    db[chat_id] = []
    await remove_active_video_chat(chat_id)
    await remove_active_chat(chat_id)


class Call(PyTgCalls):
    def __init__(self):
        self.userbot1 = Client(
            name="AnonXAss1",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING1),
        )
        self.one = PyTgCalls(
            self.userbot1,
            cache_duration=100,
        )
        self.userbot2 = Client(
            name="AnonXAss2",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING2),
        )
        self.two = PyTgCalls(
            self.userbot2,
            cache_duration=100,
        )
        self.userbot3 = Client(
            name="AnonXAss3",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING3),
        )
        self.three = PyTgCalls(
            self.userbot3,
            cache_duration=100,
        )
        self.userbot4 = Client(
            name="AnonXAss4",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING4),
        )
        self.four = PyTgCalls(
            self.userbot4,
            cache_duration=100,
        )
        self.userbot5 = Client(
            name="AnonXAss5",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=str(config.STRING5),
        )
        self.five = PyTgCalls(
            self.userbot5,
            cache_duration=100,
        )

    async def pause_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.pause(chat_id)

    async def resume_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        await assistant.resume(chat_id)

    async def stop_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            await _clear_(chat_id)
            await assistant.leave_call(chat_id)
        except:
            pass

    async def stop_stream_force(self, chat_id: int):
        try:
            if config.STRING1:
                await self.one.leave_call(chat_id)
        except:
            pass
        try:
            if config.STRING2:
                await self.two.leave_call(chat_id)
        except:
            pass
        try:
            if config.STRING3:
                await self.three.leave_call(chat_id)
        except:
            pass
        try:
            if config.STRING4:
                await self.four.leave_call(chat_id)
        except:
            pass
        try:
            if config.STRING5:
                await self.five.leave_call(chat_id)
        except:
            pass
        try:
            await _clear_(chat_id)
        except:
            pass

    async def speedup_stream(self, chat_id: int, file_path, speed, playing):
        assistant = await group_assistant(self, chat_id)
        if str(speed) != str("1.0"):
            base = os.path.basename(file_path)
            chatdir = os.path.join(os.getcwd(), "playback", str(speed))
            if not os.path.isdir(chatdir):
                os.makedirs(chatdir)
            out = os.path.join(chatdir, base)
            if not os.path.isfile(out):
                if str(speed) == str("0.5"):
                    vs = 2.0
                if str(speed) == str("0.75"):
                    vs = 1.35
                if str(speed) == str("1.5"):
                    vs = 0.68
                if str(speed) == str("2.0"):
                    vs = 0.5
                proc = await asyncio.create_subprocess_shell(
                    cmd=(
                        "ffmpeg "
                        "-i "
                        f"{file_path} "
                        "-filter:v "
                        f"setpts={vs}*PTS "
                        "-filter:a "
                        f"atempo={speed} "
                        f"{out}"
                    ),
                    stdin=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
            else:
                pass
        else:
            out = file_path
        dur = await asyncio.get_event_loop().run_in_executor(None, check_duration, out)
        dur = int(dur)
        played, con_seconds = speed_converter(playing[0]["played"], speed)
        duration = seconds_to_min(dur)
        stream = (
            MediaStream(
                out,
                audio_parameters=AudioQuality.HIGH,
                video_parameters=VideoQuality.SD_480p,
                ffmpeg_parameters=f"-ss {played} -to {duration}",

            )
            if playing[0]["streamtype"] == "video"
            else MediaStream(
                out,
                audio_parameters=AudioQuality.HIGH,
                ffmpeg_parameters=f"-ss {played} -to {duration}",
                video_flags=MediaStream.Flags.IGNORE
            )
        )
        if str(db[chat_id][0]["file"]) == str(file_path):
            await assistant.play(chat_id, stream)
        else:
            raise AssistantErr("Umm")
        if str(db[chat_id][0]["file"]) == str(file_path):
            exis = (playing[0]).get("old_dur")
            if not exis:
                db[chat_id][0]["old_dur"] = db[chat_id][0]["dur"]
                db[chat_id][0]["old_second"] = db[chat_id][0]["seconds"]
            db[chat_id][0]["played"] = con_seconds
            db[chat_id][0]["dur"] = duration
            db[chat_id][0]["seconds"] = dur
            db[chat_id][0]["speed_path"] = out
            db[chat_id][0]["speed"] = speed

    async def force_stop_stream(self, chat_id: int):
        assistant = await group_assistant(self, chat_id)
        try:
            check = db.get(chat_id)
            if check:
                popped = check.pop(0)
                await auto_clean(popped)
        except:
            pass
        await remove_active_video_chat(chat_id)
        await remove_active_chat(chat_id)
        try:
            await assistant.leave_call(chat_id)
        except:
            pass

    async def skip_stream(
        self,
        chat_id: int,
        link: str,
        video: Union[bool, str] = None,
        image: Union[bool, str] = None,
    ):
        assistant = await group_assistant(self, chat_id)
        if video:
            stream = MediaStream(
                link,
                audio_parameters=AudioQuality.HIGH,
                video_parameters=VideoQuality.SD_480p,
            )
        else:
            stream = MediaStream(link, audio_parameters=AudioQuality.HIGH,video_flags=MediaStream.Flags.IGNORE)
        await assistant.play(
            chat_id,
            stream,
        )

    async def seek_stream(self, chat_id, file_path, to_seek, duration, mode):
        assistant = await group_assistant(self, chat_id)
        stream = (
            MediaStream(
                file_path,
                audio_parameters=AudioQuality.HIGH,
                video_parameters=VideoQuality.SD_480p,
                ffmpeg_parameters=f"-ss {to_seek} -to {duration}",
            )
            if mode == "video"
            else MediaStream(
                file_path,
                audio_parameters=AudioQuality.HIGH,
                video_flags=MediaStream.Flags.IGNORE,
                ffmpeg_parameters=f"-ss {to_seek} -to {duration}",
            )
        )
        await assistant.play(chat_id, stream)

    async def stream_call(self, link):
        assistant = await group_assistant(self, config.LOGGER_ID)
        await assistant.play(
            config.LOGGER_ID,
            MediaStream(link)
        )
        await asyncio.sleep(0.2)
        await assistant.leave_call(config.LOGGER_ID)

    async def join_call(
        self,
        chat_id: int,
        original_chat_id: int,
        link,
        video: Union[bool, str] = None,
        image: Union[bool, str] = None,
    ):
        assistant = await group_assistant(self, chat_id)
        language = await get_lang(chat_id)
        _ = get_string(language)
        if not link:
            raise AssistantErr(_["play_14"])
        def _build_stream():
            if video:
                return MediaStream(
                    link,
                    audio_parameters=AudioQuality.HIGH,video_parameters=VideoQuality.SD_480p,
                    audio_flags=MediaStream.Flags.REQUIRED,
                    video_flags=MediaStream.Flags.REQUIRED,
                    )
            return MediaStream(
                link,
                audio_parameters=AudioQuality.HIGH,
                video_flags=MediaStream.Flags.IGNORE,
                audio_flags=MediaStream.Flags.REQUIRED,
            )

        for attempt in range(2):
            try:
                await assistant.play(chat_id, _build_stream())
                break
            except (NoAudioSourceFound, NoVideoSourceFound) as e:
                logger.error(f"MediaStream source check failed for {chat_id} (attempt {attempt + 1}): {e}")
                if attempt == 1:
                    raise AssistantErr(_["play_14"])
                await asyncio.sleep(1)
            except NoActiveGroupCall:
                raise AssistantErr(_["call_8"])
            except TelegramServerError:
                raise AssistantErr(_["call_10"])
        await add_active_chat(chat_id)
        await music_on(chat_id)
        if video:
            await add_active_video_chat(chat_id)
        if await is_autoend():
            counter[chat_id] = {}
            users = len(await assistant.get_participants(chat_id))
            if users == 1:
                await self._schedule_autoend(chat_id, 1)

    async def change_stream(self, client, chat_id):
        check = db.get(chat_id)
        popped = None
        loop = await get_loop(chat_id)
        try:
            if loop == 0:
                popped = check.pop(0)
            else:
                loop = loop - 1
                await set_loop(chat_id, loop)
            if popped:
                await auto_clean(popped)
            if not check:
                await _clear_(chat_id)
                return await client.leave_call(chat_id)
        except:
            try:
                await _clear_(chat_id)
                return await client.leave_call(chat_id)
            except:
                return
        else:
            queued = check[0]["file"]
            language = await get_lang(chat_id)
            _ = get_string(language)
            title = (check[0]["title"]).title()
            user = check[0]["by"]
            user_id = check[0]["user_id"]
            original_chat_id = check[0]["chat_id"]
            streamtype = check[0]["streamtype"]
            videoid = check[0]["vidid"]
            thumbnail = check[0].get("thumbnail")
            duration = check[0]["dur"]
            db[chat_id][0]["played"] = 0
            exis = (check[0]).get("old_dur")
            if exis:
                db[chat_id][0]["dur"] = exis
                db[chat_id][0]["seconds"] = check[0]["old_second"]
                db[chat_id][0]["speed_path"] = None
                db[chat_id][0]["speed"] = 1.0
            video = True if str(streamtype) == "video" else False
            if "live_" in queued:
                n, link = await YouTube.video(videoid, True)
                if n == 0:
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                if video:
                    stream = MediaStream(
                        link,
                        audio_parameters=AudioQuality.HIGH,
                        video_parameters=VideoQuality.SD_480p,
                        audio_flags=MediaStream.Flags.REQUIRED,
                        video_flags=MediaStream.Flags.REQUIRED,
                    )
                else:
                    stream = MediaStream(
                        link,
                        audio_parameters=AudioQuality.HIGH,
                        video_flags=MediaStream.Flags.IGNORE,
                        audio_flags=MediaStream.Flags.REQUIRED,
                    )
                try:
                    await client.play(chat_id, stream)
                except Exception as e:
                    logger.error(f"change_stream (live_) failed for {chat_id}: {e}")
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                img = await get_thumb(videoid, user_id, title=title, duration=duration, thumbnail=thumbnail)
                button = stream_markup(_, chat_id)
                run = await app.send_photo(
                    chat_id=original_chat_id,
                    photo=img,
                    caption=_["stream_1"].format(
                        f"https://t.me/{app.username}?start=info_{videoid}",
                        title[:23],
                        duration,
                        user,
                    ),
                    reply_markup=InlineKeyboardMarkup(button),
                )
                db[chat_id][0]["mystic"] = run
                db[chat_id][0]["markup"] = "tg"
            elif "vid_" in queued:
                mystic = await app.send_message(original_chat_id, _["call_7"])
                try:
                    file_path, direct = await YouTube.download(
                        videoid,
                        mystic,
                        videoid=True,
                        video=True if str(streamtype) == "video" else False,
                    )
                except:
                    return await mystic.edit_text(
                        _["call_6"], disable_web_page_preview=True
                    )
                if not file_path:
                    # download() returned None (failed without raising) -> guard against
                    # MediaStream(None) TypeError; surface the clean failure message.
                    return await mystic.edit_text(
                        _["call_6"], disable_web_page_preview=True
                    )
                if video:
                    stream = MediaStream(
                        file_path,
                        audio_parameters=AudioQuality.HIGH,
                        video_parameters=VideoQuality.SD_480p,
                        audio_flags=MediaStream.Flags.REQUIRED,
                        video_flags=MediaStream.Flags.REQUIRED,
                    )
                else:
                    stream = MediaStream(
                        file_path,
                        audio_parameters=AudioQuality.HIGH,
                        video_flags=MediaStream.Flags.IGNORE,
                        audio_flags=MediaStream.Flags.REQUIRED,
                    )
                try:
                    await client.play(chat_id, stream)
                except Exception as e:
                    logger.error(f"change_stream (vid_) failed for {chat_id}: {e}")
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                img = await get_thumb(videoid, user_id, title=title, duration=duration, thumbnail=thumbnail)
                button = stream_markup(_, chat_id)
                await mystic.delete()
                run = await app.send_photo(
                    chat_id=original_chat_id,
                    photo=img,
                    caption=_["stream_1"].format(
                        f"https://t.me/{app.username}?start=info_{videoid}",
                        title[:23],
                        duration,
                        user,
                    ),
                    reply_markup=InlineKeyboardMarkup(button),
                )
                db[chat_id][0]["mystic"] = run
                db[chat_id][0]["markup"] = "stream"
            elif "index_" in queued:
                stream = (
                    MediaStream(
                        videoid,
                        audio_parameters=AudioQuality.HIGH,
                        video_parameters=VideoQuality.SD_480p,
                    )
                    if str(streamtype) == "video"
                    else MediaStream(videoid, audio_parameters=AudioQuality.HIGH, video_flags=MediaStream.Flags.IGNORE)
                )
                try:
                    await client.play(chat_id, stream)
                except:
                    return await app.send_message(
                        original_chat_id,
                        text=_["call_6"],
                    )
                button = stream_markup(_, chat_id)
                run = await app.send_photo(
                    chat_id=original_chat_id,
                    photo=config.STREAM_IMG_URL,
                    caption=_["stream_2"].format(user),
                    reply_markup=InlineKeyboardMarkup(button),
                )
                db[chat_id][0]["mystic"] = run
                db[chat_id][0]["markup"] = "tg"
            else:
                if video:
                    stream = MediaStream(
                        queued,
                        audio_parameters=AudioQuality.HIGH,
                        video_parameters=VideoQuality.SD_480p,
                    )
                else:
                    stream = MediaStream(
                        queued,
                        audio_parameters=AudioQuality.HIGH,
                        video_flags=MediaStream.Flags.IGNORE
                    )
                try:
                    await client.play(chat_id, stream)
                except:
                    try:
                        await client.leave_call(chat_id)
                        await asyncio.sleep(1)
                        await client.play(chat_id, stream)
                    except:
                        return await app.send_message(
                            original_chat_id,
                            text=_["call_6"],
                        )
                if videoid == "telegram":
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=config.TELEGRAM_AUDIO_URL
                        if str(streamtype) == "audio"
                        else config.TELEGRAM_VIDEO_URL,
                        caption=_["stream_1"].format(
                            config.SUPPORT_CHAT, title[:23], check[0]["dur"], user
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "tg"
                elif videoid == "soundcloud":
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=config.SOUNCLOUD_IMG_URL,
                        caption=_["stream_1"].format(
                            config.SUPPORT_CHAT, title[:23], duration, user
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "tg"
                else:
                    img = await get_thumb(videoid, user_id, title=title, duration=duration, thumbnail=thumbnail)
                    button = stream_markup(_, chat_id)
                    run = await app.send_photo(
                        chat_id=original_chat_id,
                        photo=img,
                        caption=_["stream_1"].format(
                            f"https://t.me/{app.username}?start=info_{videoid}",
                            title[:23],
                            duration,
                            user,
                        ),
                        reply_markup=InlineKeyboardMarkup(button),
                    )
                    db[chat_id][0]["mystic"] = run
                    db[chat_id][0]["markup"] = "stream"

    async def ping(self):
        pings = []
        if config.STRING1:
            pings.append(self.one.ping)
        if config.STRING2:
            pings.append(self.two.ping)
        if config.STRING3:
            pings.append(self.three.ping)
        if config.STRING4:
            pings.append(self.four.ping)
        if config.STRING5:
            pings.append(self.five.ping)
        return str(round(sum(pings) / len(pings), 3))

    async def start(self):
        LOGGER(__name__).info("Starting PyTgCalls Client...\n")
        if config.STRING1:
            await self.one.start()
        if config.STRING2:
            await self.two.start()
        if config.STRING3:
            await self.three.start()
        if config.STRING4:
            await self.four.start()
        if config.STRING5:
            await self.five.start()

    async def _autoend_runner(self, chat_id: int, minutes: int):
        try:
            await asyncio.sleep(minutes * 60)
            if not await is_autoend():
                autoend[chat_id] = {}
                return
            if not await is_active_chat(chat_id):
                autoend[chat_id] = {}
                return
            assistant = await group_assistant(self, chat_id)
            try:
                got = len(await assistant.get_participants(chat_id))
            except:
                autoend[chat_id] = {}
                return
            if got <= 1:
                autoend[chat_id] = {}
                try:
                    await self.stop_stream(chat_id)
                except:
                    pass
                try:
                    await app.send_message(
                        chat_id,
                        "» ʙᴏᴛ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ʟᴇғᴛ ᴠɪᴅᴇᴏᴄʜᴀᴛ ʙᴇᴄᴀᴜsᴇ ɴᴏ ᴏɴᴇ ᴡᴀs ʟɪsᴛᴇɴɪɴɢ ᴏɴ ᴠɪᴅᴇᴏᴄʜᴀᴛ.",
                    )
                except:
                    pass
        except asyncio.CancelledError:
            return

    async def _schedule_autoend(self, chat_id: int, minutes: int):
        await self._cancel_autoend(chat_id)
        expiration = datetime.now() + timedelta(minutes=minutes)
        autoend[chat_id] = expiration
        autoend_tasks[chat_id] = asyncio.create_task(self._autoend_runner(chat_id, minutes))

    async def _cancel_autoend(self, chat_id: int):
        task = autoend_tasks.get(chat_id)
        if task:
            task.cancel()
        autoend_tasks.pop(chat_id, None)
        autoend[chat_id] = {}

    async def decorators(self):
        @self.one.on_update(
                fl.chat_update(
                    ChatUpdate.Status.KICKED | 
                    ChatUpdate.Status.LEFT_GROUP | 
                    ChatUpdate.Status.CLOSED_VOICE_CHAT
                    ))
        @self.two.on_update(
                fl.chat_update(
                    ChatUpdate.Status.KICKED | 
                    ChatUpdate.Status.LEFT_GROUP | 
                    ChatUpdate.Status.CLOSED_VOICE_CHAT
                    ))
        @self.three.on_update(
                fl.chat_update(
                    ChatUpdate.Status.KICKED | 
                    ChatUpdate.Status.LEFT_GROUP | 
                    ChatUpdate.Status.CLOSED_VOICE_CHAT
                    ))
        @self.four.on_update(
                fl.chat_update(
                    ChatUpdate.Status.KICKED | 
                    ChatUpdate.Status.LEFT_GROUP | 
                    ChatUpdate.Status.CLOSED_VOICE_CHAT
                    ))
        @self.five.on_update(
                fl.chat_update(
                    ChatUpdate.Status.KICKED | 
                    ChatUpdate.Status.LEFT_GROUP | 
                    ChatUpdate.Status.CLOSED_VOICE_CHAT
                    ))
        async def stream_services_handler(client, update: Update):
            await self.stop_stream(update.chat_id)

        @self.one.on_update(fl.stream_end())
        @self.two.on_update(fl.stream_end())
        @self.three.on_update(fl.stream_end())
        @self.four.on_update(fl.stream_end())
        @self.five.on_update(fl.stream_end())
        async def stream_end_handler1(client:PyTgCalls, update: StreamEnded):
            await self.change_stream(client, update.chat_id)

        @self.one.on_update(fl.call_participant(GroupCallParticipant.Action.JOINED | GroupCallParticipant.Action.LEFT))
        @self.two.on_update(fl.call_participant(GroupCallParticipant.Action.JOINED | GroupCallParticipant.Action.LEFT))
        @self.three.on_update(fl.call_participant(GroupCallParticipant.Action.JOINED | GroupCallParticipant.Action.LEFT))
        @self.four.on_update(fl.call_participant(GroupCallParticipant.Action.JOINED | GroupCallParticipant.Action.LEFT))
        @self.five.on_update(fl.call_participant(GroupCallParticipant.Action.JOINED | GroupCallParticipant.Action.LEFT))
        async def participants_change_handler(client:PyTgCalls, update: UpdatedGroupCallParticipant):
            chat_id = update.chat_id
            users = counter.get(chat_id)
            if not users:
                try:
                    got = len(await client.get_participants(chat_id))
                except:
                    return
                counter[chat_id] = got
                if got == 1:
                    await self._schedule_autoend(chat_id, AUTO_END_TIME)
                    return
                await self._cancel_autoend(chat_id)
            else:
                final = users + 1 if str(update.action) == "Action.JOINED" else users - 1
                counter[chat_id] = final
                if final == 1:
                    await self._schedule_autoend(chat_id, AUTO_END_TIME)
                    return
                await self._cancel_autoend(chat_id)

    async def stop(self):
        if config.STRING1:
            await self.userbot1.stop()
        if config.STRING2:
            await self.userbot2.stop()
        if config.STRING3:
            await self.userbot3.stop()
        if config.STRING4:
            await self.userbot4.stop()
        if config.STRING5:
            await self.userbot5.stop()

Anony = Call()
