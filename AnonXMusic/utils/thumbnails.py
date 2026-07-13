import os
import re
import math
import asyncio

import aiofiles
import aiohttp
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from unidecode import unidecode
from ytSearch import VideosSearch

from AnonXMusic import app
from config import YOUTUBE_IMG_URL


# ─────────────────────────────────────────────────────────────────────────────
# BRAND COLOUR — Sony Music lime green (matches "Started Streaming" border)
# ─────────────────────────────────────────────────────────────────────────────
SONY_TEAL    = (0x00, 0xe5, 0x76)   # #00e576  bright lime green
SONY_TEAL_DK = (0x00, 0x9a, 0x4e)   # #009a4e  darker shade for glow base

# ─────────────────────────────────────────────────────────────────────────────
# FONT CACHE — loaded once at import, reused every call (saves RAM + time)
# ─────────────────────────────────────────────────────────────────────────────
_FONTS: dict = {}

def _load_fonts(scale: int) -> dict:
    key = scale
    if key in _FONTS:
        return _FONTS[key]
    try:
        f = {
            "bold":  ImageFont.truetype("AnonXMusic/assets/font2.ttf", 32 * scale),
            "badge": ImageFont.truetype("AnonXMusic/assets/font2.ttf", 18 * scale),
            "small": ImageFont.truetype("AnonXMusic/assets/font.ttf",  24 * scale),
            "dur":   ImageFont.truetype("AnonXMusic/assets/font.ttf",  22 * scale),
            "title": ImageFont.truetype("AnonXMusic/assets/font2.ttf", 28 * scale),
        }
    except Exception:
        default = ImageFont.load_default()
        f = {k: default for k in ("bold", "badge", "small", "dur", "title")}
    _FONTS[key] = f
    return f


# ─────────────────────────────────────────────────────────────────────────────
# UNCHANGED HELPERS (identical to original)
# ─────────────────────────────────────────────────────────────────────────────

def changeImageSize(maxWidth, maxHeight, image):
    widthRatio  = maxWidth  / image.size[0]
    heightRatio = maxHeight / image.size[1]
    newWidth    = int(widthRatio  * image.size[0])
    newHeight   = int(heightRatio * image.size[1])
    return image.resize((newWidth, newHeight), Image.LANCZOS)


def circle(img):
    img    = img.convert("RGBA")
    h, w   = img.size
    mask   = Image.new("L", (h, w), 0)
    ImageDraw.Draw(mask).ellipse([(0, 0), (h, w)], fill=255)
    result = Image.new("RGBA", (h, w), (0, 0, 0, 0))
    result.paste(img, mask=mask)
    return result


def clear(text, limit=45):
    words, title = text.split(" "), ""
    for w in words:
        if len(title) + len(w) < limit:
            title += " " + w
    return title.strip()


def get_dominant_color(img: Image.Image, n: int = 4) -> tuple:
    """Most vibrant dominant colour via mini k-means on a tiny 80×80 sample."""
    small   = img.convert("RGB").resize((80, 80))          # 80 not 120 — 2× faster
    arr     = np.array(small).reshape(-1, 3).astype(np.float32)
    rng     = np.random.default_rng(42)
    centers = arr[rng.choice(len(arr), n, replace=False)].copy()
    for _ in range(10):                                     # 10 iters not 12
        dists  = np.linalg.norm(arr[:, None] - centers[None], axis=2)
        labels = np.argmin(dists, axis=1)
        for k in range(n):
            pts = arr[labels == k]
            if len(pts):
                centers[k] = pts.mean(axis=0)
    best, best_sat = centers[0], 0.0
    for c in centers:
        r, g, b = c / 255.0
        mx, mn  = max(r, g, b), min(r, g, b)
        sat     = (mx - mn) / (mx + 1e-9)
        lum     = (mx + mn) / 2
        score   = sat * (1 - abs(lum - 0.5))
        if score > best_sat:
            best_sat, best = score, c
    return tuple(int(x) for x in best)


def build_palette(base: tuple) -> list:
    """Rainbow palette rotated to dominant colour — unchanged from original."""
    RAINBOW = [
        (0x1e, 0x90, 0xff), (0x06, 0xb6, 0xd4), (0x14, 0xb8, 0xa6),
        (0x22, 0xc5, 0x5e), (0xf5, 0x9e, 0x0b), (0xf9, 0x73, 0x16),
        (0xf4, 0x3f, 0x5e), (0xec, 0x48, 0x99), (0xa8, 0x55, 0xf7),
        (0xe2, 0xe8, 0xf0),
    ]
    br, bg, bb = base
    def dist(c):
        return math.sqrt(
            (c[0]-br)**2 * 0.299 + (c[1]-bg)**2 * 0.587 + (c[2]-bb)**2 * 0.114
        )
    best_idx = min(range(len(RAINBOW)), key=lambda i: dist(RAINBOW[i]))
    return RAINBOW[best_idx:] + RAINBOW[:best_idx]


def make_neon_glow_border(size, bbox, color, radius=30, stroke=6, glow_layers=10):
    """Single-colour neon border — always uses supplied `color` (SONY_TEAL)."""
    nr, ng, nb = color
    nr2 = min(255, nr + 30); ng2 = min(255, ng + 30); nb2 = min(255, nb + 30)

    layer           = Image.new("RGBA", size, (0, 0, 0, 0))
    x0, y0, x1, y1 = bbox
    ld              = ImageDraw.Draw(layer)

    for i in range(glow_layers, 0, -1):
        t      = i / glow_layers
        expand = int(t ** 0.5 * glow_layers * 4)
        alpha  = int(4 + (1 - t) ** 1.2 * 140)
        w      = stroke + int(t * glow_layers * 2)
        lx0, ly0 = max(0, x0-expand), max(0, y0-expand)
        lx1, ly1 = min(size[0], x1+expand), min(size[1], y1+expand)
        cr, cg, cb = (nr, ng, nb) if i % 2 == 0 else (nr2, ng2, nb2)
        ld.rounded_rectangle((lx0,ly0,lx1,ly1),
            radius=max(6, radius - expand//6), outline=(cr,cg,cb,alpha), width=w)

    for s in range(4, 0, -1):
        ld.rounded_rectangle((x0-s,y0-s,x1+s,y1+s), radius=radius,
            outline=(min(255,nr+60), min(255,ng+60), min(255,nb+60), 60+s*35),
            width=stroke+s)

    ld.rounded_rectangle(bbox, radius=radius,
        outline=(min(255,nr+90), min(255,ng+90), min(255,nb+90), 255), width=stroke)
    ld.rounded_rectangle(bbox, radius=radius,
        outline=(255,255,255,90), width=max(1, stroke//3))
    return layer


def draw_glowing_progress_bar(draw, canvas, x0, y0, x1, bar_h, thumb_frac, palette):
    """Neon progress bar — all original drawing logic, colour fixed to SONY_TEAL."""
    draw.rounded_rectangle([(x0,y0),(x1,y0+bar_h)],
        radius=bar_h//2, fill=(50,50,80,160))

    thumb_x  = int(x0 + (x1-x0) * thumb_frac)
    base_col = SONY_TEAL
    accent   = SONY_TEAL_DK

    for glow in range(6, 0, -1):
        gr,gg,gb = base_col
        ga   = int(15 + (6-glow)*18)
        gpad = glow * 2
        draw.rounded_rectangle(
            [(x0, y0-gpad//2),(thumb_x, y0+bar_h+gpad//2)],
            radius=bar_h//2+gpad//2,
            fill=(min(255,gr+60), min(255,gg+60), min(255,gb+60), ga))

    r1,g1,b1 = base_col; r2,g2,b2 = accent
    draw.rounded_rectangle([(x0,y0),(thumb_x,y0+bar_h)], radius=bar_h//2,
        fill=(min(255,r1+80), min(255,g1+80), min(255,b1+80), 240))
    draw.rounded_rectangle([(x0,y0),(thumb_x,y0+bar_h//3)], radius=bar_h//2,
        fill=(min(255,r2+100), min(255,g2+100), min(255,b2+100), 120))

    TR = 10
    cy = y0 + bar_h//2
    for glow in range(5, 0, -1):
        gr,gg,gb = accent
        ga  = int(20 + (5-glow)*25)
        gr_r = TR + glow*3
        draw.ellipse([(thumb_x-gr_r,cy-gr_r),(thumb_x+gr_r,cy+gr_r)],
            fill=(min(255,gr+80), min(255,gg+80), min(255,gb+80), ga))
    draw.ellipse([(thumb_x-TR,cy-TR),(thumb_x+TR,cy+TR)], fill=(255,255,255,250))
    draw.ellipse([(thumb_x-TR+3,cy-TR+3),(thumb_x+TR-3,cy+TR-3)],
        fill=(min(255,r2+100), min(255,g2+100), min(255,b2+100), 200))
    return thumb_x


# ─────────────────────────────────────────────────────────────────────────────
# USER DP FETCH  — correct Pyrogram / Telethon API, cached per user
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_user_dp(user_id) -> str | None:
    """
    Download the user's Telegram profile photo to cache/dp_{user_id}.jpg.
    Returns the file path, or None if not available.
    Caches for the session — if the file already exists we reuse it.
    """
    dp_path = f"cache/dp_{user_id}.jpg"
    if os.path.isfile(dp_path):
        return dp_path
    try:
        # Pyrogram: iter_profile_photos / get_chat_photos
        # Works for both User and Chat objects
        async for photo in app.get_chat_photos(user_id, limit=1):
            await app.download_media(photo.file_id, file_name=dp_path)
            return dp_path
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

async def get_thumb(videoid, user_id, title=None, duration=None, thumbnail=None,
                    views=None, channel=None):
    """
    Generate a Sony Music cinematic thumbnail.
    • All original fetch / cache / save logic preserved.
    • Fonts cached after first call — no repeated disk I/O.
    • Dominant colour computed on 80×80 crop (faster, same result).
    • User DP fetched via correct Pyrogram API and cached per user.
    """
    out_path = f"cache/{videoid}_{user_id}.png"
    if os.path.isfile(out_path):
        return out_path

    try:
        # ── 1. fetch song details ─────────────────────────────────────────────
        if not title or not thumbnail:
            url     = f"https://www.youtube.com/watch?v={videoid}"
            results = VideosSearch(url, limit=1)
            for result in (await results.next())["result"]:
                try:    title     = re.sub(r"\W+", " ", result["title"]).title()
                except: title     = "Unsupported Title"
                try:    duration  = result["duration"]
                except: duration  = "Unknown"
                thumbnail = result["thumbnails"][0]["url"].split("?")[0]
                try:    views     = result["viewCount"]["short"]
                except: views     = "Unknown Views"
                try:    channel   = result["channel"]["name"]
                except: channel   = "Unknown Channel"
        else:
            title    = re.sub(r"\W+", " ", str(title)).title()
            duration = duration or "Unknown"
            views    = views    or "Unknown Views"
            channel  = channel  or "Unknown Channel"

        # ── 2. download song thumbnail + user DP in parallel ──────────────────
        thumb_path = f"cache/thumb{videoid}.png"

        async def _dl_thumb():
            async with aiohttp.ClientSession() as session:
                async with session.get(thumbnail) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(thumb_path, "wb") as f:
                            await f.write(await resp.read())

        # run both downloads concurrently — saves ~0.3-0.8 s per call
        dp_path, _ = await asyncio.gather(
            _fetch_user_dp(user_id),
            _dl_thumb(),
        )

        # ── 3. open & enhance cover ───────────────────────────────────────────
        SCALE = 2
        W, H  = 1280 * SCALE, 720 * SCALE

        cover_raw = Image.open(thumb_path).convert("RGB")   # RGB saves ~25% RAM vs RGBA
        cover_raw = ImageEnhance.Sharpness(cover_raw).enhance(1.4)
        cover_raw = ImageEnhance.Color(cover_raw).enhance(1.3)
        cover_raw = cover_raw.convert("RGBA")               # convert once, keep as RGBA

        dominant      = get_dominant_color(cover_raw)
        palette       = build_palette(dominant)
        r_d, g_d, b_d = dominant

        fonts = _load_fonts(SCALE)
        font_bold  = fonts["bold"]
        font_badge = fonts["badge"]
        font_small = fonts["small"]
        font_dur   = fonts["dur"]
        font_title = fonts["title"]

        # ── 4. canvas + blurred background ───────────────────────────────────
        canvas = Image.new("RGBA", (W, H), (6, 6, 20, 255))

        # resize to canvas size at BILINEAR for the blurred bg (faster, quality same after blur)
        bg = cover_raw.resize((W, H), Image.BILINEAR).convert("RGBA")
        bg = bg.filter(ImageFilter.GaussianBlur(14))        # blur at 2× already, 14≈28/2
        bg = Image.alpha_composite(bg, Image.new("RGBA", (W, H), (0, 0, 0, 140)))
        canvas.alpha_composite(bg)
        del bg                                              # free immediately

        # vignette — built as a numpy array, no per-row Python loop
        vig_arr   = np.zeros((H, W, 4), dtype=np.uint8)
        rows      = np.arange(H, dtype=np.float32) / H
        alphas    = np.clip(160 * (1 - np.sin(rows * math.pi)) ** 1.5 + 30, 0, 255).astype(np.uint8)
        vig_arr[:, :, 3] = alphas[:, None]                  # broadcast across width
        vig_arr[:, :, :3] = [5, 5, 18]
        vig = Image.fromarray(vig_arr, "RGBA")
        canvas.alpha_composite(vig)
        del vig, vig_arr

        # teal corner glow blobs
        gb_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gbd    = ImageDraw.Draw(gb_img)
        gbd.ellipse([-80*SCALE, 80*SCALE, 500*SCALE, 560*SCALE],  fill=(*SONY_TEAL, 16))
        gbd.ellipse([W-480*SCALE,-40*SCALE,W+80*SCALE,380*SCALE], fill=(*SONY_TEAL, 12))
        gb_img = gb_img.filter(ImageFilter.GaussianBlur(40))
        canvas.alpha_composite(gb_img)
        del gb_img

        draw = ImageDraw.Draw(canvas)

        # ── 5. TOP BAR ────────────────────────────────────────────────────────
        TOP_H = 90 * SCALE
        canvas.alpha_composite(Image.new("RGBA", (W, TOP_H), (0, 0, 0, 110)), (0, 0))

        # bottom glow line
        tl  = Image.new("RGBA", (W, 4*SCALE), (0, 0, 0, 0))
        tld = ImageDraw.Draw(tl)
        for i in range(4*SCALE, 0, -1):
            tld.line([(0,4*SCALE-i),(W,4*SCALE-i)], fill=(*SONY_TEAL,30+i*20), width=1)
        canvas.alpha_composite(tl, (0, TOP_H - 4*SCALE))
        del tl

        # NOW PLAYING pill (top-left)
        np_text = "▶  NOW  PLAYING"
        try:    np_tw = int(font_badge.getlength(np_text))
        except: np_tw = len(np_text) * 11 * SCALE
        np_w, np_h = np_tw + 40*SCALE, 50*SCALE
        np_x, np_y = 40*SCALE, (TOP_H - np_h)//2
        np_img = Image.new("RGBA", (np_w, np_h), (0, 0, 0, 0))
        ImageDraw.Draw(np_img).rounded_rectangle(
            [(0,0),(np_w,np_h)], radius=np_h//2,
            fill=(0,60,54,210), outline=(*SONY_TEAL,220), width=3*SCALE//2)
        canvas.alpha_composite(np_img, (np_x, np_y))
        draw.text((np_x+20*SCALE, np_y+(np_h-font_badge.size)//2),
                  np_text, fill=(230,255,252,245), font=font_badge)

        # Sony Music pill + EQ bars (top-right)
        bot_name = unidecode(app.name)[:18]
        try:    bt_w = int(font_badge.getlength(bot_name))
        except: bt_w = len(bot_name) * 11 * SCALE
        eq_unit, eq_gap, eq_max, eq_count = 10*SCALE, 5*SCALE, 34*SCALE, 5
        eq_total  = eq_count * (eq_unit + eq_gap)
        pill2_w   = eq_total + 10*SCALE + bt_w + 30*SCALE
        pill2_h   = 50*SCALE
        pill2_x   = W - pill2_w - 40*SCALE
        pill2_y   = (TOP_H - pill2_h)//2
        pill2     = Image.new("RGBA", (pill2_w, pill2_h), (0, 0, 0, 0))
        ImageDraw.Draw(pill2).rounded_rectangle(
            [(0,0),(pill2_w,pill2_h)], radius=pill2_h//2,
            fill=(0,60,54,210), outline=(*SONY_TEAL,220), width=3*SCALE//2)
        canvas.alpha_composite(pill2, (pill2_x, pill2_y))
        eq_bx = pill2_x + 14*SCALE
        eq_by = pill2_y + (pill2_h - eq_max)//2
        for i, h_frac in enumerate([0.50, 0.90, 0.45, 0.75, 0.55]):
            bh2 = int(eq_max * h_frac)
            bxp = eq_bx + i*(eq_unit+eq_gap)
            draw.rounded_rectangle(
                [(bxp, eq_by+eq_max-bh2),(bxp+eq_unit, eq_by+eq_max)],
                radius=eq_unit//2, fill=(*SONY_TEAL,230))
        draw.text((eq_bx+eq_total+10*SCALE, eq_by+(eq_max-font_badge.size)//2+2*SCALE),
                  bot_name, fill=(230,255,252,245), font=font_badge)

        # ── 6. SONG COVER RECTANGLE ───────────────────────────────────────────
        MARGIN = 80*SCALE
        RW, RH = W - MARGIN*2, 310*SCALE
        RX, RY = MARGIN, TOP_H + 28*SCALE

        cover_sq = cover_raw.resize((RW, RH), Image.LANCZOS).convert("RGBA")
        cover_sq = ImageEnhance.Sharpness(cover_sq).enhance(1.5)
        cover_sq = ImageEnhance.Contrast(cover_sq).enhance(1.1)
        rc_mask  = Image.new("L", (RW, RH), 0)
        ImageDraw.Draw(rc_mask).rounded_rectangle([(0,0),(RW,RH)], radius=22*SCALE, fill=255)
        cover_sq.putalpha(rc_mask)

        sh_w, sh_h = RW+80*SCALE, RH+80*SCALE
        shadow = Image.new("RGBA", (sh_w, sh_h), (0,0,0,0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            [(24*SCALE,24*SCALE),(sh_w-24*SCALE,sh_h-24*SCALE)],
            radius=30*SCALE, fill=(r_d//2, g_d//2, b_d//2, 180))
        shadow = shadow.filter(ImageFilter.GaussianBlur(11))
        canvas.alpha_composite(shadow, (RX-40*SCALE, RY-40*SCALE))
        canvas.alpha_composite(cover_sq, (RX, RY))
        del shadow, cover_sq

        ring_layer = make_neon_glow_border(
            (W,H), (RX,RY,RX+RW,RY+RH),
            SONY_TEAL, radius=22*SCALE, stroke=5*SCALE, glow_layers=10)
        canvas.alpha_composite(ring_layer)
        del ring_layer

        canvas.alpha_composite(Image.new("RGBA",(RW,RH),(0,0,0,55)), (RX,RY))

        # ── 7. USER DP CIRCLE ─────────────────────────────────────────────────
        DP_R  = 88 * SCALE
        DP_CX = W // 2
        DP_CY = RY + RH          # bottom edge of cover rect

        # open user DP — guaranteed to be the user's photo, not cover
        if dp_path and os.path.isfile(dp_path):
            dp_src = Image.open(dp_path).convert("RGBA")
        else:
            # fallback: plain teal circle with musical note — not the cover
            dp_src = Image.new("RGBA", (DP_R*2, DP_R*2), (*SONY_TEAL, 255))
            ImageDraw.Draw(dp_src).text(
                (DP_R//2, DP_R//2), "♪", fill=(255,255,255,220),
                font=font_title)

        # shadow
        dp_sh = Image.new("RGBA", (W, H), (0,0,0,0))
        ImageDraw.Draw(dp_sh).ellipse(
            [DP_CX-DP_R-12*SCALE, DP_CY-DP_R-12*SCALE,
             DP_CX+DP_R+12*SCALE, DP_CY+DP_R+12*SCALE],
            fill=(0,0,0,130))
        dp_sh = dp_sh.filter(ImageFilter.GaussianBlur(7))
        canvas.alpha_composite(dp_sh)
        del dp_sh

        # paste as circle
        dp_size = DP_R * 2
        dp_img  = dp_src.resize((dp_size, dp_size), Image.LANCZOS).convert("RGBA")
        dp_img  = ImageEnhance.Sharpness(dp_img).enhance(1.5)
        dp_mask = Image.new("L", (dp_size, dp_size), 0)
        ImageDraw.Draw(dp_mask).ellipse([(0,0),(dp_size,dp_size)], fill=255)
        dp_img.putalpha(dp_mask)
        canvas.alpha_composite(dp_img, (DP_CX-DP_R, DP_CY-DP_R))
        del dp_img, dp_src

        # neon teal glow ring around DP
        dp_ring = Image.new("RGBA", (W, H), (0,0,0,0))
        dprd    = ImageDraw.Draw(dp_ring)
        for i in range(10, 0, -1):
            exp = i * 3
            dprd.ellipse(
                [DP_CX-DP_R-exp, DP_CY-DP_R-exp, DP_CX+DP_R+exp, DP_CY+DP_R+exp],
                outline=(*SONY_TEAL, 8+i*14), width=4*SCALE+i)
        dprd.ellipse([DP_CX-DP_R,DP_CY-DP_R,DP_CX+DP_R,DP_CY+DP_R],
                     outline=(*SONY_TEAL,230), width=4*SCALE)
        dprd.ellipse([DP_CX-DP_R,DP_CY-DP_R,DP_CX+DP_R,DP_CY+DP_R],
                     outline=(255,255,255,80), width=2*SCALE)
        canvas.alpha_composite(dp_ring)
        del dp_ring

        # ── 8. BOTTOM INFO ────────────────────────────────────────────────────
        INFO_Y = DP_CY + DP_R + 18*SCALE

        # song title — centred
        title_text = clear(title, 42)
        try:    tw = int(font_title.getlength(title_text))
        except: tw = len(title_text) * 16 * SCALE
        draw.text(((W-tw)//2, INFO_Y), title_text, fill=(255,255,255,255), font=font_title)

        # "Played by" — centred
        sub_text = f"Played by: {unidecode(app.name)}  ·  {channel[:28]}"
        try:    sw = int(font_small.getlength(sub_text))
        except: sw = len(sub_text) * 13 * SCALE
        draw.text(((W-sw)//2, INFO_Y+44*SCALE), sub_text, fill=(175,180,215,195), font=font_small)

        # progress bar (lifted — INFO_Y+92 not +116)
        PROG_X0  = 120*SCALE
        PROG_X1  = W - 120*SCALE
        BAR_H_PX = 8*SCALE
        PROG_Y   = INFO_Y + 92*SCALE
        TIME_Y   = PROG_Y + BAR_H_PX + 8*SCALE

        draw_glowing_progress_bar(draw, canvas, PROG_X0, PROG_Y, PROG_X1,
                                  BAR_H_PX, thumb_frac=0.65, palette=palette)

        draw.text((PROG_X0, TIME_Y), "00:00", fill=(195,200,230,210), font=font_dur)
        draw.text((PROG_X1-74*SCALE, TIME_Y), duration[:7], fill=(195,200,230,210), font=font_dur)

        # outer card border
        border_layer = make_neon_glow_border(
            (W,H), (6*SCALE,6*SCALE,W-6*SCALE,H-6*SCALE),
            SONY_TEAL, radius=30*SCALE, stroke=5*SCALE, glow_layers=12)
        canvas.alpha_composite(border_layer)
        del border_layer

        # ── 9. downsample + save ──────────────────────────────────────────────
        final = canvas.convert("RGB").resize((1280, 720), Image.LANCZOS)
        del canvas

        try:    os.remove(thumb_path)
        except: pass

        final.save(out_path, quality=97, optimize=False)
        del final
        return out_path

    except Exception:
        return YOUTUBE_IMG_URL
