#!/usr/bin/env python3
"""Original Dataloka weather artwork (1200x675 JPG), not a BMKG map or screenshot."""
from __future__ import annotations

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 675
NAVY = (19, 40, 86)
DEEP = (12, 29, 65)
BLUE = (179, 220, 253)
WHITE = (242, 246, 250)
AMBER = (255, 174, 96)


def font(size, heavy=False):
    base = "/usr/share/fonts/truetype/dejavu/"
    path = base + ("DejaVuSans-Bold.ttf" if heavy else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def fit_lines(draw, text, face, width, maximum):
    lines, current = [], ""
    for word in str(text).split():
        trial = (current + " " + word).strip()
        if draw.textbbox((0, 0), trial, font=face)[2] <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > maximum:
        lines = lines[:maximum]
        while draw.textbbox((0, 0), lines[-1] + "…", font=face)[2] > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def render(alert):
    from dataloka_wp_cuaca import date_label, time_label
    region = str(alert.get("region") or "").strip()
    event = str(alert.get("event") or "").strip()
    if not region or not event:
        raise ValueError("Missing real warning label or province")
    im = Image.new("RGB", (WIDTH, HEIGHT), NAVY)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((38, 35, 1162, 637), radius=26, fill=DEEP,
                        outline=(61, 103, 157), width=3)
    d.text((80, 70), "DATALOKA", font=font(30, True), fill=BLUE)
    d.text((80, 150), "PERINGATAN DINI CUACA", font=font(31, True), fill=WHITE)
    for i, line in enumerate(fit_lines(d, event, font(45, True), 625, 3)):
        d.text((76, 216 + i*61), line, font=font(45, True), fill=BLUE)
    d.line((80, 417, 625, 417), fill=(60, 104, 159), width=3)
    for i, line in enumerate(fit_lines(d, region, font(34, True), 600, 2)):
        d.text((80, 437 + i*44), line, font=font(34, True), fill=WHITE)
    d.text((80, 550), f"DITERBITKAN {date_label(alert['issued'])}",
           font=font(17, True), fill=BLUE)
    d.text((80, 584), time_label(alert["issued"]),
           font=font(27, True), fill=WHITE)

    # Stylized storm cloud, not a meteorological radar or impact forecast.
    d.ellipse((745, 225, 965, 448), fill=(89, 142, 187))
    d.ellipse((877, 163, 1105, 436), fill=(100, 160, 200))
    d.ellipse((737, 302, 1110, 456), fill=(100, 160, 200))
    d.rounded_rectangle((745, 350, 1108, 455), radius=51, fill=(100, 160, 200))
    for x, y in ((785, 480), (875, 500), (1045, 475), (964, 526)):
        d.line([(x, y), (x-27, y+58)], fill=BLUE, width=12)
    d.polygon([(931, 416), (880, 501), (934, 497),
               (894, 590), (1024, 465), (959, 470), (1004, 416)], fill=AMBER)
    d.text((744, 595), "Ilustrasi editorial, bukan peta radar",
           font=font(16), fill=BLUE)
    d.text((80, 647), "Sumber informasi peringatan: BMKG",
           font=font(14), fill=BLUE)
    result = BytesIO()
    for quality in (85, 75, 65, 55):
        result.seek(0)
        result.truncate(0)
        im.save(result, format="JPEG", quality=quality, progressive=True, optimize=True)
        if result.tell() < 500_000:
            return result.getvalue()
    raise ValueError("Featured image exceeded 500 KB")
