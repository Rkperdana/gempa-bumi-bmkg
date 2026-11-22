#!/usr/bin/env python3
"""Original Pirsadata editorial weather cover. Never presents itself as BMKG radar."""
from __future__ import annotations
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 675
BG = (17, 29, 51)
DEEP = (22, 45, 74)
ICE = (181, 230, 246)
WHITE = (245, 247, 251)
AMBER = (255, 190, 103)


def font(size, bold=False):
    try:
        path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def fit(draw, value, face, width, limit):
    lines = []
    active = ""
    for word in str(value).split():
        proposal = f"{active} {word}".strip()
        if draw.textbbox((0, 0), proposal, font=face)[2] <= width:
            active = proposal
        else:
            if active:
                lines.append(active)
            active = word
    if active:
        lines.append(active)
    if len(lines) > limit:
        lines = lines[:limit]
        while lines[-1] and draw.textbbox((0, 0), lines[-1] + "…", font=face)[2] > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def render(entry):
    from dataloka_wp_cuaca import date_label, time_label
    event = str(entry.get("event") or "").strip()
    region = str(entry.get("region") or "").strip()
    if not event or not region:
        raise ValueError("Missing event or warning region")
    im = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((40, 35, 1160, 636), radius=26, fill=DEEP,
                        outline=(63, 121, 163), width=3)
    d.text((80, 70), "PIRSADATA", font=font(32, True), fill=ICE)
    d.text((80, 150), "PERINGATAN DINI CUACA", font=font(31, True), fill=WHITE)
    for i, line in enumerate(fit(d, event, font(43, True), 608, 3)):
        d.text((80, 215 + i * 60), line, font=font(43, True), fill=ICE)
    d.line((80, 418, 635, 418), fill=(69, 128, 166), width=3)
    for i, line in enumerate(fit(d, region, font(33, True), 595, 2)):
        d.text((80, 440 + i * 42), line, font=font(33, True), fill=WHITE)
    d.text((80, 550), f"DITERBITKAN {date_label(entry['issued'])}",
           font=font(17, True), fill=ICE)
    d.text((80, 584), time_label(entry["issued"]), font=font(27, True), fill=WHITE)

    # Generic storm illustration, no fabricated impact map or meteorological imagery.
    cloud = (112, 167, 206)
    d.ellipse((757, 226, 978, 441), fill=cloud)
    d.ellipse((882, 169, 1105, 435), fill=cloud)
    d.ellipse((747, 314, 1113, 461), fill=cloud)
    d.rounded_rectangle((750, 350, 1106, 461), radius=54, fill=cloud)
    for x, y in ((794, 482), (870, 516), (1043, 484)):
        d.line([(x, y), (x - 26, y + 58)], fill=ICE, width=12)
    d.polygon([(945, 417), (891, 505), (943, 498),
               (902, 582), (1032, 466), (968, 473), (1014, 417)], fill=AMBER)
    d.text((742, 605), "Ilustrasi editorial, bukan radar BMKG",
           font=font(14), fill=ICE)
    d.text((80, 647), "Sumber informasi: BMKG", font=font(14), fill=ICE)
    buf = BytesIO()
    for quality in (85, 75, 65, 55):
        buf.seek(0)
        buf.truncate(0)
        im.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        if buf.tell() < 500_000:
            return buf.getvalue()
    raise ValueError("Pirsadata featured image exceeds 500 KB")
