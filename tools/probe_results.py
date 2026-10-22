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
races = [c for c in R if c.startswith('pw01sde')]
for i, c in enumerate([races[0], races[-1]] if len(races) > 1 else races):
    h = get(c, post=not c.startswith('pw01sde') or True); save(f'03_race_{i}', h)
    heads = re.findall(r'<th[^>]*>(.*?)</th>', h, re.S)[:20]
    note(f'レース {c}: {len(h)}字 / 見出し: ' + ' | '.join(re.sub(r'<[^>]+>|\s+', '', x) for x in heads))
others = [c for c in R if not c.startswith('pw01sde') and not c.startswith('pw01srl')]
if others:
    h = get(others[0]); save('04_other', h); note(f'その他 {others[0]}: {len(h)}字')
note(f'リクエスト数 {f.count}')
