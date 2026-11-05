#!/usr/bin/env python3
import re, urllib.request
from html.parser import HTMLParser

URL = 'https://www.bmkg.go.id/gempabumi/gempabumi-realtime'
request=urllib.request.Request(URL,headers={'User-Agent':'Mozilla/5.0 (compatible; DatalokaGempaMonitor/1.1)','Accept':'text/html','Cache-Control':'no-cache'})
with urllib.request.urlopen(request,timeout=25) as r:
    html=r.read(1500000).decode('utf-8-sig','replace')
    print('STATUS',r.status,'URL',r.url,'BYTES',len(html))
    print('CONTENT_TYPE',r.headers.get('content-type'))
for needle in ('__NUXT_DATA__','200 Gempa Bumi','Banda Sea','<table','<tbody','<tr','<td','moment tensor','__nuxt'):
    print('NEEDLE',needle,'COUNT',html.lower().count(needle.lower()))
    idx=html.lower().find(needle.lower())
    if idx!=-1:
        print('CONTEXT',re.sub(r'\\s+',' ',html[max(0,idx-190):idx+390])[:600])
class Table(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.active=False;self.tr=False;self.td=False;self.buf=[];self.cells=[];self.depth=0
    def handle_starttag(self,tag,attrs):
        if tag=='table':self.active=True;self.depth+=1
        if self.active and tag=='tr':self.tr=True;self.cells=[]
        if self.tr and tag in ('td','th'):self.td=True;self.buf=[]
    def handle_data(self,s):
        if self.td:self.buf.append(s)
    def handle_endtag(self,tag):
        if self.td and tag in ('td','th'):self.cells.append(' '.join(' '.join(self.buf).split()));self.td=False
        if self.tr and tag=='tr':self.rows.append(self.cells);self.tr=False
        if self.active and tag=='table':self.depth-=1;self.active=self.depth>0
p=Table();p.feed(html)
print('TABLE_ROWS',len(p.rows),'FIRST',repr(p.rows[:3])[:1800])
