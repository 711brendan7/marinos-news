#!/usr/bin/env python3
"""analyze.py の純粋関数のユニットテスト（追加ライブラリ不要・標準 unittest）。

実行方法:
    python3 -m unittest note.test_analyze -v
    (または note/ ディレクトリ内で) python3 test_analyze.py
"""
import unittest

from analyze import band


class TestBand(unittest.TestCase):
    def test_free_or_membership(self):
        self.assertEqual(band(0), "0(会員/マガジン)")
        self.assertEqual(band(-100), "0(会員/マガジン)")

    def test_boundaries_are_inclusive_lower(self):
        # 各バンドの下限値そのものは「その帯」に入る
        self.assertEqual(band(1), "1〜499")
        self.assertEqual(band(500), "500〜999")
        self.assertEqual(band(1000), "1000〜1999")
        self.assertEqual(band(2000), "2000〜4999")
        self.assertEqual(band(5000), "5000以上")

    def test_boundaries_just_below(self):
        # 上限の1つ下は前の帯に入る
        self.assertEqual(band(499), "1〜499")
        self.assertEqual(band(999), "500〜999")
        self.assertEqual(band(1999), "1000〜1999")
        self.assertEqual(band(4999), "2000〜4999")

    def test_large_price(self):
        self.assertEqual(band(100000), "5000以上")


if __name__ == "__main__":
    unittest.main()
