"""
JRAホームページの出馬表から、一口クラブ名義の出走馬だけを取り出して data/races.json に保存する。

- 木曜16時すぎ: 馬番なしの出馬表（出走確定）
- レース前日10時すぎ: 枠番・馬番つきの出馬表
が公開されるので、GitHub Actions で木曜夕方・金曜朝・土曜朝（・日曜朝）に実行する。

馬番なしの出馬表には馬主名が載らないため、馬ごとに「どのクラブの馬か（クラブ以外なら空）」を
data/cache.json に記録して週をまたいで使い回す（個人馬主の名前は保存しない）。
- 1日分をまとめた出馬表ページで、出走馬・枠番・馬番・騎手を読む（競馬場ごとに1ページ）
- 記録にない馬がいて、馬番つきの出馬表が出ているレースは、そのレースの出馬表（馬主名つき）で確認する
- それでも分からない馬（主に木曜）は、馬のページで馬主名を確認する
- リクエストの間は2秒以上あける

使い方:
  python3 tools/fetch_races.py            # JRAから取得
  python3 tools/fetch_races.py --offline DIR  # 保存済みHTMLで動作確認（DIR/*.html）
"""
import json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(DATA, 'races.json')
CACHE = os.path.join(DATA, 'cache.json')
BASE = 'https://www.jra.go.jp'
UA = 'Mozilla/5.0 (compatible; racecard/1.0; +https://github.com/saboten-no-hana/racecard)'
JST = timezone(timedelta(hours=9))
WAIT = 2.0
VENUES = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京', '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}

# ---------------------------------------------------------------- clubs
def load_clubs():
    """clubs.js から {正規化した馬主名: クラブid} を作る"""
    src = open(os.path.join(ROOT, 'clubs.js'), encoding='utf-8').read()
    out = {}
    for m in re.finditer(r"\{id:'([^']+)'[^\n]*?owner:'([^']+)'", src):
        out[norm_owner(m.group(2))] = m.group(1)
    if len(out) < 10:
        raise SystemExit('clubs.js からクラブを読み取れませんでした')
    return out

def norm_owner(s):
    s = unicodedata.normalize('NFKC', s or '')
    s = re.sub(r'\((株|有|合|同)\)|株式会社|有限会社|合同会社|一般社団法人', '', s)
    return re.sub(r'[\s・]', '', s)

# ---------------------------------------------------------------- http
class Fetcher:
    def __init__(self, offline=None):
        self.offline = offline
        self.count = 0
        self.last = 0.0

    def _decode(self, raw):
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:3000])
        enc = m.group(1).decode() if m else 'shift_jis'
        if enc.lower() in ('shift_jis', 'sjis', 'x-sjis'):
            enc = 'cp932'
        return raw.decode(enc, errors='replace')

    def get(self, cname, post=False, path='/JRADB/accessD.html'):
        if self.offline:
            path = os.path.join(self.offline, cname.replace('/', '_') + '.html')
            return open(path, encoding='utf-8').read() if os.path.exists(path) else ''
        wait = WAIT - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        url = BASE + path
        headers = {'User-Agent': UA, 'Referer': BASE + '/JRADB/accessD.html', 'Accept-Language': 'ja'}
        data = None
        if post:
            data = urllib.parse.urlencode({'cname': cname}).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            url += '?CNAME=' + cname
        for attempt in range(3):
            try:
                self.count += 1
                with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=40) as r:
                    raw = r.read()
                self.last = time.time()
                return self._decode(raw)
            except (urllib.error.URLError, TimeoutError) as e:
                self.last = time.time()
                print(f'  retry {cname}: {e}', flush=True)
                time.sleep(10 * (attempt + 1))
        raise RuntimeError(f'取得できませんでした: {cname}')

# ---------------------------------------------------------------- parsing
def text(el):
    return re.sub(r'\s+', ' ', el.get_text(' ', strip=True)).strip() if el else ''

def parse_header(cap):
    """出馬表テーブルの caption からレース情報を読む"""
    info = {}
    d = text(cap.select_one('.date_line .date'))
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', d)
    if m:
        info['date'] = f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m = re.search(r'\d+回(\D+?)\d+日', d)
    if m:
        info['venue'] = m.group(1).strip()
    t = text(cap.select_one('.date_line .time'))
    m = re.search(r'(\d{1,2})時(\d{2})分', t)
    if m:
        info['time'] = f'{int(m.group(1)):02d}:{m.group(2)}'
    img = cap.select_one('.race_number img')
    m = re.search(r'(\d+)', img.get('alt', '') if img else '')
    if m:
        info['r'] = int(m.group(1))
    rn = cap.select_one('.race_name')
    if rn:
        grade = ''
        for g in rn.select('img'):
            alt = g.get('alt', '')
            if re.search(r'G|J', alt):
                grade = unicodedata.normalize('NFKC', alt).replace('Ⅰ', 'I')
            g.decompose()
        info['raceName'] = text(rn)
        info['grade'] = grade
    c = text(cap.select_one('.cell.course'))
    m = re.search(r'([\d,]+)\s*メートル', c)
    if m:
        info['dist'] = int(m.group(1).replace(',', ''))
    m = re.search(r'（(芝|ダート|障害)', c)
    if m:
        info['surface'] = {'芝': '芝', 'ダート': 'ダ', '障害': '障'}[m.group(1)]
    return info

def parse_rows(table):
    horses = []
    for tr in table.select('tbody > tr'):
        a = tr.select_one('td.horse a[href*="CNAME=pw01dud"]')
        if not a:
            continue
        m = re.search(r'pw01dud\d{2}(\d{10})', a['href'])
        hc = re.search(r'CNAME=(pw01dud[^"&\']+)', a['href'])
        h = {'horseId': m.group(1) if m else '', 'name': text(a), 'horseCname': hc.group(1) if hc else ''}
        w = tr.select_one('td.waku img')
        m = re.search(r'枠(\d)', w.get('alt', '') if w else '')
        h['waku'] = m.group(1) if m else ''
        num = tr.select_one('td.num')
        m = re.match(r'\s*(\d+)', num.get_text() if num else '')
        h['umaban'] = m.group(1) if m else ''
        h['owner'] = text(tr.select_one('p.owner'))
        jk = tr.select_one('p.jockey a') or tr.select_one('td.jockey a')
        h['jockey'] = text(jk)
        age = tr.select_one('p.age') or tr.select_one('td.age')
        h['sexAge'] = text(age).split('/')[0]
        rowtxt = text(tr)
        h['status'] = '取消' if '取消' in rowtxt else ('除外' if '除外' in rowtxt else '')
        horses.append(h)
    return horses

def parse_race_tables(html):
    soup = BeautifulSoup(html, 'html.parser')
    races = []
    for table in soup.select('table'):
        cap = table.select_one('caption .race_header')
        if not cap:
            continue
        info = parse_header(cap)
        if 'r' not in info:
            continue
        info['horses'] = parse_rows(table)
        races.append(info)
    return races

def horse_owner(html):
    soup = BeautifulSoup(html, 'html.parser')
    for dt in soup.select('dt'):
        if text(dt) == '馬主名':
            return text(dt.find_next_sibling('dd'))
    return None

def links(html, prefix):
    found = re.findall(r"doAction\('/JRADB/accessD\.html',\s*'(%s[^']*)'\)" % prefix, html)
    found += re.findall(r'CNAME=(%s[^"&\']+)' % prefix, html)
    return list(dict.fromkeys(found))

# ---------------------------------------------------------------- main
def main():
    offline = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == '--offline' else None
    clubs = load_clubs()
    f = Fetcher(offline)
    os.makedirs(DATA, exist_ok=True)

    top = f.get('pw01dli00/F3', post=True)
    lists = links(top, 'pw01drl')
    if not lists:
        print('出馬表の開催一覧が見つかりませんでした（開催がない週、またはページの形式が変わった可能性）')
        return 0
    meetings = []
    for c in lists:
        m = re.match(r'pw01drl00(\d{2})\d{4}\d{2}\d{2}(\d{8})', c)
        if m:
            d = m.group(2)
            meetings.append({'cname': c, 'venue': VENUES.get(m.group(1), m.group(1)), 'date': f'{d[:4]}-{d[4:6]}-{d[6:]}'})
    dates = sorted({x['date'] for x in meetings})
    print('開催:', ', '.join(f"{x['date']} {x['venue']}" for x in meetings), flush=True)

    cache = {}
    if os.path.exists(CACHE):
        cache = json.load(open(CACHE, encoding='utf-8'))
    club_of = cache.setdefault('clubOf', {})   # horseId -> clubId（クラブ以外は ''）
    seen_owners = {}                           # 確認用（保存しない）
    def remember(h, owner):
        seen_owners[h['horseId']] = owner
        club_of[h['horseId']] = clubs.get(norm_owner(owner), '')

    result = []
    stats = {'detail': 0, 'horse': 0}
    for mt in meetings:
        rl = f.get(mt['cname'], post=True)
        race_pages = {}
        for c in links(rl, 'pw01dde'):
            m = re.match(r'pw01dde\d{2}\d{2}\d{4}\d{2}\d{2}(\d{2})\d{8}', c)
            if m:
                race_pages[int(m.group(1))] = c
        all_pages = links(rl, 'pw01des')
        races = parse_race_tables(f.get(all_pages[0], post=True)) if all_pages else []
        if not races:  # まとめページがない場合は各レースのページを読む
            races = [r for c in race_pages.values() for r in parse_race_tables(f.get(c))]
        for race in races:
            rno = race['r']
            unknown = [h for h in race['horses'] if h['horseId'] not in club_of]
            if unknown and any(h['umaban'] for h in race['horses']) and rno in race_pages:
                detail = parse_race_tables(f.get(race_pages[rno]))
                stats['detail'] += 1
                for d in (detail[0]['horses'] if detail else []):
                    if d['owner']:
                        remember(d, d['owner'])
                unknown = [h for h in race['horses'] if h['horseId'] not in club_of]
            for h in unknown:
                if not h['horseCname']:
                    continue
                owner = horse_owner(f.get(h['horseCname'], path='/JRADB/accessU.html'))
                stats['horse'] += 1
                if owner is not None:
                    remember(h, owner)
            for h in race['horses']:
                club = club_of.get(h['horseId'], '')
                if not club:
                    continue
                result.append({
                    'key': f"{mt['date']}|{mt['venue']}|{rno}|{h['horseId']}", 'horseId': h['horseId'], 'name': h['name'],
                    'clubId': club,
                    'date': race.get('date', mt['date']), 'venue': race.get('venue', mt['venue']), 'r': rno,
                    'time': race.get('time', ''), 'raceName': race.get('raceName', ''), 'grade': race.get('grade', ''),
                    'surface': race.get('surface', ''), 'dist': race.get('dist', ''),
                    'jockey': h['jockey'], 'waku': h['waku'], 'umaban': h['umaban'], 'sexAge': h['sexAge'], 'status': h['status'],
                })
        print(f"  {mt['date']} {mt['venue']}: {len(races)}R / 累計 {len(result)} 頭 / 詳細 {stats['detail']} / 馬ページ {stats['horse']}", flush=True)

    # 確認用: クラブらしい名義なのに一致しなかったもの
    hits = {}
    for x in result:
        hits[x['clubId']] = hits.get(x['clubId'], 0) + 1
    print('クラブ別:', hits)
    miss = sorted({o for o in seen_owners.values() if re.search(r'レーシング|ホース|クラブ|サラブレッド|ファーム', o) and not clubs.get(norm_owner(o))})
    print('一致しなかったクラブらしい名義:', miss)
    order = {v: i for i, v in enumerate(VENUES.values())}
    result.sort(key=lambda x: (x['date'], order.get(x['venue'], 99), x['r'], int(x['umaban'] or 99)))
    days = [{'date': d, 'venues': [m['venue'] for m in meetings if m['date'] == d]} for d in dates]
    out = {
        'source': 'JRAホームページ 出馬表',
        'updated': datetime.now(JST).isoformat(timespec='minutes'),
        'days': days,
        'horses': result,
    }
    old = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    if {k: v for k, v in old.items() if k != 'updated'} == {k: v for k, v in out.items() if k != 'updated'}:
        print('変更なし')
    else:
        json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'data/races.json を更新: {len(result)} 頭')
    json.dump(cache, open(CACHE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    print(f'リクエスト数: {f.count}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
