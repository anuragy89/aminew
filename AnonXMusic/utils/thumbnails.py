import os
import re

import aiofiles
import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from unidecode import unidecode
from ytSearch import VideosSearch

from AnonXMusic import app, LOGGER
from config import YOUTUBE_IMG_URL

def changeImageSize(maxWidth, maxHeight, image):
    widthRatio = maxWidth / image.size[0]
    heightRatio = maxHeight / image.size[1]
    newWidth = int(widthRatio * image.size[0])
    newHeight = int(heightRatio * image.size[1])
    newImage = image.resize((newWidth, newHeight))
    return newImage

def circle(img):
    img = img.convert("RGBA")
    w, h = img.size
    
    mask = Image.new('L', (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, w, h), fill=255)
    
    output = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    output.paste(img, (0, 0))
    output.putalpha(mask)
    
    return output

def clear(text):
    list = text.split(" ")
    title = ""
    for i in list:
        if len(title) + len(i) < 60:
            title += " " + i
    return title.strip()

async def get_thumb(videoid, user_id, title=None, duration=None, thumbnail=None, channel=None, views=None):
    if os.path.isfile(f"cache/{videoid}_{user_id}.png"):
        return f"cache/{videoid}_{user_id}.png"

    try:
        if not all([title, thumbnail]):
            url = f"https://www.youtube.com/watch?v={videoid}"
            results = VideosSearch(url, limit=1)
            for result in (await results.next())["result"]:
                try:
                    title = result["title"]
                    title = re.sub(r"\W+", " ", title)
                    title = title.title()
                except:
                    title = "Unsupported Title"
                try:
                    duration = result["duration"]
                except:
                    duration = "Unknown Mins"
                thumbnail = result["thumbnails"][0]["url"].split("?")[0]
                try:
                    views = result["viewCount"]["short"]
                except:
                    views = "Unknown Views"
                try:
                    channel = result["channel"]["name"]
                except:
                    channel = "Unknown Channel"
        else:
            if title:
                title = re.sub(r"\W+", " ", title)
                title = title.title()
            else:
                title = "Unsupported Title"
            duration = duration or "Unknown Mins"
            views = views or "Unknown Views"
            channel = channel or "Unknown Channel"

        async with aiohttp.ClientSession() as session:
            async with session.get(thumbnail) as resp:
                if resp.status == 200:
                    f = await aiofiles.open(f"cache/thumb{videoid}.png", mode="wb")
                    await f.write(await resp.read())
                    await f.close()
        
        sp = None
        try:
            async for photo in app.get_chat_photos(user_id, 1):
                sp = await app.download_media(photo.file_id, file_name=f"{user_id}.jpg")
        except Exception as e:
            LOGGER(__name__).error(f"error 1 {e}")

        if not sp:
            try:
                async for photo in app.get_chat_photos(app.id, 1):
                    sp = await app.download_media(photo.file_id, file_name=f"{app.id}.jpg")
            except Exception as e:
                LOGGER(__name__).error(f"error 2{e}")

        if not sp:
            sp = f"cache/thumb{videoid}.png"
        
        xp = Image.open(sp)
        youtube = Image.open(f"cache/thumb{videoid}.png")
        
        image1 = changeImageSize(1280, 720, youtube)
        image2 = image1.convert("RGBA")
        background = image2.filter(filter=ImageFilter.BoxBlur(10))

        enhancer = ImageEnhance.Brightness(background)
        background = enhancer.enhance(0.5)
        y=changeImageSize(200,200,circle(youtube)) 
        background.paste(y,(45,225),mask=y)
        a=changeImageSize(200,200,circle(xp)) 
        background.paste(a,(1045,225),mask=a)
        
        draw = ImageDraw.Draw(background)
        
        arial = ImageFont.truetype("AnonXMusic/assets/font2.ttf", 30)
        font = ImageFont.truetype("AnonXMusic/assets/font.ttf", 30)

        draw.text((1110, 8), unidecode(app.name), fill="white", font=arial)
        draw.text(
                (55, 560),
                f"{channel} | {views[:23]}",
                (255, 255, 255),
                font=arial,
            )
        draw.text(
                (57, 600),
                clear(title),
                (255, 255, 255),
                font=font,
            )
        draw.line(
                [(55, 660), (1220, 660)],
                fill="white",
                width=5,
                joint="curve",
            )
        draw.ellipse(
                [(918, 648), (942, 672)],
                outline="white",
                fill="white",
                width=15,
            )
        draw.text(
                (36, 685),
                "00:00",
                (255, 255, 255),
                font=arial,
            )
        draw.text(
                (1185, 685),
                f"{duration[:23]}",
                (255, 255, 255),
                font=arial,
            )
        
        try:
            os.remove(f"cache/thumb{videoid}.png")
        except:
            pass

        background.save(f"cache/{videoid}_{user_id}.png")
        return f"cache/{videoid}_{user_id}.png"
    except Exception as e:
        LOGGER(__name__).error(f"error 3 {e}")
        return YOUTUBE_IMG_URL
