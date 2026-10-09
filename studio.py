"""Studio style: a clean studio background (dark and light scenes), real pictures as floating cards, captions at the
top (spoken words appear one by one, the key word in a highlight box) and smooth motion on every shot.
Inspired by hand-animated explainer reels. Every frame is drawn here in Python and piped to ffmpeg."""
import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter

import video as V

W, H, FPS = V.W, V.H, V.FPS
ACCENT = V.ACCENT
CARD_TOP, CARD_BOTTOM, CARD_W = 470, 1700, 930   # the picture area; captions live above it
CAP_Y0, CAP_H = 150, 320                          # caption strip (top of the screen)
THEMES = {
    "dark": {"bg": (11, 12, 16), "glow": (30, 32, 42), "fg": (250, 250, 252), "muted": (104, 107, 118),
             "shadow": 175, "box": (123, 154, 248, 70), "line": (40, 42, 52)},
    "light": {"bg": (241, 241, 244), "glow": (255, 255, 255), "fg": (16, 17, 22), "muted": (158, 160, 170),
              "shadow": 60, "box": (123, 154, 248, 55), "line": (226, 227, 232)},
}


def theme_for(beat_index):
    """Two dark scenes, then two light ones: the look of a studio explainer."""
    return "light" if beat_index % 4 in (2, 3) else "dark"


def ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_back(x):
    """Ease out with a tiny overshoot: things land with a soft bounce."""
    x = max(0.0, min(1.0, x))
    c = 1.4
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


# ---------------------------------------------------------------- building blocks
_BG = {}


def background(theme):
    """Solid studio colour with a soft light in the middle and the handle at the bottom."""
    if theme not in _BG:
        t = THEMES[theme]
        small = Image.new("RGB", (54, 96), t["bg"])
        px = small.load()
        for y in range(96):
            for x in range(54):
                d = (((x - 27) / 27) ** 2 + ((y - 50) / 40) ** 2) ** 0.5
                a = max(0.0, 1 - d) ** 1.6
                px[x, y] = tuple(int(t["bg"][i] + (t["glow"][i] - t["bg"][i]) * a) for i in range(3))
        img = small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(8))
        if V.HANDLE:
            d = ImageDraw.Draw(img)
            d.text((W / 2, 1838), "@" + V.HANDLE.lstrip("@"), font=V.font(30, semi=True), fill=t["muted"], anchor="mm")
        _BG[theme] = img.convert("RGBA")
    return _BG[theme].copy()


def rounded(img, radius):
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=radius, fill=255)
    img.putalpha(Image.composite(img.getchannel("A"), mask, mask))
    return img


def sprite(img, theme, max_w=CARD_W, max_h=CARD_BOTTOM - CARD_TOP - 90, radius=34, pad=70, fill=None):
    """A picture as a floating card: rounded corners, soft shadow. Returns an RGBA image with `pad` around the card."""
    img = img.convert("RGBA")
    if fill:  # cover the box exactly (crop), else fit inside it
        s = max(fill[0] / img.width, fill[1] / img.height)
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
        x, y = (img.width - fill[0]) // 2, (img.height - fill[1]) // 3
        img = img.crop((x, y, x + fill[0], y + fill[1]))
    else:
        s = min(max_w / img.width, max_h / img.height)
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    card = rounded(img, radius)
    out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 22, pad + card.width, pad + card.height + 22], radius=radius,
                                         fill=(0, 0, 0, THEMES[theme]["shadow"]))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)))
    if theme == "light":  # a hairline edge so white pictures don't melt into the background
        ImageDraw.Draw(out).rounded_rectangle([pad - 1, pad - 1, pad + card.width, pad + card.height], radius=radius,
                                              outline=(0, 0, 0, 28), width=2)
    out.alpha_composite(card, (pad, pad))
    return out


def place(frame, spr, cx, cy, scale=1.0, alpha=1.0):
    if alpha <= 0.01 or scale <= 0.01:
        return
    s = spr
    if abs(scale - 1) > 0.002:
        s = spr.resize((max(1, round(spr.width * scale)), max(1, round(spr.height * scale))), Image.BILINEAR)
    if alpha < 0.99:
        s = s.copy()
        s.putalpha(s.getchannel("A").point(lambda a: int(a * alpha)))
    frame.alpha_composite(s, (round(cx - s.width / 2), round(cy - s.height / 2)))


def select_box(d, box, theme):
    """The highlight around a key word: tinted fill, thin blue line, small handles on the corners."""
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=6, fill=THEMES[theme]["box"], outline=(*ACCENT, 255), width=3)
    for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        d.rectangle([cx - 6, cy - 6, cx + 6, cy + 6], fill=(255, 255, 255, 255), outline=(*ACCENT, 255), width=3)


def write_frames(out, frames, draw, alpha=False, size=(W, H)):
    """draw(k) → PIL image for frame k; frames are piped straight into ffmpeg (no files)."""
    if alpha:
        enc = ["-c:v", "qtrle", "-pix_fmt", "argb", "-r", str(FPS)]
    else:
        enc = V.encode_args()
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba" if alpha else "rgb24",
                          "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-", *enc, out],
                         stdin=subprocess.PIPE)
    last_key, last_bytes = object(), b""
    try:
        for k in range(int(frames)):
            img = draw(k)
            if isinstance(img, tuple):  # (cache key, image or None): unchanged frames are reused
                key, img = img
                if key == last_key:
                    p.stdin.write(last_bytes)
                    continue
                last_key = key
            last_bytes = (img if alpha else img.convert("RGB")).tobytes()
            p.stdin.write(last_bytes)
    finally:
        p.stdin.close()
        p.wait()
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed writing {os.path.basename(out)}")
    return out


def fit_font(text, size, max_w, semi=False, min_size=40):
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while size > min_size and probe.textlength(text, font=V.font(size, semi)) > max_w:
        size -= 4
    return V.font(size, semi)


# ---------------------------------------------------------------- shots
CARD_CY = (CARD_TOP + CARD_BOTTOM) // 2 - 20

# the same picture shown again in a beat is reframed (a punch-in to another part), so it reads as a new shot
CROPS = [(0.15, 0.10, 0.70), (0.30, 0.24, 0.66), (0.04, 0.28, 0.66), (0.13, 0.02, 0.74)]


def picture_shot(out, frames, img, theme, credit="", reframe=0, style=0):
    if reframe:
        x, y, s = CROPS[(reframe - 1) % len(CROPS)]
        img = img.crop((int(img.width * x), int(img.height * y), int(img.width * (x + s)), int(img.height * (y + s))))
    spr = sprite(img, theme)
    bg = background(theme)
    if credit:
        d = ImageDraw.Draw(bg)
        d.text((W / 2, CARD_CY + (spr.height - 140) / 2 + 52), credit[:60], font=V.font(26, semi=True),
               fill=THEMES[theme]["muted"], anchor="mm")
    push = (1, -1)[style % 2]

    def draw(k):
        t = k / FPS + 0.05
        p = ease(t / 0.45)
        frame = bg.copy()
        scale = 0.9 + 0.1 * ease_back(t / 0.5) + push * 0.035 * (k / max(1, frames))
        place(frame, spr, W / 2, CARD_CY + 80 * (1 - p), scale, p)
        return frame
    return write_frames(out, frames, draw)


_MASKS = {}


def clip_shot(out, frames, src, theme, offset=0.0):
    """Stock video inside a rounded card that slides up into place."""
    cw, ch = CARD_W, 1080
    bg_png = os.path.join(os.path.dirname(out), f"studio_bg_{theme}.png")
    if not os.path.exists(bg_png):
        bg = background(theme)
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        y0 = CARD_CY - ch // 2
        ImageDraw.Draw(sh).rounded_rectangle([(W - cw) // 2, y0 + 22, (W + cw) // 2, y0 + ch + 22], radius=34,
                                             fill=(0, 0, 0, THEMES[theme]["shadow"]))
        bg.alpha_composite(sh.filter(ImageFilter.GaussianBlur(26)))
        bg.convert("RGB").save(bg_png)
    mask_png = os.path.join(os.path.dirname(out), "studio_clip_mask.png")
    if not os.path.exists(mask_png):
        m = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=34, fill=255)
        m.save(mask_png)
    y0 = CARD_CY - ch // 2
    graph = (f"[1:v]fps={FPS},scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},"
             f"eq=saturation=1.08:contrast=1.04,format=rgba[c];[2:v]format=gray[m];[c][m]alphamerge,"
             f"fade=t=in:st=0:d=0.3:alpha=1[card];"
             f"[0:v][card]overlay=x=(W-w)/2:y='{y0}+80*pow(1-min(t/0.45\\,1)\\,3)'[v]")
    V.sh(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", bg_png, "-stream_loop", "-1",
          "-ss", f"{offset:.2f}", "-i", src, "-loop", "1", "-i", mask_png, "-filter_complex", graph,
          "-map", "[v]", "-frames:v", str(int(frames)), *V.encode_args(), out])
    return out


def stat_shot(out, frames, big, small, theme):
    """A big number that counts up, with its meaning underneath."""
    t_ = THEMES[theme]
    m = re.match(r"^([^\d]*)(\d[\d,]*\.?\d*)(.*)$", big.strip())
    fnt = fit_font(big, 300, W - 160)
    bg = background(theme)
    probe = ImageDraw.Draw(bg)
    label = V.wrap(probe, small, V.font(62, semi=True), W - 200)[:2]
    ny = CARD_CY - 170

    def text_for(p):
        if not m:
            return big
        prefix, num, suffix = m.groups()
        value = float(num.replace(",", ""))
        dec = len(num.split(".")[1]) if "." in num else 0
        v = value * p
        body = f"{v:,.{dec}f}" if "," in num else f"{v:.{dec}f}"
        return f"{prefix}{body}{suffix}" if p < 1 else big

    def draw(k):
        tt = k / FPS + 0.05
        p = ease(tt / 0.9)
        frame = bg.copy()
        d = ImageDraw.Draw(frame)
        d.text((W / 2, ny), text_for(p), font=fnt, fill=ACCENT, anchor="mm")
        bar = ease((tt - 0.25) / 0.6)
        if bar > 0:
            bw = 360 * bar
            d.rounded_rectangle([W / 2 - bw / 2, ny + fnt.size * 0.62, W / 2 + bw / 2, ny + fnt.size * 0.62 + 10],
                                radius=5, fill=(*ACCENT, 255))
        q = ease((tt - 0.35) / 0.5)
        if q > 0:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            y = ny + fnt.size * 0.62 + 70 + 30 * (1 - q)
            for line in label:
                ld.text((W / 2, y), line, font=V.font(62, semi=True), fill=(*t_["fg"], int(255 * q)), anchor="ma")
                y += 80
            frame.alpha_composite(layer)
        return (round(p, 3), round(bar, 3), round(q, 3)), frame
    return write_frames(out, frames, draw)


def person_shot(out, frames, face, name, role, theme, credit=""):
    t_ = THEMES[theme]
    size = 560
    if face is not None:
        sq = V.portrait_square(face.convert("RGB"), size)
        ring = Image.new("RGBA", (size + 20, size + 20), (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle([0, 0, size + 19, size + 19], radius=70, fill=(255, 255, 255, 255))
        ring.alpha_composite(rounded(sq, 62), (10, 10))
        spr = sprite(ring, theme, max_w=size + 20, max_h=size + 20, radius=70)
    else:  # no trustworthy photo: initials, never someone else's face
        ini = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        dd = ImageDraw.Draw(ini)
        dd.ellipse([0, 0, size - 1, size - 1], fill=(*ACCENT, 255))
        dd.text((size / 2, size / 2), "".join(w[0] for w in name.split()[:2]).upper(), font=V.font(220),
                fill=(15, 20, 48), anchor="mm")
        spr = ini
    bg = background(theme)
    cy = CARD_CY - 150
    name_f = fit_font(name, 84, W - 140)

    def draw(k):
        tt = k / FPS + 0.05
        frame = bg.copy()
        p = ease_back(tt / 0.5)
        place(frame, spr, W / 2, cy, 0.85 + 0.15 * p + 0.02 * (k / max(1, frames)), ease(tt / 0.3))
        q = ease((tt - 0.25) / 0.45)
        if q > 0:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            y = cy + size / 2 + 70 + 30 * (1 - q)
            ld.text((W / 2, y), name, font=name_f, fill=(*t_["fg"], int(255 * q)), anchor="ma")
            if role:
                rf = V.font(44, semi=True)
                tw = ld.textlength(role[:48], font=rf)
                yy = y + name_f.size + 40
                ld.rounded_rectangle([W / 2 - tw / 2 - 30, yy, W / 2 + tw / 2 + 30, yy + 72], radius=36,
                                     fill=(*ACCENT, int(255 * q)))
                ld.text((W / 2, yy + 36), role[:48], font=rf, fill=(12, 14, 30, int(255 * q)), anchor="mm")
            if credit and face is not None:
                ld.text((W / 2, 1720), credit[:60], font=V.font(26, semi=True), fill=(*t_["muted"], int(255 * q)),
                        anchor="mm")
            frame.alpha_composite(layer)
        return frame
    return write_frames(out, frames, draw)


def article_card(outlet, headline, domain="", date="", logo=None):
    """A white article card, like a screenshot of the source page."""
    cw = 900
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    hf = V.font(60)
    lines = V.wrap(probe, headline, hf, cw - 120)[:4]
    ch = 200 + len(lines) * 78 + 230
    card = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))
    d = ImageDraw.Draw(card)
    x = 60
    if logo is not None:
        lg = logo.convert("RGBA")
        lg.thumbnail((64, 64), Image.LANCZOS)
        card.alpha_composite(lg, (x, 62 - lg.height // 2 + 20))
        x += 84
    d.text((x, 82), (outlet or domain)[:34], font=V.font(40), fill=(18, 18, 24), anchor="lm")
    if date:
        d.text((cw - 60, 82), date, font=V.font(30, semi=True), fill=(140, 142, 152), anchor="rm")
    d.line([60, 150, cw - 60, 150], fill=(232, 233, 238), width=3)
    y = 190
    for line in lines:
        d.text((60, y), line, font=hf, fill=(16, 16, 22))
        y += 78
    y += 40
    for wfrac in (1.0, 0.93, 0.97, 0.6):  # the article's body, as soft grey lines
        d.rounded_rectangle([60, y, 60 + (cw - 120) * wfrac, y + 18], radius=9, fill=(232, 233, 238))
        y += 42
    if domain:
        d.text((60, ch - 40), domain, font=V.font(28, semi=True), fill=(150, 152, 162), anchor="lm")
    return card


def source_shot(out, frames, outlet, headline, domain, theme, date="", logo=None):
    spr = sprite(article_card(outlet, headline, domain, date, logo), theme, radius=28)
    bg = background(theme)

    def draw(k):
        tt = k / FPS + 0.05
        p = ease(tt / 0.5)
        frame = bg.copy()
        place(frame, spr, W / 2, CARD_CY + 120 * (1 - p), 0.96 + 0.04 * p + 0.025 * (k / max(1, frames)), p)
        return frame
    return write_frames(out, frames, draw)


def logo_shot(out, frames, name, domain, theme, logo=None):
    t_ = THEMES[theme]
    tile = Image.new("RGBA", (440, 440), (255, 255, 255, 255))
    if logo is not None:
        lg = logo.convert("RGBA")
        lg.thumbnail((300, 300), Image.LANCZOS)
        tile.alpha_composite(lg, ((440 - lg.width) // 2, (440 - lg.height) // 2))
    else:
        ImageDraw.Draw(tile).text((220, 220), name[:1].upper(), font=V.font(220), fill=(20, 20, 28), anchor="mm")
    spr = sprite(tile, theme, max_w=440, max_h=440, radius=100)
    bg = background(theme)
    nf = fit_font(name, 90, W - 140)
    cy = CARD_CY - 120

    def draw(k):
        tt = k / FPS + 0.05
        frame = bg.copy()
        place(frame, spr, W / 2, cy, 0.7 + 0.3 * ease_back(tt / 0.5) + 0.02 * (k / max(1, frames)), ease(tt / 0.3))
        q = ease((tt - 0.25) / 0.4)
        if q > 0:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(layer).text((W / 2, cy + 330 + 30 * (1 - q)), name, font=nf,
                                       fill=(*t_["fg"], int(255 * q)), anchor="ma")
            frame.alpha_composite(layer)
        return frame
    return write_frames(out, frames, draw)


def statement_shot(out, frames, tag, theme):
    """The line's key fact in big type, words popping in one by one, the key word in a highlight box."""
    t_ = THEMES[theme]
    bg = background(theme)
    probe = ImageDraw.Draw(bg)
    size = 150
    while size > 80 and len(V.wrap(probe, tag, V.font(size), W - 160)) > 2:
        size -= 8
    fnt = V.font(size)
    lines = V.wrap(probe, tag, fnt, W - 160)[:3]
    words = tag.split()
    key = key_word_index(words)
    key_word = words[key] if key is not None else None
    y0 = CARD_CY - len(lines) * size * 0.62

    def draw(k):
        tt = k / FPS + 0.05
        frame = bg.copy()
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        y, n, boxed = y0, 0, False
        for line in lines:
            lw = d.textlength(line, font=fnt) + (24 if key_word and key_word in line.split() else 0)
            x = W / 2 - lw / 2
            for word in line.split():
                q = ease((tt - 0.06 - n * 0.09) / 0.3)
                ww = d.textlength(word, font=fnt)
                if q > 0:
                    dy = 40 * (1 - q)
                    if not boxed and word == key_word and q > 0.5:
                        boxed = True
                        select_box(d, (x - 8, y + dy - 6, x + ww + 16, y + dy + size * 1.08), theme)
                    d.text((x + (4 if word == key_word else 0), y + dy), word, font=fnt,
                           fill=(*(ACCENT if word == key_word else t_["fg"]), int(255 * q)))
                x += ww + d.textlength(" ", font=fnt) + (24 if word == key_word else 0)
                n += 1
            y += int(size * 1.2)
        bar = ease((tt - 0.3) / 0.5)
        if bar > 0:
            d.rounded_rectangle([W / 2 - 160 * bar, y + 30, W / 2 + 160 * bar, y + 40], radius=5, fill=(*ACCENT, 255))
        s = 1 + 0.03 * (k / max(1, frames))
        if s > 1.001:
            layer = layer.resize((round(W * s), round(H * s)), Image.BILINEAR).crop(
                (round((W * s - W) / 2), round((H * s - H) / 2), round((W * s - W) / 2) + W, round((H * s - H) / 2) + H))
        frame.alpha_composite(layer)
        return frame
    return write_frames(out, frames, draw)


def key_word_index(words):
    """Which word of a line deserves the highlight: a number first, else a name (capitalised, not the first word)."""
    for i, w in enumerate(words):
        if re.search(r"\d", w):
            return i
    for i, w in enumerate(words):
        if i > 0 and w[:1].isupper() and len(re.sub(r"\W", "", w)) > 2:
            return i
    return 0 if words and words[0][:1].isupper() and len(words[0]) > 2 else None


def hook_shot(out, frames, hook, label, img=None, theme="dark"):
    """Opening: the source label, the headline popping in line by line (key word highlighted), the picture below."""
    t_ = THEMES[theme]
    bg = background(theme)
    probe = ImageDraw.Draw(bg)
    size = 104
    while size > 64 and len(V.wrap(probe, hook, V.font(size), W - 140)) > 3:
        size -= 6
    fnt = V.font(size)
    lines = V.wrap(probe, hook, fnt, W - 140)
    words_all = hook.split()
    key = key_word_index(words_all)
    key_word = words_all[key] if key is not None else None
    top = 330
    text_end = top + len(lines) * int(size * 1.2)
    pic_top = text_end + 60
    spr = sprite(img, theme, max_h=CARD_BOTTOM - pic_top - 20, max_w=CARD_W) if img is not None else None
    lf = V.font(36, semi=True)

    def draw(k):
        tt = k / FPS + 0.05
        frame = bg.copy()
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        a = ease(tt / 0.3)
        tw = d.textlength(label, font=lf)
        x = W / 2 - (tw + 34) / 2
        d.ellipse([x, 230 - 11, x + 22, 230 + 11], fill=(*ACCENT, int(255 * a)))
        d.text((x + 34, 230), label, font=lf, fill=(*t_["muted"], int(255 * a)), anchor="lm")
        y = top
        boxed = False
        for li, line in enumerate(lines):
            q = ease((tt - 0.12 - li * 0.14) / 0.35)
            if q > 0:
                yy = y + 36 * (1 - q)
                lw = d.textlength(line, font=fnt)
                xx = W / 2 - lw / 2
                for wi, word in enumerate(line.split()):
                    ww = d.textlength(word, font=fnt)
                    if not boxed and key_word and word == key_word:
                        boxed = True
                        if q > 0.6:
                            select_box(d, (xx - 14, yy - 4, xx + ww + 14, yy + size * 1.08), theme)
                    d.text((xx, yy), word, font=fnt, fill=(*t_["fg"], int(255 * q)))
                    xx += ww + d.textlength(" ", font=fnt) + (18 if word == key_word else 0)
            y += int(size * 1.2)
        frame.alpha_composite(layer)
        if spr is not None:
            p = ease((tt - 0.3) / 0.5)
            place(frame, spr, W / 2, pic_top + (spr.height - 140) / 2 + 90 * (1 - p),
                  0.94 + 0.06 * p + 0.02 * (k / max(1, frames)), p)
        return frame
    return write_frames(out, frames, draw)


# ---------------------------------------------------------------- captions at the top
def _norm(t):
    return re.sub(r"[^a-z0-9]", "", str(t).lower())


def caption_track(out, words, total, hook_until, theme_at, keywords=()):
    """A transparent caption strip with the whole sentence on screen (up to 3 lines), so viewers can read a complete
    thought: words light up from grey to full colour as they're spoken, the key word (a number or a name) gets a
    highlight box once it's said."""
    stop = {"the", "and", "for", "of", "a", "an", "in", "on", "at", "to", "with", "by", "from", "inc", "ltd"}
    keys = {_norm(k) for kw in keywords for k in str(kw).split()
            if len(_norm(k)) > 2 and _norm(k) not in stop and (k[:1].isupper() or re.search(r"\d", k))}
    chunks = V.chunk_words(words, max_words=16, max_chars=95, sentence_breaks=".!?")
    events = []
    for ci, ch in enumerate(chunks):
        nxt = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else total
        chunk_end = nxt if nxt - ch[-1]["end"] < 0.6 else ch[-1]["end"] + 0.5
        texts = [V.ass_text(w["text"], False) for w in ch]
        key = next((i for i, w in enumerate(texts) if re.search(r"\d", w)),
                   next((i for i, w in enumerate(texts) if w[:1].isupper() and _norm(w) in keys), None))
        first = max(ch[0]["start"], hook_until)
        if chunk_end <= first:
            continue
        events.append((first, ch[0]["start"], texts, key, -1, ci))  # (the sentence shows a hair before its first word)
        for wi, w in enumerate(ch):
            start = max(w["start"], hook_until)
            end = ch[wi + 1]["start"] if wi + 1 < len(ch) else chunk_end
            if end > start:
                events.append((start, end, texts, key, wi, ci))
    events = [e for e in events if e[1] > e[0]]
    cache = {}

    def layout(texts, key):
        probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        for size in (56, 50, 44):
            f = V.font(size, semi=True)
            sp = probe.textlength(" ", font=f)
            widths = [probe.textlength(w, font=f) + (18 if i == key else 0) for i, w in enumerate(texts)]
            lines, cur, cw = [], [], 0
            for i, w in enumerate(widths):
                if cur and cw + sp + w > W - 150:
                    lines.append(cur)
                    cur, cw = [], 0
                cur.append(i)
                cw += (sp if len(cur) > 1 else 0) + w
            lines.append(cur)
            if len(lines) <= 3:
                break
        return f, sp, widths, lines, int(size * 1.32)

    def strip(texts, key, wi, theme):
        t_ = THEMES[theme]
        img = Image.new("RGBA", (W, CAP_H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        f, sp, widths, lines, lh = layout(texts, key)
        y = CAP_H / 2 - (len(lines) * lh) / 2 + 4
        upcoming = (*t_["muted"], 150)
        for line in lines:
            lw = sum(widths[i] for i in line) + sp * (len(line) - 1)
            x = W / 2 - lw / 2
            for i in line:
                said = i <= wi
                if i == key:
                    if said:
                        select_box(d, (x - 2, y - 4, x + widths[i] - 2, y + lh - 6), theme)
                    x += 9
                d.text((x, y), texts[i], font=f, fill=(*t_["fg"], 255) if said else upcoming)
                x += widths[i] + sp - (9 if i == key else 0)
            y += lh
        return img

    blank = Image.new("RGBA", (W, CAP_H), (0, 0, 0, 0))
    ev = 0

    def draw(k):
        nonlocal ev
        t = k / FPS + 0.05
        while ev < len(events) and events[ev][1] <= t:
            ev += 1
        if ev < len(events) and events[ev][0] <= t:
            s, e, texts, key, wi, ci = events[ev]
            theme = theme_at(t)
            ck = (ci, wi, theme)
            if ck not in cache:
                cache.clear()
                cache[ck] = strip(texts, key, wi, theme)
            return ck, cache[ck]
        return "blank", blank
    return write_frames(out, int(round(total * FPS)), draw, alpha=True, size=(W, CAP_H))


# ---------------------------------------------------------------- the whole video track
def build_track(beats, times, plan, hook, hook_len, total, tmp):
    """Like video.build_video_track, in the studio style. hook = (text, label, PIL image or None).
    Returns (concat list file, cut times, theme_at function)."""
    segments, pos, n = [], 0, 0
    spans = []  # (start, end, theme)

    def add(fn, end_time, theme, *args, **kw):
        nonlocal pos, n
        frames = int(round(end_time * FPS)) - pos
        if frames < 1:
            return
        out = os.path.join(tmp, f"st{n:03d}.mp4")
        n += 1
        fn(out, frames, *args, **kw)
        got = V.frame_count(out)
        if got != frames:
            fixed = out.replace(".mp4", "_fix.mp4")
            V.sh(["ffmpeg", "-y", "-i", out, "-vf", f"tpad=stop_mode=clone:stop={max(0, frames - got)}",
                  "-frames:v", str(frames), *V.encode_args(), fixed])
            out = fixed
        spans.append((pos / FPS, (pos + frames) / FPS, theme))
        segments.append(out)
        pos += frames

    text, label, img = hook
    add(hook_shot, hook_len, "dark", text, label, img, "dark")
    cuts = [hook_len]
    # real news photos of this story, reused (with a new crop each time) instead of AI pictures
    real = [i for i in V.STUDIO_INFO.values() if i["kind"] == "picture" and i.get("credit") and
            i.get("raw") and os.path.exists(i["raw"])]
    if img is not None:
        hook_raw = os.path.join(tmp, "hook_raw.jpg")
        try:
            img.convert("RGB").save(hook_raw, quality=90)
            real.append({"kind": "picture", "raw": hook_raw, "credit": "", "real": True})
        except Exception:
            pass
    uses = {}

    def real_instead(n_pieces):
        """Real photos of the story, each shown at most twice in the whole reel (a third time reads as a loop)."""
        out = []
        for k in range(n_pieces):
            fresh = [i for i in real if uses.get(i["raw"], 0) < 2]
            if not fresh:
                break
            info = min(fresh, key=lambda i: uses.get(i["raw"], 0))
            uses[info["raw"]] = uses.get(info["raw"], 0) + 1
            out.append(("picture", {**info, "_reframe": uses[info["raw"]]}))
        return out
    shown_brands = set()
    for i, ((start, end), b, shots) in enumerate(zip(times, beats, plan)):
        start = max(start, hook_len)
        if end - start < 0.05:
            continue
        theme = theme_for(i)
        if start > hook_len + 0.2:
            cuts.append(start)
        specs = specs_for(b, shots)
        pieces = max(1, round((end - start) / V.SHOT_SECONDS))
        ai_only = all(k == "picture" and not (i.get("credit") or i.get("real")) for k, i in specs)
        tag = (b.get("tag") or "").strip()
        multi = False
        if ai_only:  # nothing real fits this line: what it names, then its key fact, then real photos if any left
            alts = []
            for br in b.get("brands") or []:
                key = re.sub(r"[^a-z0-9]", "", str(br.get("name", "")).lower())
                if key and key not in shown_brands:
                    shown_brands.add(key)
                    alts.append(("logo", {"name": br["name"], "domain": br.get("domain", ""),
                                          "logo": V.brand_logo(br["name"], br.get("domain", ""))}))
                    break
            if tag:
                alts.append(("statement", {"tag": tag}))
            if real and pieces > len(alts):
                alts += real_instead(pieces - len(alts))
            if alts:
                specs, pieces, multi = alts, len(alts), True
        if not specs and tag:
            specs = [("statement", {"tag": tag})]
        if not specs:
            specs = [("logo", {"name": (b.get("brands") or [{}])[0].get("name") or "AI", "domain": ""})]
        text_card = specs[0][0] in ("stat", "person", "source", "logo")
        if text_card and not multi:
            pieces = 1
        for k in range(pieces):
            kind, info = specs[k % len(specs)]
            repeat = k // len(specs)
            stop = start + (end - start) * (k + 1) / pieces
            if kind == "picture":
                add(picture_shot, stop, theme, Image.open(info["raw"]), theme, info.get("credit", ""),
                    info.get("_reframe", repeat), i + k)
            elif kind == "clip":
                add(clip_shot, stop, theme, info["src"], theme, repeat * V.SHOT_SECONDS)
            elif kind == "statement":
                add(statement_shot, stop, theme, info["tag"], theme)
            elif kind == "stat":
                add(stat_shot, stop, theme, info["big"], info["small"], theme)
            elif kind == "person":
                face = Image.open(info["raw"]) if info.get("raw") else None
                add(person_shot, stop, theme, face, info["name"], info.get("role", ""), theme, info.get("credit", ""))
            elif kind == "source":
                add(source_shot, stop, theme, info["outlet"], info["headline"], info.get("domain", ""), theme,
                    info.get("date", ""), info.get("logo"))
            else:
                add(logo_shot, stop, theme, info["name"], info.get("domain", ""), theme, info.get("logo"))
    if int(round(total * FPS)) > pos:
        add(logo_shot, total, "dark", "Gradient Daily", "", "dark")
    listfile = os.path.join(tmp, "studio_list.txt")
    with open(listfile, "w") as f:
        f.writelines(f"file '{os.path.abspath(s)}'\n" for s in segments)

    def theme_at(t):
        for a, b, th in spans:
            if a <= t < b:
                return th
        return "dark"
    return listfile, cuts, theme_at


def specs_for(b, shots):
    """What to show for a beat in the studio style, from what plan_visuals found (V.STUDIO_INFO)."""
    specs, seen_text = [], False
    for kind, src in shots:
        if kind == "layered":
            continue
        if kind == "clip":
            specs.append(("clip", {"src": src}))
            continue
        info = V.STUDIO_INFO.get(src)
        if not info:
            continue
        if info["kind"] in ("stat", "person", "source", "logo"):
            if not seen_text:
                specs.insert(0, (info["kind"], info))
                seen_text = True
        elif info.get("raw") and os.path.exists(info["raw"]):
            specs.append(("picture", info))
    return specs
