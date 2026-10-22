"""調査用（probe-results ブランチだけ。main には入れない）: JRA のレース結果ページの作りを調べる。
リクエストは最大10回ほど、間隔は fetch_races.py と同じ 2 秒。取ったページは probe/ に保存してブランチにコミットする。"""
import os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch_races import Fetcher

OUT = 'probe'; os.makedirs(OUT, exist_ok=True)
f = Fetcher(); MAX = 10
def save(name, html):
    open(os.path.join(OUT, name + '.html'), 'w', encoding='utf-8').write(html)
def slinks(html, prefix=''):
    a = re.findall(r"doAction\('/JRADB/accessS\.html',\s*'(%s[^']*)'\)" % prefix, html)
    a += re.findall(r'accessS\.html\?CNAME=(%s[^"&\']+)' % prefix, html)
    return list(dict.fromkeys(a))
def note(msg): print('::notice::' + msg)
def get(c, post=True):
    if f.count >= MAX: raise SystemExit('上限')
    return f.get(c, post=post, path='/JRADB/accessS.html')

top = get('pw01sli00/AF'); save('01_top', top)
L = slinks(top); note(f'結果トップ: {len(top)}字 / accessS のリンク {len(L)}件: ' + ' '.join(L[:12]))
kai = [c for c in L if c.startswith('pw01srl')]
if not kai:
    note('開催のリンクなし。調査を終える'); sys.exit(0)
html = get(kai[0]); save('02_kaisai', html)
R = slinks(html); note(f'開催 {kai[0]}: リンク {len(R)}件: ' + ' '.join(R[:30]))
ses = [c for c in R if c.startswith('pw01ses')]
if ses:
    h = get(ses[0]); save('05_ses', h)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(h, 'html.parser'); tabs = soup.select('table')
    note(f'全レース {ses[0]}: {len(h)}字 / 表 {len(tabs)}個 / 着順の列 {len(soup.select("td.place"))}件 / 人気の列 {len(soup.select("td.pop"))}件')
kinds = sorted(set(c[:9] for c in L)); note('結果トップのリンクの種類: ' + ' '.join(kinds))
note(f'リクエスト数 {f.count}')
