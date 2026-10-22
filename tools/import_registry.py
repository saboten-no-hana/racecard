"""
JRA の「競走馬登録馬名簿」PDF（https://www.jra.go.jp/datafile/resist/）を一度だけ読み、
現役馬の「馬名 → クラブID（クラブ以外は空文字）」を data/names.json に保存する。

木曜の出馬表（馬番なし）には馬主名が載らないため、記録（cache.json）にない馬は馬のページを1頭ずつ読んでいる。
名簿で先に現役馬のクラブ判定をしておけば、木曜に読むのは名簿の後に登録された馬（主に初出走の馬）だけになる。

- PDF は文字を取り出せない作り（独自のフォント設定）なので、ページを画像にして OCR（tesseract jpn）で読む
- 表の罫線を画像から探して行と列に分け、行ごとに「馬名」の欄と「馬主（調教師）」の欄の上半分だけを読む
- 馬主名はクラブの名義（clubs.js）と照合し、クラブならクラブID、はっきりクラブ以外なら空文字、
  読み取りがあやしいものは入れない（木曜にこれまでどおり馬のページで確かめる）
- 個人馬主の名前は保存しない（保存するのは馬名とクラブIDだけ）
- 読み違えた馬名は出馬表の馬名と一致しないだけなので、結果が間違うことはない（馬のページで確かめる）

使い方:
  python3 tools/import_registry.py PDFのあるディレクトリ [--check data/races.json] [--write]
    --check: races.json のクラブ馬が名簿で正しいクラブとして見つかるかを数える（精度の確認）
    --write: data/names.json に書き出す
  python3 tools/import_registry.py --image 画像.png   # 1枚の画像で動作確認（行ごとの読み取り結果を表示）
"""
import json, os, re, subprocess, sys, tempfile, unicodedata
from difflib import SequenceMatcher
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_races as fr  # noqa: E402  clubs.js の読み込みと馬主名の正規化を共通にする

NAMES = os.path.join(fr.DATA, 'names.json')
DPI = 250
CLUB_MIN = 0.88      # これ以上クラブの名義に似ていればそのクラブ（ゆるいと「ウインレーシング」が「インゼルレーシング」になる）
OTHER_MAX = 0.45     # どのクラブの名義ともこれ未満ならクラブ以外（空文字）。間は保存しない
OTHER_MIN_LEN = 4    # クラブ以外と決めるのは、名義らしい長さで読めた時だけ（読めずに崩れた字をクラブ以外にしない）
KANA_NAME = re.compile(r'^[ァ-ヴー]{2,9}$')


def lines_of(mask_1d, min_gap=3):
    """True が続く区間の中央の位置の一覧（罫線の位置）"""
    out, start = [], None
    for i, v in enumerate(mask_1d):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start + i - 1) // 2)
            start = None
    if start is not None:
        out.append((start + len(mask_1d) - 1) // 2)
    merged = []
    for p in out:
        if merged and p - merged[-1] <= min_gap:
            merged[-1] = (merged[-1] + p) // 2
        else:
            merged.append(p)
    return merged


def table_cells(img):
    """表の罫線から、行ごとに (馬名の欄, 馬主の欄) の箱を返す"""
    g = np.asarray(img.convert('L')) < 128
    h, w = g.shape
    rows = lines_of(g.mean(axis=1) > 0.5)          # 横罫線（表の幅の半分以上が黒い行）
    if len(rows) < 3:
        return []
    top, bottom = rows[0], rows[-1]
    cols = lines_of(g[top:bottom].mean(axis=0) > 0.6)   # 縦罫線（表の高さの6割以上が黒い列）
    if len(cols) < 4:
        return []
    name_x = (cols[0], cols[1])
    owner_x = (cols[-2], cols[-1])
    cells = []
    for y0, y1 in zip(rows, rows[1:]):
        if y1 - y0 < h * 0.02:      # 見出しの細い段などは飛ばす
            continue
        cells.append(((name_x[0], y0, name_x[1], y1), (owner_x[0], y0, owner_x[1], y1)))
    return cells


def ocr(img, psm=7):
    with tempfile.NamedTemporaryFile(suffix='.png') as t:
        img.save(t.name)
        # tesseract は既定で複数スレッドを使い、並列に動かすと取り合って数倍遅くなる（10/22 確認）ので1スレッドにする
        r = subprocess.run(['tesseract', t.name, '-', '-l', 'jpn', '--psm', str(psm)],
                           capture_output=True, text=True, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
    return r.stdout


def clean_kana(s):
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s', '', s)
    s = s.replace('一', 'ー').replace('－', 'ー').replace('-', 'ー').replace('ｰ', 'ー')
    runs = re.findall(r'[ァ-ヴー]+', s)
    return max(runs, key=len) if runs else ''


def read_row(img, cell):
    (nx0, y0, nx1, y1), (ox0, _, ox1, _) = cell
    pad = 6
    hgt = y1 - y0
    # 馬名は欄の中ほど（上に「市場取引馬」、右下に登録番号の小さい字がある）。
    # 切り出し方で読めたり読み違えたりするので、3通りで読んで、馬名の形になったものをすべて候補にする
    # （読み違えた候補は出馬表の馬名と一致しないだけなので害はない）
    names = []
    for a, z, psm in ((0.15, 0.85, 7), (0.22, 0.80, 7), (0.05, 0.95, 6)):
        n = clean_kana(ocr(img.crop((nx0 + pad, y0 + int(hgt * a), nx1 - pad, y0 + int(hgt * z))), psm))
        if KANA_NAME.match(n) and n not in names:
            names.append(n)
        if len(names) >= 2 or (names and psm == 7 and a == 0.22):   # 2通り読めたか、2つ目まで試して1つ読めていれば十分
            break
    # 馬主は欄の上半分（下半分は調教師）。長い名義は縮めて印刷され、短い名義は1行で読みにくいことがあるので、
    # 1通り目で判定できなければ、2倍に拡大したもの・少し広く切り出したもので読み直す（readings の順に試す）
    owner_img = img.crop((ox0 + pad, y0 + pad, ox1 - pad, y0 + int(hgt * 0.52)))
    readings = [re.sub(r'\s', '', unicodedata.normalize('NFKC', ocr(owner_img)))]
    return names, readings, (owner_img, img.crop((ox0 + pad, y0 + pad, ox1 - pad, y0 + int(hgt * 0.60))))


def more_readings(imgs):
    small, wide = imgs
    big = small.resize((small.width * 2, small.height * 2), Image.LANCZOS)
    out = []
    for im, psm in ((big, 7), (big, 6), (wide, 6)):
        t = ocr(im, psm)
        line = next((x for x in t.splitlines() if x.strip()), '')   # 6 の時は1行目だけ（2行目は調教師）
        out.append(re.sub(r'\s', '', unicodedata.normalize('NFKC', line)))
    return out


def decide(readings, imgs, clubs):
    """馬主名の読み取りを順に試し、クラブ／クラブ以外が決まった所で止める。
    どれかがクラブと読めた時、ほかの読みがクラブ以外でもクラブの方を採る（名義の字が欠けてクラブ以外に見えることはあるが、
    クラブ以外の名義がクラブの名義にほぼ一致する形に読み違えられることはまずないため）。食い違うクラブ同士なら決めない"""
    res = [classify(r, clubs) for r in readings]
    if res[0] is None:
        extra = more_readings(imgs)
        readings += extra
        res += [classify(r, clubs) for r in extra]
    cl = {c for c in res if c}
    if len(cl) == 1:
        return cl.pop(), readings
    if len(cl) > 1:
        return None, readings
    return ('' if '' in res else None), readings


DAKU = str.maketrans('ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポヴァィゥェォャュョッヮ',
                     'カキクケコサシスセソタチツテトハヒフヘホハヒフヘホウアイウエオヤユヨツワ')
GENERIC = ['サラフレツトクラフ', 'ホースクラフ', 'レーシンク', 'レースホース', 'オーナース', 'ファーム', 'クラフ', 'ホース', 'レース']


def loose(s):
    """OCR の読み違いが多い所をならす: 濁点・半濁点を取り、小さい字を大きくし、記号を除く"""
    return re.sub(r'[・･.。、,\-－‐()（）<>＞＜|｜\'"]', '', s.replace('一', 'ー').translate(DAKU))


def core(key):
    """クラブの名義から、ほかの名義にもよくある語（レーシング・ホースクラブ など）を除いた固有の部分"""
    k = loose(key)
    for g in GENERIC:
        k = k.replace(loose(g), '')
    return k


def classify(owner, clubs):
    """馬主名（OCR）→ クラブID / ''（クラブ以外）/ None（あやしいので保存しない）"""
    if not owner:
        return None
    n = fr.norm_owner(owner).replace('一', 'ー')
    n = re.sub(r'^\(?[株有合同覆称症]\)?', '', n)   # ㈱㈲ は「覆」「称」などに読み違えやすい
    if n.endswith('氏'):
        return ''     # 個人馬主
    ln = loose(n)
    best, bid = 0.0, None
    for key, cid in clubs.items():
        lk = loose(key)
        r = SequenceMatcher(None, ln, lk).ratio()
        if len(key) >= 5 and key in n:    # 「ウイン」のような短い名義は部分一致にしない（ウイン〇〇 などを拾わないため）
            r = max(r, 0.95)
        # 固有の部分（ノルマンディー・ブリーダーズユニオン・ラフィアン など、5字以上。ライオン など4字以下は一般の名義にも含まれやすいので使わない）が読めていて、全体もある程度似ていればそのクラブ
        # （長い名義は縮めて印刷され、前後の字が崩れたり欠けたりしやすい）
        c = core(key)
        w = min(6, len(c))
        if len(c) >= 5 and any(c[i:i + w] in ln for i in range(len(c) - w + 1)) and r >= 0.55:
            r = max(r, 0.9)
        if r > best:
            best, bid = r, cid
    if best >= CLUB_MIN:
        return bid
    if best < OTHER_MAX and len(n) >= OTHER_MIN_LEN:
        return ''     # どのクラブの名義とも似ていない（個人・一般の法人）。クラブの名義が崩れて読めた時にここへ来ないよう、ゆるめない
    return None


def read_image(img, clubs):
    out = []
    for cell in table_cells(img):
        names, readings, imgs = read_row(img, cell)
        if names:
            c, readings = decide(readings, imgs, clubs)
            out.append((names, readings, c))
    return out


def read_page(job):
    """1ページを画像にして読む（ページごとに別のプロセスで並列に動かす）"""
    pdf, page = job
    clubs = fr.load_clubs()
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(['pdftoppm', '-r', str(DPI), '-gray', '-png', '-f', str(page), '-l', str(page), '-singlefile', pdf,
                        os.path.join(d, 'p')], check=True)
        return pdf, page, read_image(Image.open(os.path.join(d, 'p.png')).convert('RGB'), clubs)


def report(line):
    """結果の行を、ログに加えて Actions の注記（公開 API でも読める）と実行結果のページの要約にも出す"""
    print(line, flush=True)
    if os.environ.get('GITHUB_ACTIONS'):
        print('::notice::' + line.replace('%', '%25').replace('\n', '%0A'), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(line + '\n\n')


def main():
    args = sys.argv[1:]
    clubs = fr.load_clubs()
    if args and args[0] == '--image':
        for names, readings, c in read_image(Image.open(args[1]).convert('RGB'), clubs):
            print(f'{"／".join(names)}\t{c!r}\t{" | ".join(readings)}')
        return 0
    src = args[0]
    jobs = []
    for pdf in sorted(f for f in os.listdir(src) if f.startswith('registration_') and f.endswith('.pdf') and 'count' not in f):
        info = subprocess.run(['pdfinfo', os.path.join(src, pdf)], capture_output=True, text=True).stdout
        n = int(re.search(r'Pages:\s+(\d+)', info).group(1))
        jobs += [(os.path.join(src, pdf), i) for i in range(1, n + 1)]
    print('ページ数:', len(jobs), flush=True)
    names, bad, stats = {}, set(), {'rows': 0, 'club': 0, 'other': 0, 'unsure': 0, 'dup': 0}
    raw = {}   # 確認用: 馬名の候補 → (判定, 馬主名の読み)。races.json のクラブ馬（名義はクラブ）についてだけログに出す
    per_file = {}
    with ProcessPoolExecutor(os.cpu_count() or 2) as ex:
        results = []
        for r in ex.map(read_page, jobs):
            results.append(r)
            if len(results) % 25 == 0 or len(results) == len(jobs):
                print(f'{len(results)}/{len(jobs)} ページ', flush=True)
    for path, page, rows in results:
        pdf = os.path.basename(path)
        per_file[pdf] = per_file.get(pdf, 0) + len(rows)
        for cands, readings, c in rows:
            for n in cands:
                raw[n] = (c, readings)
            stats['rows'] += 1
            if c is None:
                stats['unsure'] += 1
                continue
            stats['club' if c else 'other'] += 1
            for name in cands:
                if name in bad:
                    continue
                if name in names and names[name] != c:
                    stats['dup'] += 1
                    names.pop(name)     # 同じ馬名で判定が食い違ったら使わない
                    bad.add(name)
                    continue
                names[name] = c
    report(f'ファイル別の行数: {per_file}')
    report(f"集計: {stats} ／ 保存する馬名: {len(names)}（うちクラブ {sum(1 for v in names.values() if v)}）")

    if '--check' in args:
        races = json.load(open(args[args.index('--check') + 1], encoding='utf-8'))
        club = {}
        for h in races['horses']:
            club[h['name']] = h['clubId']
        ok = sum(1 for n, c in club.items() if names.get(n) == c)
        miss = sorted(n for n in club if n not in names)
        wrong = sorted(n for n, c in club.items() if n in names and names[n] != c)
        report(f'精度の確認: races.json のクラブ馬 {len(club)} 頭のうち 正しいクラブ {ok}／名簿で見つからない {len(miss)}／判定が違う {len(wrong)}')
        report(f'見つからない（初出走・名簿の後の登録・読み違い）: {miss}')
        report(f'見つからないうち、名簿に馬名はあった（馬主名の判定を保留）: {[(n, club[n], raw[n][1]) for n in miss if n in raw]}')
        report(f'見つからないうち、名簿に馬名もない: {[n for n in miss if n not in raw]}')
        report(f'判定が違う（要確認）: {[(n, club[n], names[n], raw.get(n, (None, []))[1]) for n in wrong]}')

    # 名簿の時点（名簿のページの「9月27日（日曜）現在の情報です」）
    today = datetime.now(fr.JST).date()
    asof = today.isoformat()
    idx = os.path.join(src, 'index.html')
    if os.path.exists(idx):
        raw = open(idx, 'rb').read()
        try:
            page = raw.decode('utf-8')
        except UnicodeDecodeError:
            page = raw.decode('cp932', errors='replace')
        m = re.search(r'(\d{1,2})月(\d{1,2})日（.{1,3}）現在', page)
        if m:
            mo, dy = int(m.group(1)), int(m.group(2))
            asof = f'{today.year - (1 if mo > today.month else 0)}-{mo:02d}-{dy:02d}'
    report(f'名簿の時点: {asof}')
    from collections import Counter
    cnt = Counter(v for v in names.values() if v)
    report('クラブ別の頭数（名簿で判定できたクラブ馬）: ' + '、'.join(f'{k} {v}' for k, v in cnt.most_common()) + f'（計 {sum(cnt.values())}）')

    if '--write' in args:
        json.dump({'source': 'JRA 競走馬登録馬名簿（OCR）', 'imported': today.isoformat(), 'asof': asof,
                   'names': dict(sorted(names.items()))},
                  open(NAMES, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print('data/names.json を書き出し:', len(names))
    return 0


if __name__ == '__main__':
    sys.exit(main())
