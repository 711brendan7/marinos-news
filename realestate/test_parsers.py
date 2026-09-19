#!/usr/bin/env python3
"""parsers.py の正規表現ベース抽出関数のユニットテスト（標準 unittest）。

実行方法: realestate/ ディレクトリ内で
    ./venv/bin/python3 test_parsers.py
（bs4 が venv 前提のため、システムの python3 では実行できない）
"""
import unittest

from parsers import is_rental, norm_price, norm_area, extract_layout, extract_address


class TestIsRental(unittest.TestCase):
    def test_detects_rental_keywords(self):
        self.assertTrue(is_rental("賃料 8万円/月"))
        self.assertTrue(is_rental("敷金1ヶ月 礼金1ヶ月"))

    def test_sale_text_is_not_rental(self):
        self.assertFalse(is_rental("価格 2,280万円 売買物件"))

    def test_empty_or_none(self):
        self.assertFalse(is_rental(""))
        self.assertFalse(is_rental(None))


class TestNormPrice(unittest.TestCase):
    def test_man_yen(self):
        self.assertEqual(norm_price("価格：2,280万円"), "2,280万円")

    def test_oku_yen(self):
        self.assertEqual(norm_price("1億2,000万円"), "1億2,000万円")

    def test_no_price_returns_empty(self):
        self.assertEqual(norm_price("価格応相談"), "")

    def test_empty_input(self):
        self.assertEqual(norm_price(""), "")


class TestNormArea(unittest.TestCase):
    def test_square_meter_symbol(self):
        self.assertEqual(norm_area("土地面積 89.24㎡"), "89.24㎡")

    def test_m2_notation_converted(self):
        self.assertEqual(norm_area("敷地面積 120.5m2"), "120.5㎡")

    def test_m_with_space_2_notation(self):
        self.assertEqual(norm_area("120.5m 2"), "120.5㎡")

    def test_no_area_returns_empty(self):
        self.assertEqual(norm_area("面積不明"), "")


class TestExtractLayout(unittest.TestCase):
    def test_ldk_pattern(self):
        self.assertEqual(extract_layout("間取り：3LDK"), "3LDK")

    def test_oneroom_keyword(self):
        self.assertEqual(extract_layout("ワンルームタイプ"), "ワンルーム")

    def test_1r_prefix(self):
        # 「\d[SLDKR]{1,4}」が先に "1R" にマッチするため、"1R"表記のまま返る
        # （ワンルームへのフォールバック分岐は「1R」表記には実質到達しない）。
        # "1R" 自体が間取り表記として一般的なため、これは許容仕様として扱う。
        self.assertEqual(extract_layout("1R 20㎡"), "1R")

    def test_no_match(self):
        self.assertEqual(extract_layout("詳細はお問い合わせください"), "")


class TestExtractAddress(unittest.TestCase):
    def test_prefecture_prefixed_address(self):
        self.assertEqual(
            extract_address("所在地：神奈川県横須賀市佐島３丁目"),
            "神奈川県横須賀市佐島３丁目",
        )

    def test_fallback_without_prefecture(self):
        addr = extract_address("三浦市初声町")
        self.assertIn("市", addr)

    def test_avoids_kukakuzu_false_positive(self):
        # 「区画図」を市区町村と誤検出しない
        self.assertEqual(extract_address("区画図はこちら"), "")


if __name__ == "__main__":
    unittest.main()
