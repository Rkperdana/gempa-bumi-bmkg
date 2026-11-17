#!/usr/bin/env python3
"""Generate an offline editorial map of a BMKG epicenter, no invented imagery.

Only real BMKG coordinates are shown. Land outlines are Natural Earth public domain.
Requires Pillow. Returns a 1200x675 JPEG under 500 KB, suitable for a WP featured image.
"""
from __future__ import annotations

from io import BytesIO
import datetime as dt
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LAND = ROOT / "assets" / "natural-earth-110m-land.json"
SIZE = (1200, 675)
NAVY = (19, 40, 86)
OCEAN = (17, 38, 79)
LAND_COLOR = (52, 92, 125)
BORDER = (115, 152, 183)
LIGHT = (242, 246, 250)
PALE = (179, 220, 253)
ORANGE = (255, 150, 87)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")


def font(size, bold=False):
    base = "/usr/share/fonts/truetype/dejavu/"
    path = base + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def wrap_text(draw, text, face, width, max_lines):
    """Keep source location legible without making up or changing words."""
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        attempt = (current + " " + word).strip()
        if draw.textbbox((0, 0), attempt, font=face)[2] <= width:
            current = attempt
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textbbox((0, 0), lines[-1] + "…", font=face)[2] > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def render(event):
    lat = float(event["lat"])
    lon = float(event["lon"])
    magnitude = float(event["magnitude"])
    depth = float(event["depth_km"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid epicenter coordinates")
    now = dt.datetime.fromisoformat(str(event["datetime"]).replace("Z", "+00:00"))
    if now.tzinfo is None:
        raise ValueError("Missing time zone")
    local = now.astimezone(dt.timezone(dt.timedelta(hours=7)))
    region = str(event["region"]).strip()
    if not region:
        raise ValueError("Region is blank")
    data = json.loads(LAND.read_text(encoding="utf-8"))

    im = Image.new("RGB", SIZE, NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1200, 675), fill=NAVY)
    d.rectangle((478, 90, 1168, 606), fill=OCEAN)
    d.rounded_rectangle((478, 90, 1168, 606), radius=20, outline=(54, 93, 141), width=2)

    # An equirectangular local map with gridlines around the measured epicenter.
    left, top, right, bottom = 488, 100, 1158, 596
    lat_span = 30.0
    lon_span = 41.0 / max(0.55, math.cos(math.radians(lat)))
    lon_span = min(lon_span, 85.0)
    def xy(a, b):
        dx = ((a - lon + 180) % 360) - 180
        return (left + (0.5 + dx / lon_span) * (right - left),
                top + (0.5 - (b - lat) / lat_span) * (bottom - top))
    step = 10
    for i in range(-90, 91, step):
        if abs(i - lat) <= lat_span / 2:
            y = xy(lon, i)[1]
            d.line((left, y, right, y), fill=(38, 64, 105), width=1)
    for k in range(-180, 181, step):
        if abs(((k - lon + 180) % 360) - 180) <= lon_span / 2:
            x = xy(k, lat)[0]
            d.line((x, top, x, bottom), fill=(38, 64, 105), width=1)

    for poly in data["polygons"]:
        for ring in poly:
            if len(ring) < 3:
                continue
            pts = [xy(lng, lt) for lng, lt in ring]
            # Avoid antimeridian-spanning artifacts from a ring at the other side of the world.
            if any(abs(pts[j][0] - pts[j - 1][0]) > (right - left) / 2
                   for j in range(1, len(pts))):
                continue
            if max(p[0] for p in pts) < left or min(p[0] for p in pts) > right:
                continue
            if max(p[1] for p in pts) < top or min(p[1] for p in pts) > bottom:
                continue
            d.polygon(pts, fill=LAND_COLOR)
            d.line(pts, fill=BORDER, width=2, joint="curve")

    px, py = xy(lon, lat)
    for r, w, color in [(65, 2, (129, 111, 105)), (40, 3, (221, 128, 89)),
                        (20, 3, ORANGE)]:
        d.ellipse((px - r, py - r, px + r, py + r), outline=color, width=w)
    d.ellipse((px - 8, py - 8, px + 8, py + 8), fill=ORANGE, outline=LIGHT, width=2)
    d.rectangle((left, top, right, bottom), outline=(55, 90, 136), width=2)

    d.text((55, 44), "DATALOKA", font=font(25, True), fill=PALE)
    d.text((55, 121), "GEMPA BUMI", font=font(30, True), fill=LIGHT)
    mag_label = f"M{magnitude:.1f}".replace(".", ",")
    d.text((50, 157), mag_label, font=font(102, True), fill=PALE)
    d.line((55, 290, 380, 290), fill=(69, 111, 165), width=2)
    d.text((55, 311), "LOKASI EPISENTRUM", font=font(18, True), fill=PALE)
    for i, line in enumerate(wrap_text(d, region, font(30, True), 386, 3)):
        d.text((55, 348 + i * 43), line, font=font(30, True), fill=LIGHT)
    d.text((55, 491), "KEDALAMAN", font=font(17), fill=PALE)
    d.text((55, 518), f"{depth:g} KM", font=font(28, True), fill=LIGHT)
    d.text((55, 566), "WAKTU KEJADIAN (WIB)", font=font(16), fill=PALE)
    d.text((55, 590), f"{local:%d} {MONTHS[local.month - 1]} {local:%Y, %H.%M}", font=font(20, True), fill=LIGHT)
    d.text((490, 620), "Sumber episentrum: BMKG   |   Geografi: Natural Earth", font=font(15), fill=PALE)
    d.text((54, 641), "Peta ilustratif berbasis koordinat, bukan peta intensitas guncangan", font=font(13), fill=PALE)

    output = BytesIO()
    for quality in (86, 78, 70, 62, 54):
        output.seek(0)
        output.truncate(0)
        im.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
        if output.tell() <= 500_000:
            return output.getvalue()
    raise RuntimeError("Generated image exceeds 500 KB")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("event_json", help="Event JSON with BMKG normalized coordinates")
    parser.add_argument("output_jpg")
    args = parser.parse_args()
    event = json.loads(Path(args.event_json).read_text(encoding="utf-8"))
    Path(args.output_jpg).write_bytes(render(event))
