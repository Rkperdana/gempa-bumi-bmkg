#!/usr/bin/env python3
"""Isolated, opt-in maritime publisher for verified BMKG wave warnings."""
import datetime as dt
import html
import json
import os
from pathlib import Path
import urllib.request
from dataloka_maritim import WAVE, fetch, parse_wave, key, article, cover
from dataloka_wp_gempa import WordPress, slugify, EditorialConflict

STATE = Path(__file__).resolve().parents[1]/"data"/"dataloka-maritim-state.json"
UTC = dt.timezone.utc

def load_state():
    if not STATE.exists(): return {"version":1,"published":{}}
    state=json.loads(STATE.read_text())
    if state.get("version")!=1 or not isinstance(state.get("published"),dict):
        raise ValueError("Invalid maritime ledger")
    return state

def persist(state):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    temp=STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(STATE)

class MaritimeWP(WordPress):
    def strict_tags(self,names):
        ids=[]
        for name in names:
            terms=self.call("GET","tags",{"search":name,"per_page":100})
            exact=[t for t in terms if html.unescape(str(t.get("name",""))).casefold()==name.casefold()]
            if len(exact)>1: raise RuntimeError("Ambiguous tag")
            term=exact[0] if exact else self.call("POST","tags",payload={"name":name,"slug":slugify(name)})
            ids.append(int(term["id"]))
        return sorted(set(ids))

    def image_id(self,kind):
        slug="dataloka-maritim-ilustrasi-"+kind+"-v1"
        found=self.call("GET","media",{"slug":slug,"context":"edit","per_page":2})
        label="Ilustrasi editorial Dataloka: "+("banjir rob" if kind=="rob" else "gelombang tinggi")
        if len(found)>1: raise RuntimeError("Ambiguous media")
        if found:
            media=found[0]
        else:
            req=urllib.request.Request("https://dataloka.id/wp-json/wp/v2/media",data=cover(kind),method="POST",
                headers={"Authorization":self.authorization,"Content-Type":"image/jpeg",
                    "Content-Disposition":f'attachment; filename="{slug}.jpg"'})
            with urllib.request.urlopen(req,timeout=40) as r: media=json.loads(r.read(1000000))
            self.call("POST",f"media/{int(media['id'])}",payload={"alt_text":label,"caption":label,"title":label})
        media=self.call("GET",f"media/{int(media['id'])}",{"context":"edit"})
        if media.get("slug")!=slug or media.get("alt_text")!=label:
            raise RuntimeError("Featured image metadata not verified")
        return int(media["id"])

    def publish_verified(self,a,revalidate,now):
        p=article(a,now)
        tags=self.strict_tags(p["tag_names"])
        category=int(self.berita_category_id())
        media=self.image_id(a["kind"])
        payload={k:p[k] for k in ("title","slug","content","excerpt")}
        payload.update({"meta":p["yoast_meta"],"tags":tags,"categories":[category],
                        "featured_media":media,"status":"draft","comment_status":"closed"})
        def verify(found):
            if (found.get("slug")!=p["slug"] or found.get("content",{}).get("raw")!=p["content"] or
                html.unescape(found.get("title",{}).get("raw",""))!=html.unescape(p["title"])):
                raise EditorialConflict("Existing maritime post differs; no overwrite")
            self._verified_yoast(found,p["yoast_meta"])
            if (set(found.get("tags",[]))!=set(tags) or category not in found.get("categories",[]) or
                int(found.get("featured_media") or 0)!=media):
                raise EditorialConflict("Maritime post taxonomy or media differs; no overwrite")
        found=self.by_slug(p["slug"])
        if found is None:
            # Validate before even creating a draft; never publish stale data.
            revalidate(a)
            found=self.call("POST","posts",payload=payload)
        found=self.by_id(found["id"])
        verify(found)
        if found.get("status")=="publish": return int(found["id"])
        if found.get("status")!="draft": raise EditorialConflict("Not a bot draft")
        # Check again immediately before changing only status.
        revalidate(a)
        self.call("POST",f"posts/{int(found['id'])}",payload={"status":"publish"})
        confirmed=self.by_id(found["id"])
        verify(confirmed)
        if confirmed.get("status")!="publish": raise RuntimeError("Publication not confirmed")
        return int(confirmed["id"])

def live_wave(now=None):
    if os.getenv("BMKG_MARITIM_AUTHORIZED")!="true" or os.getenv("BMKG_MARITIM_LIVE")!="true":
        raise PermissionError("Authorization and explicit go-live required")
    now=now or dt.datetime.now(UTC)
    # Do not instantiate CMS until actual source access/validation succeeds.
    entries=parse_wave(fetch(WAVE),now)
    state=load_state()
    pending=[a for a in entries if key(a) not in state["published"]]
    pending.sort(key=lambda a:(a["region"]!="Indonesia",a["region"]))
    if not pending:
        print("No unpublished validated wave alerts")
        return
    wp=MaritimeWP(os.getenv("WP_USERNAME"),os.getenv("WP_APP_PASSWORD"))
    def revalidate(a):
        current=parse_wave(fetch(WAVE),dt.datetime.now(UTC))
        if key(a) not in {key(x) for x in current}:
            raise RuntimeError("Wave warning changed or expired before publication")
    # Two posts per cycle at most. Persistent ledger plus stable CMS slug.
    for a in pending[:2]:
        try:
            post=wp.publish_verified(a,revalidate,now)
        except EditorialConflict as exc:
            print("::warning::Editorial conflict:",str(exc))
            state["published"][key(a)]={"status":"editorial-conflict","region":a["region"]}
            persist(state)
            continue
        state["published"][key(a)]={"post_id":post,"status":"publish","region":a["region"],"end":a["end"]}
        persist(state)
        print("Verified maritime post",post,a["region"])

if __name__=="__main__":
    live_wave()
