import asyncio
import glob
import json
import os
import re
import sys
from typing import Union
from urllib.parse import parse_qs, urlparse
import aiohttp
import requests
import yt_dlp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from ytSearch import VideosSearch, Playlist
from ytSearch.suggestions import VideoSuggestions
from AnonXMusic import LOGGER
from AnonXMusic.utils.formatters import time_to_seconds
from config import DURATION_LIMIT, STREAMING, YT_API_KEY, YTPROXY_URL as YTPROXY

logger = LOGGER(__name__)

AUDIO_VIA_VIDEO = True  # Set to True to always download video and extract audio, instead of direct audio stream

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
    def _get_headers(cls, cookie=None):
        """Get API headers (created once and reused).

        If `cookie` is given (the affinity cookie issued by the router on /info), attach
        it so the /stream + chunk requests are routed to the dyno that extracted the URL
        (the googlevideo URL is bound to that dyno's egress IP — a mismatch is a 403/410).
        """
        if cls._api_headers is None:
            cls._api_headers = {
                "x-api-key": f"{YT_API_KEY}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        if cookie:
            # Return a fresh dict so we never mutate the shared cached headers.
            return {**cls._api_headers, "Cookie": cookie}
        return cls._api_headers

    @staticmethod
    def _extract_affinity_cookie(response):
        """Pull the Heroku affinity cookie the router issued for this video.

        The router exposes it directly as `X-Affinity-Cookie: name=value` for non-browser
        clients; we fall back to parsing Set-Cookie. Attaching it to the download requests
        pins them to the extractor dyno, avoiding the egress-IP-mismatch 403/410.
        """
        cookie = response.headers.get("X-Affinity-Cookie")
        if cookie:
            return cookie
        try:
            for name, value in response.cookies.items():
                if "affinity" in name.lower():
                    return f"{name}={value}"
        except Exception:
            pass
        return None

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
        try:
            async with session.get(url, headers=chunk_headers, timeout=aiohttp.ClientTimeout(total=120)) as response:
                if response.status in (200, 206):
                    return chunk_id, await response.read()
                return chunk_id, None
        except Exception as e:
            logger.error(f"Chunk {chunk_id} download failed: {str(e)}")
            return chunk_id, None
        
    async def _get_content_length(self, url, headers):
        """Get file size using HEAD request to proxy"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        return int(response.headers.get('content-length', 0))
        except Exception as e:
            logger.error(f"HEAD request failed: {str(e)}")
        return 0
    
    async def _download_single(self, url, filepath, headers):
        """Single connection download with aiohttp (fallback)"""
        try:
            timeout = aiohttp.ClientTimeout(total=300)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, allow_redirects=True) as response:
                    if response.status != 200:
                        logger.error(f"Download failed with status {response.status}")
                        return None
                    
                    with open(filepath, 'wb') as f:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            f.write(chunk)
            
            return filepath
            
        except Exception as e:
            logger.error(f"Single download failed: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None
    
    @staticmethod
    def _is_googlevideo_url(url):
        return bool(re.match(r".*googlevideo\.com/", url))

    @staticmethod
    def _content_length_from_url(url):
        try:
            return int(parse_qs(urlparse(url).query).get("clen", [0])[0])
        except (TypeError, ValueError):
            return 0

    async def _download_googlevideo(self, url, filepath, chunk_size=1_000_000):
        try:
            total_size = self._content_length_from_url(url)

            timeout = aiohttp.ClientTimeout(total=300)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                with open(filepath, 'wb') as f:
                    start = 0
                    while total_size == 0 or start < total_size:
                        end = start + chunk_size - 1
                        if total_size:
                            end = min(end, total_size - 1)
                        range_headers = {"Range": f"bytes={start}-{end}"}

                        data = None
                        for attempt in range(3):
                            async with session.get(url, headers=range_headers) as response:
                                if response.status == 416:
                                    data = b""
                                    break
                                if response.status in (403, 429) and attempt < 2:
                                    # Transient CDN block - back off and retry the same range.
                                    logger.warning(f"Googlevideo status {response.status}, retrying in {2 ** attempt}s")
                                    await asyncio.sleep(2 ** attempt)
                                    continue
                                if response.status not in (200, 206):
                                    logger.error(f"Ranged download failed with status {response.status}")
                                    return None
                                data = await response.read()
                                break

                        if not data:
                            break
                        f.write(data)
                        start += len(data)
                        if total_size == 0 and len(data) < chunk_size:
                            break

            return filepath

        except Exception as e:
            logger.error(f"Googlevideo ranged download failed: {str(e)}")
            if os.path.exists(filepath):
                os.remove(filepath)
            return None

    async def _download_parallel(self, url, filepath, headers, num_connections=4):
        """Download file in parallel using multiple Range requests"""
        try:
            total_size = await self._get_content_length(url, headers)
            
            if total_size == 0 or total_size < 5 * 1024 * 1024:
                return await self._download_single(url, filepath, headers)
            
            chunk_size = total_size // num_connections
            ranges = [
                (i * chunk_size, (i + 1) * chunk_size - 1 if i < num_connections - 1 else total_size - 1, i) 
                for i in range(num_connections)
            ]
            
            connector = aiohttp.TCPConnector(limit=num_connections, force_close=True)
            async with aiohttp.ClientSession(connector=connector) as session:
                tasks = [
                    self._download_chunk(session, url, start, end, chunk_id, headers) 
                    for start, end, chunk_id in ranges
                ]
                results = await asyncio.gather(*tasks)
            
            if any(data is None for _, data in results):
                logger.error("Some chunks failed, falling back to single connection")
                return await self._download_single(url, filepath, headers)
            
            results.sort(key=lambda x: x[0])
            with open(filepath, 'wb') as f:
                for _, data in results:
                    f.write(data)
            
            return filepath
            
        except Exception as e:
            logger.error(f"Parallel download failed: {str(e)}, falling back to single connection")
            return await self._download_single(url, filepath, headers)
    
    async def _fetch_media_url(self, vid_id, media_type='audio'):
        """Fetch audio/video URL from API (unified method).

        Returns (url, cookie): the media URL and the affinity cookie to attach to the
        follow-up /stream requests (None if the API didn't issue one / on failure).
        """
        try:
            session = self._get_session()
            response = session.get(f"{YTPROXY}/info/{vid_id}", headers=self._get_headers(), timeout=60)
            data = response.json()

            if data.get('status') == 'success':
                return data.get(f'{media_type}_url'), self._extract_affinity_cookie(response)
            elif data.get('status') == 'error':
                logger.error(f"API Error: {data.get('message', 'Unknown error from API.')}")
            else:
                logger.error("Could not fetch Backend\nPlease contact API provider.")
            return None, None

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error while fetching {media_type} info: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid response from proxy: {str(e)}")
        except Exception as e:
            logger.error(f"Error fetching {media_type} URL: {str(e)}")
        return None, None

    @staticmethod
    async def _extract_audio(video_path, audio_path):
        """Strip the audio track out of a downloaded video file with ffmpeg."""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", video_path, "-vn", "-c:a", "libmp3lame", "-q:a", "2", audio_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0 or not os.path.exists(audio_path):
            logger.error(f"ffmpeg audio extraction failed: {stderr.decode(errors='ignore').strip()}")
            if os.path.exists(audio_path):
                os.remove(audio_path)
            return None
        return audio_path

    async def _download_audio_via_video(self, vid_id, filepath):
        """Download the video stream, then convert it to audio at `filepath`."""
        video_path = f"{os.path.splitext(filepath)[0]}.src.mp4"
        try:
            if not await self._download_url(vid_id, video_path, 'video'):
                return None
            return await self._extract_audio(video_path, filepath)
        finally:
            if os.path.exists(video_path):
                os.remove(video_path)

    async def _download_url(self, vid_id, filepath, media_type):
        """Fetch the media URL and download it, retrying once on a dead URL."""
        media_url, cookie = await self._fetch_media_url(vid_id, media_type)
        if not media_url:
            return None
        elif STREAMING:
            # Direct-stream mode: py-tgcalls/ffmpeg fetches the URL itself, so the affinity
            # cookie isn't attached here (see README for the ffmpeg-header follow-up).
            return media_url

        result = await self._download_media_url(media_url, filepath, self._get_headers(cookie))
        if result:
            return result

        # The URL likely died mid-download (expired, or googlevideo 403/410 from an
        # egress-IP mismatch). Re-fetch /info once — the router re-steers to a dyno whose
        # IP matches and issues a fresh affinity cookie — then retry the download.
        logger.warning(f"Download failed for {vid_id} ({media_type}); re-fetching URL and retrying once")
        media_url, cookie = await self._fetch_media_url(vid_id, media_type)
        if not media_url:
            return None
        return await self._download_media_url(media_url, filepath, self._get_headers(cookie))

    async def _download_media_url(self, media_url, filepath, headers):
        """Pick the right downloader for a resolved media URL."""
        if self._is_googlevideo_url(media_url):
            return await self._download_googlevideo(media_url, filepath)
        return await self._download_parallel(media_url, filepath, headers)

    async def _download_media(self, vid_id, filepath, media_type='audio'):
        """Unified download method for audio/video"""
        if os.path.exists(filepath):
            return filepath

        if media_type == 'audio' and AUDIO_VIA_VIDEO:
            if STREAMING:
                return await self._download_url(vid_id, filepath, 'video')
            return await self._download_audio_via_video(vid_id, filepath)

        return await self._download_url(vid_id, filepath, media_type)
        


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

    async def related(self, vidid: str, exclude: list = None):
        # A suggestion should be one song, not a multi-hour mix/compilation - those are
        # far more likely to time out mid-download (the downloader's per-connection
        # timeouts are minutes, not hours) and silently leave nothing playable queued.
        # Cap well below the generous playlist-import DURATION_LIMIT (~5h).
        autoplay_duration_limit = min(DURATION_LIMIT, 1200)
        exclude = set(exclude or [])
        try:
            suggestions = VideoSuggestions(vidid, limit=8)
            results = (await suggestions.next())["result"]
        except Exception:
            return None
        for result in results:
            if result.get("type") != "video":
                continue
            rid = result.get("id")
            if not rid or rid in exclude:
                continue
            duration_min = result.get("duration")
            try:
                duration_sec = int(time_to_seconds(duration_min)) if duration_min else None
            except Exception:
                duration_sec = None
            if not duration_sec or duration_sec > autoplay_duration_limit:
                continue
            thumbnails = result.get("thumbnails") or [{}]
            return {
                "vidid": rid,
                "title": result.get("title") or "Unknown",
                "duration_min": duration_min,
                "thumbnail": (thumbnails[0].get("url") or "").split("?")[0],
            }
        return None

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

