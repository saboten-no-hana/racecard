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
                     ('株ノルマンディーサラブレッドレ一シング', 'normandy'), ('株ウイン', 'win'), ('BloomingRacing', 'blooming'),
                     # 10/22 の名簿で実際にあった読み違い（濁点が取れる・前後の字が崩れる・小さい字）
                     ('除ダルプリーダーズ・ユニオ', 'union'), ('机友駿ホースクラフ', 'yushun'), ('條ノルマンデイーサフブ', 'normandy'),
                     ('覆サラフレッドクラブ・ラフィア', 'ruffian'), ('株ウィン', 'win'), ('覆キャロット', 'carrot')]:
            self.check(o, c)

    def test_not_club(self):
        for o in ['手嶋康雄氏', '株ノースヒルズ', 'ディアレストクラブ株']:
            self.check(o, '')

    def test_unsure(self):
        # 似ているがクラブではない名義・読めずに崩れた字は、どちらとも決めない（木曜に馬のページで確かめる）
        for o in ['株ウインレーシング', '株Gリビエール・レーシング', '症', '馬。主', '', '株ライオンズクラブ', '株グリーンウッド', '有サンデーヒルズ',
                  'レッドレーシンダー']:
            self.check(o, None)

    def test_decide_needs_all_readings_for_not_club(self):
        """読み直しのどれかが判定できなければ、クラブ以外とは決めない（崩れたクラブの名義をクラブ以外にしない）"""
        from unittest import mock
        garbled = ['レッドレーシング=', '愉ブノルレマンブイーザサフブ', '全ブクレマプンブイーサフブ']   # 10/22 の実例（ノルマンディー）
        with mock.patch.object(ir, 'more_readings', lambda imgs: garbled):
            self.assertIsNone(ir.decide(['レッドレーシングー'], None, self.clubs)[0])
        with mock.patch.object(ir, 'more_readings', lambda imgs: ['手嶋康雄氏'] * 3):
            self.assertEqual(ir.decide(['株ノースヒルズ'], None, self.clubs)[0], '')
        with mock.patch.object(ir, 'more_readings', lambda imgs: ['覆キャロットファーム', '株ノースヒルズ', '']):
            self.assertEqual(ir.decide(['症'], None, self.clubs)[0], 'carrot')

    def test_kana_name(self):
        self.assertEqual(ir.clean_kana('ア イ ア ム ス テ キ\n'), 'アイアムステキ')
        self.assertEqual(ir.clean_kana('アイアムアヒ一ロ一'), 'アイアムアヒーロー')


if __name__ == '__main__':
    unittest.main()
