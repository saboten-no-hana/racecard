"""登録馬名簿の取り込み（tools/import_registry.py）の馬主名の判定のテスト。OCR そのものは動かさない。"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import import_registry as ir
    import fetch_races as fr
except ImportError as e:   # PIL などがない環境
    ir = None
    REASON = str(e)


@unittest.skipIf(ir is None, 'import_registry を読み込めない')
class TestClassify(unittest.TestCase):
    def setUp(self):
        self.clubs = fr.load_clubs()

    def check(self, owner, want):
        self.assertEqual(ir.classify(owner, self.clubs), want, owner)

    def test_clubs(self):
        # ㈱㈲ は「覆」「称」などに読み違えることがある
        for o, c in [('覆キャロットファーム', 'carrot'), ('株社台レースホース', 'shadai'), ('称G1レーシング', 'g1'),
                     ('株ノルマンディーサラブレッドレ一シング', 'normandy'), ('株ウイン', 'win'), ('BloomingRacing', 'blooming')]:
            self.check(o, c)

    def test_not_club(self):
        for o in ['手嶋康雄氏', '株ノースヒルズ', 'ディアレストクラブ株']:
            self.check(o, '')

    def test_unsure(self):
        # 似ているがクラブではない名義・読めずに崩れた字は、どちらとも決めない（木曜に馬のページで確かめる）
        for o in ['株ウインレーシング', '株Gリビエール・レーシング', '覆キャロット', '症', '馬。主', '']:
            self.check(o, None)

    def test_kana_name(self):
        self.assertEqual(ir.clean_kana('ア イ ア ム ス テ キ\n'), 'アイアムステキ')
        self.assertEqual(ir.clean_kana('アイアムアヒ一ロ一'), 'アイアムアヒーロー')


if __name__ == '__main__':
    unittest.main()
