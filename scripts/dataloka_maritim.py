#!/usr/bin/env python3
"""Dataloka maritime editorial pilot. No WordPress writes. Offline by default."""
import argparse
import datetime as dt
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import urllib.request
from PIL import Image, ImageDraw, ImageFont

BASE = "https://maritim.bmkg.go.id/marine2026-data/"
WAVE = BASE + "warning/warnings.json"
ROB = BASE + "w-banjirob/banjirrob_combine.json"
ZONES = {"WIB": 7, "WITA": 8, "WIT": 9}
LEVELS = {"sedang": "Sedang (1,25–2,5 meter)", "tinggi": "Tinggi (2,5–4 meter)",
          "sangat_tinggi": "Sangat tinggi (4–6 meter)", "ekstrem": "Ekstrem (lebih dari 6 meter)"}
MONTHS = "Januari Februari Maret April Mei Juni Juli Agustus September Oktober November Desember".split()

def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing text field")
    return " ".join(value.split())

def time_local(value, zone):
    stamp = dt.datetime.fromisoformat(value)
    if zone not in ZONES or stamp.tzinfo is not None:
        raise ValueError("Unexpected source timezone")
    return stamp.replace(tzinfo=dt.timezone(dt.timedelta(hours=ZONES[zone])))

def date_label(d):
    return f"{d.day} {MONTHS[d.month-1]} {d.year}"

def key(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]

def parse_wave(raw, now):
    if not isinstance(raw, dict) or not raw:
        raise ValueError("Invalid wave response")
    results = []
    for name, obj in raw.items():
        d = obj["data"]
        region = text(name) # preserve subregions; don't collapse distinct bulletins
        zone = d["time_zone"]
        start, end = (time_local(d[k], zone) for k in ("valid_from", "valid_until"))
        if end <= start or end-start > dt.timedelta(days=4):
            raise ValueError("Invalid wave validity")
        groups = d["warning"]
        if set(groups) != set(LEVELS):
            raise ValueError("Unexpected wave category schema")
        if any(not isinstance(v, list) for v in groups.values()):
            raise ValueError("Invalid area list")
        groups = {k: sorted(set(text(x) for x in groups[k])) for k in LEVELS}
        if not start <= now < end or not any(groups[k] for k in ("tinggi", "sangat_tinggi", "ekstrem")):
            continue
        synoptic = text(d["synoptic"])
        results.append({"kind":"wave","region":region,"start":start.isoformat(),
            "end":end.isoformat(),"zone":zone,"groups":groups,"synoptic":synoptic,
            "source":WAVE})
    return results

def parse_reviewed_rob(raw, now):
    """Editorial transcription schema, NOT a claim about the live BMKG schema."""
    if not isinstance(raw, list):
        raise ValueError("Reviewed rob input must be a list")
    results = []
    for d in raw:
        region = text(d["region"])
        start, end = (dt.date.fromisoformat(d[k]) for k in ("start", "end"))
        zone = d["zone"]
        if zone not in ZONES or end < start or (end-start).days > 31:
            raise ValueError("Invalid rob validity")
        if not isinstance(d["areas"], list) or not d["areas"]:
            raise ValueError("Missing areas")
        today = now.astimezone(dt.timezone(dt.timedelta(hours=ZONES[zone]))).date()
        if not start <= today <= end:
            continue
        results.append({"kind":"rob","region":region,"start":start.isoformat(),
            "end":end.isoformat(),"zone":zone,"areas":sorted(set(text(x) for x in d["areas"])),
            "synoptic":text(d["description"]),"source":"https://www.bmkg.go.id/peringatan-dini/banjir-pesisir"})
    return results

def article(a, now):
    esc = html.escape
    region = a["region"]
    start, end = (dt.datetime.fromisoformat(a[k]) if a["kind"] == "wave" else
                  dt.date.fromisoformat(a[k]) for k in ("start","end"))
    period = date_label(start) + " hingga " + date_label(end)
    if a["kind"] == "wave":
        period = f"{date_label(start)} pukul {start:%H.%M} {a['zone']} hingga {date_label(end)} pukul {end:%H.%M} {a['zone']}"
        highest = next(k for k in reversed(LEVELS) if a["groups"][k])
        title = f"BMKG: Waspada Gelombang {('Ekstrem' if highest == 'ekstrem' else 'Sangat Tinggi' if highest == 'sangat_tinggi' else 'Tinggi')} di {region} hingga {date_label(end)}"
        topic = "gelombang tinggi"
        detail = "; ".join(LEVELS[k]+": "+", ".join(v) for k,v in a["groups"].items() if v)
        tags = ["BMKG","Cuaca","Gelombang Tinggi","Maritim"]
    else:
        title = f"BMKG: Waspada Banjir Rob di {region} hingga {date_label(end)}"
        topic = "banjir rob"
        detail = "; ".join(a["areas"])
        tags = ["BMKG","Cuaca","Banjir Rob","Maritim"]
    source = esc(a["source"], quote=True)
    paragraphs = [
        f'<strong>Dataloka.id</strong> - Badan Meteorologi, Klimatologi, dan Geofisika (BMKG) mengeluarkan informasi potensi {topic} di {esc(region)}. Informasi ini berkaitan dengan <a href="https://dataloka.id/tag/cuaca">cuaca</a> maritim.',
        f"Peringatan berlaku pada {esc(period)} berdasarkan informasi resmi BMKG.",
        f"Rincian wilayah yang perlu diwaspadai: {esc(detail)}.",
        esc(a["synoptic"]),
        f'Informasi tersebut merupakan prakiraan, bukan laporan kejadian yang telah terjadi. Pantau <a href="{source}">informasi resmi BMKG</a> untuk pembaruan sebelum beraktivitas di kawasan terkait. (RK/D-1)'
    ]
    fingerprint = key(a)
    slug = re.sub(r"[^a-z0-9]+","-",f"{topic}-{region}".lower()).strip("-")[:80]
    summary = f"BMKG memperingatkan potensi {topic} di {region} hingga {date_label(end)}. Simak wilayah dan masa berlaku peringatannya."
    return {"title":title,"slug":f"{slug}-{fingerprint[:12]}","excerpt":summary[:280],
            "content":"".join(f"<p>{p}</p>" for p in paragraphs)+
              f'<p><strong>Sumber: BMKG</strong> — <a href="{source}">{topic}</a>, diakses {date_label(now.date())}.</p><!-- dataloka-maritim:{fingerprint} -->',
            "tag_names":tags,"yoast_meta":{"_yoast_wpseo_focuskw":f"{topic} {region}",
            "_yoast_wpseo_title":title,"_yoast_wpseo_metadesc":summary[:160]},
            "fingerprint":fingerprint,"status":"preview"}

def cover(kind):
    # Original editorial illustration, never an official map or disaster photograph.
    im = Image.new("RGB",(1600,900),"#182d48")
    d=ImageDraw.Draw(im)
    for y in range(900):
        f=y/900
        d.line((0,y,1600,y),fill=(int(42-24*f),int(78+12*f),int(111+5*f)))
    for n in range(10):
        y=405+n*55
        amp=10+n*2 if kind=="rob" else 22+n*4
        points=[(x,int(y+amp*math.sin(x/113+n*0.73))) for x in range(0,1601,8)]
        d.polygon(points+[(1600,900),(0,900)],fill=(15+n*3,67+n*5,94+n*6))
        d.line(points,fill=(113+n*8,172+n*5,184+n*4),width=3)
    if kind=="rob":
        for x,h in [(690,160),(925,205),(1190,140)]:
            y=555
            d.rectangle((x,y-h,x+185,y+30),fill="#bbc6c8")
            d.polygon([(x-28,y-h),(x+92,y-h-76),(x+210,y-h)],fill="#6f504a")
            d.rectangle((x+72,y-65,x+113,y+23),fill="#30465b")
        for n in range(4):
            y=570+n*46
            pts=[(x,int(y+9*math.sin(x/83+n))) for x in range(0,1601,8)]
            d.line(pts,fill="#c1e1e5",width=4)
    else:
        crest=[(x,int(540-235*math.exp(-((x-1050)/250)**2)+32*math.sin(x/100))) for x in range(0,1601,7)]
        d.polygon(crest+[(1600,900),(0,900)],fill="#176b85")
        d.line(crest,fill="#deedf0",width=10)
        d.polygon([(980,540),(1250,540),(1200,589),(1030,589)],fill="#d8a36e")
        d.rectangle((1096,461,1106,540),fill="#f0eee5")
        d.polygon([(1109,467),(1109,535),(1192,535)],fill="#f0eee5")
    font="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    def load(p,s):
        try: return ImageFont.truetype(p,s)
        except OSError: return ImageFont.load_default()
    d.text((80,70),"ILUSTRASI EDITORIAL",font=load(bold,26),fill="#d8eaf0")
    d.text((78,118),"BANJIR ROB" if kind=="rob" else "GELOMBANG TINGGI",
           font=load(bold,70),fill="white")
    buf=io.BytesIO()
    im.save(buf,"JPEG",quality=88,optimize=True)
    return buf.getvalue()

def fetch(url):
    if url not in (WAVE, ROB):
        raise ValueError("Only fixed official API endpoints")
    if os.getenv("BMKG_MARITIM_AUTHORIZED") != "true":
        raise PermissionError("Written authorization required before automatic access")
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"DatalokaMaritimEditorial/1.0"})
    with urllib.request.urlopen(req,timeout=25) as r:
        if r.geturl()!=url:
            raise ValueError("Unexpected redirect")
        raw=r.read(5_000_001)
    if len(raw)>5_000_000: raise ValueError("Oversized response")
    return json.loads(raw)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--wave-json",type=Path)
    p.add_argument("--reviewed-rob-json",type=Path)
    p.add_argument("--authorized-wave",action="store_true")
    p.add_argument("--inspect-rob",action="store_true")
    p.add_argument("--out",type=Path,default=Path("maritim-preview"))
    args=p.parse_args()
    now=dt.datetime.now(dt.timezone.utc)
    args.out.mkdir(parents=True,exist_ok=True)
    items=[]
    if args.wave_json: items+=parse_wave(json.loads(args.wave_json.read_text()),now)
    if args.authorized_wave: items+=parse_wave(fetch(WAVE),now)
    if args.reviewed_rob_json: items+=parse_reviewed_rob(json.loads(args.reviewed_rob_json.read_text()),now)
    if args.inspect_rob:
        raw=fetch(ROB)
        # No raw data printed or uploaded. Schema review is required before a rob adapter.
        print("ROB response type:",type(raw).__name__)
        if isinstance(raw,dict): print("ROB top-level keys:",list(raw)[:40])
        elif isinstance(raw,list) and raw and isinstance(raw[0],dict): print("ROB first-row keys:",list(raw[0])[:40])
    unique={key(a):a for a in items}
    for a in unique.values():
        payload=article(a,now)
        slug=payload["slug"]
        (args.out/(slug+".json")).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        (args.out/(slug+".html")).write_text(payload["content"],encoding="utf-8")
    for kind in ("rob","wave"): (args.out/(kind+".jpg")).write_bytes(cover(kind))
    print(f"{len(unique)} previews; no WordPress access or publication")

if __name__=="__main__": main()
