"""OGP 画像（og.png、1200×630）を作り直す

画面と同じ描画処理で「縦長」のカードを架空の馬名で描き、左に説明文、右にそのカードを置いた
1200×630 の画像にする（X のカードは横長 1.91:1 で表示されるため、縦長のカードを丸ごと見せる形にしている）。

使い方（リポジトリ直下で）:
    pip install playwright && python3 -m playwright install chromium
    python3 tools/make_og.py            # og.png を上書き
    python3 tools/make_og.py out.png    # 別のファイルに書き出す

- 画像内の文字は同梱の IPAexゴシック。勝負服はクラブの CC0 画像（silks/）
- data/races.json は 404 にして、実際の出馬表で馬が上書きされないようにする
- 画面の描画（性齢・斤量の表示など）を変えたら、これを実行して og.png も作り直す
"""
import base64, functools, http.server, json, os, sys, threading

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'og.png')

# 架空の馬（クラブは実在、勝負服は CC0 画像）。金曜以降（枠順確定後）の見た目
HORSES = [
    dict(name='ミホンノウマ', clubId='silk', date='2026-10-24', venue='東京', r=9, time='14:25', raceName='〇〇特別（2勝クラス）',
         surface='芝', dist=1800, jockey='騎手名', sexAge='牡3', weight='56.0', waku='2', umaban='3', kuchi='none'),
    dict(name='サンプルホース', clubId='carrot', date='2026-10-24', venue='東京', r=11, time='15:45', raceName='〇〇ステークス（GII）',
         surface='芝', dist=1800, jockey='騎手名', sexAge='牝4', weight='55.0', waku='4', umaban='7', kuchi='win'),
    dict(name='ダミーステップ', clubId='normandy', date='2026-10-25', venue='京都', r=10, time='15:05', raceName='〇〇ステークス（L）',
         surface='芝', dist=2000, jockey='騎手名', sexAge='牡5', weight='57.0', waku='7', umaban='15', kuchi='wait'),
    dict(name='カセツノホシ', clubId='lion', date='2026-10-25', venue='東京', r=8, time='13:50', raceName='3歳以上1勝クラス',
         surface='ダ', dist=1800, jockey='騎手名', sexAge='牝3', weight='55.0', waku='5', umaban='9', kuchi='none'),
]

STATE = {
    'settings': {'title': '今週の出走予定', 'post': None, 'handle': '@your_account', 'theme': 'turf', 'size': '4:5',
                 'showKuchi': True, 'order': 'venue', 'showCount': True, 'showAgeWeight': True, 'skipPostGuide': True},
    'horses': [dict(h, id=f'og{i}', ownerLabel='', status='', photo='', customSilks=None) for i, h in enumerate(HORSES)],
}

# 右にカード、左に説明文。文字は IPAexゴシック
COMPOSE = r"""
() => {
  const card = document.getElementById('cv');
  const W = 1200, H = 630, cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const c = cv.getContext('2d'), IPA = '"IPAexGothic",sans-serif';
  /* 背景（「芝」のデザインと同じ配色・斜めの帯） */
  c.fillStyle = '#123d2b'; c.fillRect(0, 0, W, H);
  c.save(); c.translate(W/2, H/2); c.rotate(-0.38); const bw = W*.085, D = Math.hypot(W, H);
  c.fillStyle = 'rgba(255,255,255,0.035)'; for (let i = -20; i < 20; i += 2) c.fillRect(i*bw, -D, bw, D*2); c.restore();
  const g = c.createLinearGradient(0, H*.45, 0, H); g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, '#0b2a1d'); c.fillStyle = g; c.fillRect(0, 0, W, H);
  /* カード（縦長）: 上下に余白を取り、影と角丸をつける */
  const ch = H - 64, cw = Math.round(card.width * ch / card.height), cx = W - 56 - cw, cy = 32, rr = 14;
  const rect = () => { c.beginPath(); c.roundRect(cx, cy, cw, ch, rr); };
  c.save(); c.shadowColor = 'rgba(0,0,0,0.5)'; c.shadowBlur = 36; c.shadowOffsetY = 12; rect(); c.fillStyle = '#0b2a1d'; c.fill(); c.restore();
  c.save(); rect(); c.clip(); c.imageSmoothingQuality = 'high'; c.drawImage(card, cx, cy, cw, ch); c.restore();
  c.save(); rect(); c.strokeStyle = 'rgba(255,255,255,0.18)'; c.lineWidth = 2; c.stroke(); c.restore();
  /* 左の説明文 */
  const x = 64, maxW = cx - x - 48;
  const fit = (t, w, size, mw = maxW) => { let s = size; do { c.font = `${w} ${s}px ${IPA}`; } while (c.measureText(t).width > mw && --s > 10); return s; };
  c.textBaseline = 'alphabetic';
  let y = 100;
  c.fillStyle = '#e2bd5c'; c.font = `700 22px ${IPA}`; c.fillText('一口馬主の出走告知を、1枚の画像に', x, y);
  y += 30; c.fillStyle = '#f4efe1';
  const s1 = fit('出資馬出走', 700, 76); c.fillText('出資馬出走', x, y + s1);
  y += s1 * 1.18; const s2 = fit('カードメーカー', 700, 76); c.font = `700 ${s2}px ${IPA}`; c.fillText('カードメーカー', x, y + s2);
  y += s2 + 30; c.fillStyle = '#e2bd5c'; c.fillRect(x, y, 84, 4); c.fillStyle = 'rgba(255,255,255,0.10)'; c.fillRect(x + 94, y + 1, maxW - 94, 2);
  y += 50;
  const lines = ['一口クラブ馬を自動でリストアップ', 'レース名・騎手名・馬番（決定後）なども自動表示', '背景などのカスタムも可能', '複数クラブ対応・無料・登録不要'];
  const ls = Math.min(...lines.map(t => fit(t, 700, 25, maxW - 24)));  /* 箇条書きは同じ大きさにそろえる */
  for (const t of lines) {
    c.fillStyle = '#e2bd5c'; c.beginPath(); c.arc(x + 7, y - 9, 5, 0, Math.PI*2); c.fill();
    c.fillStyle = '#f4efe1'; c.font = `700 ${ls}px ${IPA}`; c.fillText(t, x + 24, y); y += 42;
  }
  c.fillStyle = '#b7c8b6'; c.font = `700 22px ${IPA}`; c.fillText('saboten-no-hana.github.io/racecard', x, H - 56);
  return cv.toDataURL('image/png');
}
"""


def main():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{srv.server_address[1]}/index.html'
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={'width': 1280, 'height': 900})
            page.route('**/data/races.json*', lambda r: r.fulfill(status=404, body=''))
            page.route('**/fonts.googleapis.com/**', lambda r: r.abort())
            page.route('**/fonts.gstatic.com/**', lambda r: r.abort())
            page.add_init_script('localStorage.setItem("racecard.v2", %s)' % json.dumps(json.dumps(STATE, ensure_ascii=False)))
            page.goto(url)
            page.wait_for_function("document.getElementById('out').src.startsWith('data:image')")
            page.wait_for_function("document.fonts.check('40px IPAexGothic', '出資馬')")
            page.wait_for_timeout(800)  # 勝負服画像の読み込み後の描き直しを待つ
            data = page.evaluate(COMPOSE)
            b.close()
    finally:
        srv.shutdown()
    with open(OUT, 'wb') as f:
        f.write(base64.b64decode(data.split(',', 1)[1]))
    print('書き出した:', OUT)


if __name__ == '__main__':
    main()
