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
from ytSearch.suggestions import VideoSuggestions
from AnonXMusic import LOGGER
from AnonXMusic.utils.formatters import time_to_seconds
from config import DURATION_LIMIT, PLAYBACK_MODE, STREAMING, YT_API_KEY, YTPROXY_URL as YTPROXY

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
    # Hybrid-mode background pre-downloads, keyed by video id -> asyncio.Task.
    _prefetch_tasks = {}

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

    async def _download_full(self, vid_id, filepath, media_type, headers_url=None):
        """Fully download the media to `filepath`, with a single re-fetch/retry on failure.

        `headers_url` is an optional (media_url, cookie) pair already fetched by the caller
        (avoids a duplicate /info call); when omitted we fetch it here.
        """
        if headers_url is None:
            media_url, cookie = await self._fetch_media_url(vid_id, media_type)
        else:
            media_url, cookie = headers_url
        if not media_url:
            return None

        result = await self._download_parallel(media_url, filepath, self._get_headers(cookie))
        if result:
            return result

        # The URL likely died mid-download (expired, or googlevideo 403/410 from an
        # egress-IP mismatch). Re-fetch /info once — the router re-steers to a dyno whose
        # IP matches and issues a fresh affinity cookie — then retry the download.
        logger.warning(f"Download failed for {vid_id} ({media_type}); re-fetching URL and retrying once")
        await asyncio.sleep(2)  # brief pause to avoid hammering the API
        media_url, cookie = await self._fetch_media_url(vid_id, media_type)
        if not media_url:
            return None
        return await self._download_parallel(media_url, filepath, self._get_headers(cookie))

    async def _download_media(self, vid_id, filepath, media_type='audio', force_download=False):
        """Resolve media to a playable target (local path or direct URL) for the current mode.

        - download mode (or force_download for the /song feature): fully download -> local path.
        - stream mode: hand back the media URL for py-tgcalls/ffmpeg to fetch itself.
        - hybrid mode: if a background pre-download has already produced the file, use it;
          otherwise cancel any in-flight pre-download and stream the URL now (a play/skip
          means "play it immediately" — quality yields to responsiveness).
        """
        if os.path.exists(filepath):
            # A completed pre-download (or an earlier play) already left the whole file here.
            return filepath

        if not force_download and PLAYBACK_MODE in ("stream", "hybrid"):
            if PLAYBACK_MODE == "hybrid":
                # We're resolving this song to play right now; don't let a background
                # pre-download keep racing/writing the same file behind us.
                self.cancel_prefetch(vid_id)
            # Direct-stream: py-tgcalls/ffmpeg fetches the URL itself, so the affinity
            # cookie isn't attached here (see README for the ffmpeg-header follow-up).
            media_url, _cookie = await self._fetch_media_url(vid_id, media_type)
            return media_url

        return await self._download_full(vid_id, filepath, media_type)

    @classmethod
    def cancel_prefetch(cls, vidid):
        """Cancel (and forget) any in-flight hybrid pre-download for `vidid`."""
        if not vidid:
            return
        task = cls._prefetch_tasks.pop(vidid, None)
        if task and not task.done():
            task.cancel()

    @classmethod
    def cancel_prefetch_for_queue(cls, queue):
        """Cancel pre-downloads for every entry in a queue (used on stop/clear)."""
        for item in queue or []:
            try:
                cls.cancel_prefetch(item.get("vidid"))
            except Exception:
                pass

    def start_prefetch(self, entry, video=False, delay=3.5):
        """Kick off a background pre-download for a queued song (hybrid mode).

        `entry` is the live queue dict; when the download finishes we update `entry['file']`
        in place (the queue holds the same object), so change_stream/skip find a local path
        instead of the deferred `vid_` marker. One task per video id at a time.
        """
        vidid = entry.get("vidid")
        if not vidid or vidid in self._prefetch_tasks:
            return
        task = asyncio.create_task(self._prefetch_worker(entry, video, delay))
        self._prefetch_tasks[vidid] = task

    async def _prefetch_worker(self, entry, video, delay):
        vidid = entry.get("vidid")
        media_type = "video" if video else "audio"
        ext = "mp4" if video else "mp3"
        filepath = os.path.join("downloads", f"{vidid}.{ext}")
        tmp = filepath + ".part"
        media_url = None
        try:
            # Warm-up: request the URL immediately so the backend propagates/primes it,
            # then wait a few seconds before actually pulling the bytes.
            media_url, cookie = await self._fetch_media_url(vidid, media_type)
            await asyncio.sleep(delay)

            result = None
            if os.path.exists(filepath):
                result = filepath
            elif media_url:
                dl = await self._download_parallel(media_url, tmp, self._get_headers(cookie))
                if not dl:
                    # URL may have expired during the warm-up wait; re-fetch once.
                    media_url, cookie = await self._fetch_media_url(vidid, media_type)
                    if media_url:
                        dl = await self._download_parallel(media_url, tmp, self._get_headers(cookie))
                if dl and os.path.exists(tmp):
                    # Publish atomically so a half-written file is never seen as complete.
                    try:
                        os.replace(tmp, filepath)
                        result = filepath
                    except Exception as e:
                        logger.error(f"prefetch rename failed for {vidid}: {e}")

            # Only commit if the entry is still the deferred marker (not skipped/played yet).
            if str(entry.get("file", "")).startswith("vid_"):
                if result:
                    entry["file"] = result            # quality upgrade to local file
                elif media_url:
                    entry["file"] = media_url          # graceful fallback: stream the URL
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"prefetch worker failed for {vidid}: {e}")
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            self._prefetch_tasks.pop(vidid, None)



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
        
        # /song downloads must always yield a real file to upload, regardless of mode.
        if songvideo:
            filepath = f"downloads/{title}.mp4"
            result = await self._download_media(vid_id, filepath, 'video', force_download=True)
            return result
        elif songaudio:
            filepath = f"downloads/{title}.mp3"
            result = await self._download_media(vid_id, filepath, 'audio', force_download=True)
            return result
        # In hybrid mode we defer to a `vid_` queue marker (direct=False) so the song is
        # streamed instantly and pre-downloaded in the background; other modes store the
        # resolved path/URL directly (direct=True).
        direct = PLAYBACK_MODE != "hybrid"
        if video:
            filepath = os.path.join("downloads", f"{vid_id}.mp4")
            downloaded_file = await self._download_media(vid_id, filepath, 'video')
            return downloaded_file, direct
        else:
            filepath = os.path.join("downloads", f"{vid_id}.mp3")
            downloaded_file = await self._download_media(vid_id, filepath, 'audio')
            return downloaded_file, direct

