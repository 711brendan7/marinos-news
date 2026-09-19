#!/usr/bin/env python3
"""rank.py の利益試算ロジックのユニットテスト（追加ライブラリ不要・標準 unittest）。

実行方法: gacha/ ディレクトリ内で python3 test_rank.py
"""
import unittest

from rank import calc_profit, build_rows, KAKERITSU


class TestCalcProfit(unittest.TestCase):
    def test_known_spec_matches_manual_calc(self):
        # SR+ スパイダーマン DELUXE: (5種, 500円, 送料350, est=False)
        row = calc_profit("SR+ スパイダーマン DELUXE", median=3000)
        retail = 5 * 500  # 2500
        cost = retail * KAKERITSU  # 1750
        fee = 3000 * 0.10 + 350  # 650
        expected_profit = round(3000 - fee - cost)  # 3000-650-1750=600
        self.assertEqual(row["profit"], expected_profit)
        self.assertEqual(row["est"], False)
        self.assertEqual(row["retail"], retail)

    def test_unknown_name_uses_default_spec(self):
        row = calc_profit("未知の商品XYZ", median=2000)
        self.assertEqual(row["types"], 5)
        self.assertEqual(row["unit"], 400)
        self.assertTrue(row["est"])  # DEFAULTはest=True

    def test_carton_scales_with_sets_per_carton(self):
        row = calc_profit("SR+ スパイダーマン DELUXE", median=3000)
        # 1回転40個 / 5種 = 8セット分
        self.assertEqual(row["carton"], row["profit"] * 8)


class TestBuildRows(unittest.TestCase):
    def test_excludes_low_sample_and_no_median(self):
        data = [
            {"name": "A", "median": 1000, "n": 3},   # n<5 → 除外
            {"name": "B", "median": None, "n": 10},  # median無し → 除外
            {"name": "C", "median": 1000, "n": 5},   # 対象
        ]
        rows = build_rows(data)
        self.assertEqual([r["name"] for r in rows], ["C"])

    def test_sorted_by_profit_descending(self):
        data = [
            {"name": "未知A", "median": 500, "n": 10},
            {"name": "未知B", "median": 5000, "n": 10},
        ]
        rows = build_rows(data)
        profits = [r["profit"] for r in rows]
        self.assertEqual(profits, sorted(profits, reverse=True))


if __name__ == "__main__":
    unittest.main()
