import asyncio
import glob
import json
import os
import re
import sys
from typing import Union
import aiohttp
import requests
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ytSearch import VideosSearch, Playlist
from AnonXMusic import LOGGER
from AnonXMusic.utils.formatters import time_to_seconds
from config import STREAMING, YT_API_KEY, YTPROXY_URL as YTPROXY

logger = LOGGER(__name__)

async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    _api_headers = None
    _session = None
    _config_validated = False
    
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        
        if not YouTubeAPI._config_validated:
            self._validate_config_on_init()
            YouTubeAPI._config_validated = True
    
    @staticmethod
    def _validate_config_on_init():
        """Validate API configuration at startup - exits if invalid"""
        if not YT_API_KEY:
            logger.error("API KEY not set in config. Set API Key you got from @tgmusic_apibot")
            logger.error("Exiting...")
            sys.exit(1)
        if not YTPROXY:
            logger.error("API Endpoint not set in config. Set a valid endpoint for YTPROXY_URL in config.")
            logger.error("Exiting...")
            sys.exit(1)
        logger.info("YouTube API config validated successfully")
    
    @classmethod
    def _get_headers(cls):
        """Get API headers (created once and reused)"""
        if cls._api_headers is None:
            cls._api_headers = {
                "x-api-key": f"{YT_API_KEY}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        return cls._api_headers
    
    @classmethod
    def _get_session(cls):
        """Get reusable requests session with retry logic"""
        if cls._session is None or not cls._session.adapters:
            cls._session = requests.Session()
            retries = Retry(total=3, backoff_factor=0.1)
            cls._session.mount('http://', HTTPAdapter(max_retries=retries))
            cls._session.mount('https://', HTTPAdapter(max_retries=retries))
        return cls._session
    
    @staticmethod
    async def _download_chunk(session, url, start, end, chunk_id, headers):
        """Download a single chunk using Range header through proxy"""
        chunk_headers = {**headers, "Range": f"bytes={start}-{end}"}
        chunk_size = end - start + 1
        logger.info(f"[CHUNK {chunk_id}] Starting download: bytes {start}-{end} ({chunk_size / 1024 / 1024:.2f} MB)")
        try:
            async with session.get(url, headers=chunk_headers, timeout=aiohttp.ClientTimeout(total=120)) as response:
                if response.status in (200, 206):
                    data = await response.read()
                    logger.info(f"[CHUNK {chunk_id}] Completed successfully: received {len(data) / 1024 / 1024:.2f} MB")
                    return chunk_id, data
                logger.warning(f"[CHUNK {chunk_id}] Failed with status {response.status}")
                return chunk_id, None
        except Exception as e:
            logger.error(f"[CHUNK {chunk_id}] Download failed: {str(e)}")
            return chunk_id, None
        
    async def _get_content_length(self, url, headers):
        """Get file size using HEAD request to proxy"""
        logger.info(f"[HEAD] Fetching content length from URL...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        content_length = int(response.headers.get('content-length', 0))
                        logger.info(f"[HEAD] Content-Length: {content_length} bytes ({content_length / 1024 / 1024:.2f} MB)")
                        return content_length
                    logger.warning(f"[HEAD] Request returned status {response.status}")
        except Exception as e:
            logger.error(f"[HEAD] Request failed: {str(e)}")
        return 0
    
    async def _download_single(self, url, filepath, headers):
        """Single connection download with aiohttp (fallback)"""
        logger.info(f"[SINGLE DOWNLOAD] Starting single-connection download to: {filepath}")
        try:
            timeout = aiohttp.ClientTimeout(total=300)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    if response.status != 200:
                        logger.error(f"[SINGLE DOWNLOAD] Failed with status {response.status}")
                        return None
                    
                    total_bytes = 0
                    with open(filepath, 'wb') as f:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            f.write(chunk)
                            total_bytes += len(chunk)
                            logger.info(f"[SINGLE DOWNLOAD] Progress: {total_bytes / 1024 / 1024:.2f} MB downloaded")
            
            logger.info(f"[SINGLE DOWNLOAD] Completed: {total_bytes / 1024 / 1024:.2f} MB saved to {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"[SINGLE DOWNLOAD] Failed: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None
    
    async def _download_parallel(self, url, filepath, headers, num_connections=4):
        """Download file in parallel using multiple Range requests"""
        logger.info(f"[PARALLEL DOWNLOAD] Initiating parallel download to: {filepath}")
        try:
            total_size = await self._get_content_length(url, headers)
            
            if total_size == 0:
                logger.warning(f"[PARALLEL DOWNLOAD] Content-Length is 0, falling back to single download")
                return await self._download_single(url, filepath, headers)
            
            if total_size < 5 * 1024 * 1024:
                logger.info(f"[PARALLEL DOWNLOAD] File too small ({total_size / 1024 / 1024:.2f} MB < 5 MB), using single download")
                return await self._download_single(url, filepath, headers)
            
            chunk_size = total_size // num_connections
            ranges = [
                (i * chunk_size, (i + 1) * chunk_size - 1 if i < num_connections - 1 else total_size - 1, i) 
                for i in range(num_connections)
            ]
            
            logger.info(f"[PARALLEL DOWNLOAD] Starting {num_connections} parallel connections for {total_size / 1024 / 1024:.2f} MB file")
            logger.info(f"[PARALLEL DOWNLOAD] Chunk size: {chunk_size / 1024 / 1024:.2f} MB each")
            for start, end, chunk_id in ranges:
                logger.info(f"[PARALLEL DOWNLOAD] Chunk {chunk_id}: bytes {start}-{end}")
            
            connector = aiohttp.TCPConnector(limit=num_connections, force_close=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                tasks = [
                    self._download_chunk(session, url, start, end, chunk_id, headers) 
                    for start, end, chunk_id in ranges
                ]
                results = await asyncio.gather(*tasks)
            
            if any(data is None for _, data in results):
                logger.error("[PARALLEL DOWNLOAD] Some chunks failed, falling back to single connection")
                return await self._download_single(url, filepath, headers)
            
            results.sort(key=lambda x: x[0])
            total_written = 0
            with open(filepath, 'wb') as f:
                for chunk_id, data in results:
                    f.write(data)
                    total_written += len(data)
                    logger.info(f"[PARALLEL DOWNLOAD] Wrote chunk {chunk_id}: {len(data) / 1024 / 1024:.2f} MB")
            
            logger.info(f"[PARALLEL DOWNLOAD] Completed: {total_written / 1024 / 1024:.2f} MB saved to {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"[PARALLEL DOWNLOAD] Failed: {str(e)}, falling back to single connection")
            return await self._download_single(url, filepath, headers)
    
    async def _fetch_media_url(self, vid_id, media_type='audio'):
        """Fetch audio/video URL from API (unified method)"""
        logger.info(f"[FETCH URL] Fetching {media_type} URL for video ID: {vid_id}")
        try:
            session = self._get_session()
            response = session.get(f"{YTPROXY}/info/{vid_id}", headers=self._get_headers(), timeout=60)
            data = response.json()
            
            if data.get('status') == 'success':
                media_url = data.get(f'{media_type}_url')
                logger.info(f"[FETCH URL] Successfully retrieved {media_type} URL")
                return media_url
            elif data.get('status') == 'error':
                logger.error(f"[FETCH URL] API Error: {data.get('message', 'Unknown error from API.')}")
            else:
                logger.error("[FETCH URL] Could not fetch Backend\nPlease contact API provider.")
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"[FETCH URL] Network error while fetching {media_type} info: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"[FETCH URL] Invalid response from proxy: {str(e)}")
        except Exception as e:
            logger.error(f"[FETCH URL] Error fetching {media_type} URL: {str(e)}")
        return None
    
    async def _download_media(self, vid_id, filepath, media_type='audio'):
        """Unified download method for audio/video"""
        logger.info(f"[DOWNLOAD] Starting {media_type} download for video ID: {vid_id}")
        logger.info(f"[DOWNLOAD] Target filepath: {filepath}")
        
        if os.path.exists(filepath):
            logger.info(f"[DOWNLOAD] File already exists, skipping download: {filepath}")
            return filepath
        
        media_url = await self._fetch_media_url(vid_id, media_type)
        if not media_url:
            logger.error(f"[DOWNLOAD] Failed to get media URL for {vid_id}")
            return None
        elif STREAMING:
            logger.info(f"[DOWNLOAD] STREAMING mode enabled, returning URL directly")
            return media_url
        
        logger.info(f"[DOWNLOAD] Proceeding with parallel download...")
        return await self._download_parallel(media_url, filepath, self._get_headers())
        


    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]


        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
            
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-g",
            "-f",
            "best[height<=?720][width<=?1280]",
            f"{link}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        playlist = await Playlist.get(link)
        if playlist:
            videos = []
            for video in playlist["videos"][:limit]:
                try:
                    duration = video.get("duration")
                    if duration:
                        duration_sec = int(time_to_seconds(duration))
                    else:
                        duration_sec = 0
                    videos.append({
                        "vidid": video["id"],
                        "title": video.get("title", "Unknown"),
                        "duration_min": duration,
                        "duration_sec": duration_sec,
                        "thumbnail": video.get("thumbnails", [{}])[0].get("url", "").split("?")[0] if video.get("thumbnails") else "",
                    })
                except:
                    continue
            return videos
        return None

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
        ytdl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
                except:
                    continue
                if not "dash" in str(format["format"]).lower():
                    try:
                        format["format"]
                        format["filesize"]
                        format["format_id"]
                        format["ext"]
                        format["format_note"]
                    except:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        try:
            results = []
            search = VideosSearch(link, limit=10)
            search_results = (await search.next()).get("result", [])

            for result in search_results:
                duration_str = result.get("duration", "0:00")
                try:
                    parts = duration_str.split(":")
                    duration_secs = 0
                    if len(parts) == 3:
                        duration_secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        duration_secs = int(parts[0]) * 60 + int(parts[1])

                    if duration_secs <= 3600:
                        results.append(result)
                except (ValueError, IndexError):
                    continue

            if not results or query_type >= len(results):
                raise ValueError("No suitable videos found within duration limit")

            selected = results[query_type]
            return (
                selected["title"],
                selected["duration"],
                selected["thumbnails"][0]["url"].split("?")[0],
                selected["id"]
            )

        except Exception as e:
            LOGGER(__name__).error(f"Error in slider: {str(e)}")
            raise ValueError("Failed to fetch video details")

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            vid_id = link
            link = self.base + link
        
        if songvideo:
            filepath = f"downloads/{title}.mp4"
            result = await self._download_media(vid_id, filepath, 'video')
            return result
        elif songaudio:
            filepath = f"downloads/{title}.mp3"
            result = await self._download_media(vid_id, filepath, 'audio')
            return result
        elif video:
            filepath = os.path.join("downloads", f"{vid_id}.mp4")
            downloaded_file = await self._download_media(vid_id, filepath, 'video')
            return downloaded_file, True
        else:
            filepath = os.path.join("downloads", f"{vid_id}.mp3")
            downloaded_file = await self._download_media(vid_id, filepath, 'audio')
            return downloaded_file, True

