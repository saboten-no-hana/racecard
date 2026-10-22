"""調査用（probe-results ブランチだけ）: 開催中にレース結果がいつ載るかを見張る。
結果トップ1回 → 当日の開催1回 → その開催の全レースまとめを2分おきに読む（最大 MIN 分、合計20リクエストまで）。
各回の「どのレースに着順が載っているか」を probe/watch.log に残す。"""
import os, re, sys, time
from datetime import datetime, timedelta, timezone
sys.path.insert(0, os.path.dirname(__file__))
from fetch_races import Fetcher
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9)); OUT = 'probe'; os.makedirs(OUT, exist_ok=True)
MIN = int(sys.argv[1]) if len(sys.argv) > 1 else 30
f = Fetcher(); MAX = 20
log = open(os.path.join(OUT, 'watch.log'), 'a', encoding='utf-8')
def now(): return datetime.now(JST)
def out(msg, notice=False):
    line = now().strftime('%m/%d %H:%M:%S ') + msg
    print(('::notice::' if notice else '') + line); log.write(line + '\n'); log.flush()
def slinks(html):
    a = re.findall(r"doAction\('/JRADB/accessS\.html',\s*'([^']*)'\)", html)
    return list(dict.fromkeys(a))
def get(c):
    if f.count >= MAX: out('上限に達したので終了', True); raise SystemExit(0)
    f.memo = {}
    return f.get(c, post=True, path='/JRADB/accessS.html')

today = now().strftime('%Y%m%d')
top = get('pw01sli00/AF'); open(os.path.join(OUT, 'w1_top.html'), 'w', encoding='utf-8').write(top)
L = slinks(top)
kai = [c for c in L if c.startswith('pw01srl') and c.split('/')[0].endswith(today)]
out(f'結果トップの当日の開催: {" ".join(kai) or "なし"} / リンクの種類: {" ".join(sorted(set(c[:9] for c in L)))}', True)
if not kai: raise SystemExit(0)
pick = next((c for c in kai if c[9:11] == '05'), kai[0])   # 東京があれば東京
srl = get(pick); open(os.path.join(OUT, 'w2_kaisai.html'), 'w', encoding='utf-8').write(srl)
R = slinks(srl)
races = sorted(c for c in R if c.startswith('pw01sde'))
ses = [c for c in R if c.startswith('pw01ses')]
out(f'開催 {pick}: 個別レースのリンク {len(races)}件（{", ".join(c[19:21] + "R" for c in races)}）/ 全レースまとめ {ses[0] if ses else "なし"}', True)
if not ses: raise SystemExit(0)

end = now() + timedelta(minutes=MIN); prev = None; last = ''
while True:
    h = get(ses[0]); last = h
    soup = BeautifulSoup(h, 'html.parser'); st = []
    for u in soup.select('div.race_result_unit'):
        r = (u.get('id') or '').replace('race_result_', '')
        dl = u.select_one('.date_line'); m = re.search(r'(\d+)時(\d+)分', dl.get_text() if dl else '')
        places = [td.get_text(strip=True) for td in u.select('td.place')]
        st.append(f'{r}({m.group(1)}:{m.group(2) if m else "?"})={sum(1 for p in places if p)}/{len(places)}')
    cur = ' '.join(st) or f'レースなし（{len(h)}字）'
    out(cur, cur != prev); prev = cur
    if now() + timedelta(minutes=2) > end: break
    time.sleep(120)
open(os.path.join(OUT, 'w3_ses_last.html'), 'w', encoding='utf-8').write(last)
out(f'リクエスト数 {f.count}', True)
