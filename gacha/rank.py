#!/usr/bin/env python3
"""③問屋カートン仕入れモデルで全品の利益を試算しランキング化。
利益/コンプ = median - median*0.10 - 送料 - (定価コンプ * 掛け率)
定価コンプ = 種類数 * 単価。掛け率0.70、1回転40個で均等排出(ダブり無し)前提。
"""
import json

KAKERITSU = 0.70
# 判明している種類数・単価。無いものは既定(5種,400,送料350)。est=Trueは推定。
SPEC = {
    "SR+ スパイダーマン DELUXE": (5, 500, 350, False),
    "ポケモン ぎらぎらサンシャイン5": (4, 400, 350, False),
    "映画ちいかわ 人魚の島 もっちるフェイスマスコット": (5, 500, 400, False),
    "おねむたん 鬼滅の刃 拾参ノ型": (5, 300, 350, False),
    "キン肉マン キンケシ27": (6, 300, 350, False),
    "機動戦士ガンダム EXCEED MODEL ザクヘッド リブート1": (5, 600, 400, False),
    "HGドラゴンボール Another2": (5, 500, 400, False),
    "PUTITTO ヒグチユウコ": (6, 500, 350, False),
    "銀魂 ねむらせ隊": (5, 400, 350, False),
    "DEATH NOTE コレクションフィギュア RICH": (5, 500, 350, False),
    "ジョジョの奇妙な冒険 カプセルフィギュア RE-Collect05": (5, 500, 350, False),
    "本当に録音再生 ポータブルゲーム機マスコット": (5, 500, 400, False),
    "ルミナスメカニカルビークル MAZDA RX-7": (4, 600, 400, False),
    "ホビーガチャ ワイルドスピード MEGAMAX": (5, 500, 400, False),
    "こびとづかん カクレモモジリコレクション": (5, 400, 350, False),
    "富士ホーロー MOOMIN ミニコレクション2": (5, 500, 400, False),
    "超宇宙刑事ギャバン インフィニティ": (5, 500, 400, False),
    "まちぼうけ 仮面ライダー その4": (5, 400, 350, False),
    "刃牙 すわらせ隊": (5, 400, 350, False),
    "TOY STORY Funny Time": (5, 400, 400, False),
    "LOONEY TUNES ミニチュアパッケージチャーム": (5, 400, 350, False),
    "パンダの穴 わんわんおでん": (5, 500, 400, False),
    "くまのプーさん コスチュームフィギュアマスコット": (5, 500, 400, False),
    "ポケモン メタモンいっぱいコレクション": (5, 400, 350, False),
    "ミスター ミセス ポテトヘッド めじるしガチャマスコット": (6, 500, 350, False),
    "トムとジェリー 天使と悪魔めじるしガチャマスコット": (6, 500, 350, False),
    "PINGU マスコットフィギュア": (5, 500, 400, False),
    # ぬいぐるみ系は送料高め・単品売り混在で信頼度低い
    "洗われた猫 ぬいぐるみ": (4, 700, 700, True),
    "うさぎのモフィ ぬいぐるみマスコット": (5, 500, 600, True),
    "mofusand ねぶくろにゃん ぬいぐるみ": (4, 700, 700, True),
    "拒否犬ストラップ2": (5, 500, 350, True),
    "肩ズンFig カラフルピーチ": (6, 500, 400, True),
    "TOY STORY サウンドロップ": (6, 500, 400, True),
    "BT21 ぬいぐるみクリップ": (8, 500, 500, True),
}
DEFAULT = (5, 400, 350, True)


def calc_profit(name, median, spec=SPEC, default=DEFAULT, kakeritsu=KAKERITSU):
    """1商品ぶんの利益試算を行い、rank_result.json の1行分のdictを返す（純粋関数・テスト用に分離）。"""
    types, unit, ship, est = spec.get(name, default)
    retail_set = types * unit
    cost = retail_set * kakeritsu
    fee = median * 0.10 + ship
    profit = median - fee - cost
    sets_per_carton = 40 / types
    profit_carton = profit * sets_per_carton
    return {
        "name": name, "median": median, "types": types,
        "unit": unit, "retail": retail_set, "profit": round(profit),
        "carton": round(profit_carton), "est": est,
    }


def build_rows(data):
    """scan_result.json 相当のリストから、実売5件未満を除外して利益ランキング行を作る。"""
    rows = []
    for d in data:
        if not d.get("median") or d["n"] < 5:  # 実売5件未満は信頼度不足で除外
            continue
        row = calc_profit(d["name"], d["median"])
        row["n"] = d["n"]
        rows.append(row)
    rows.sort(key=lambda r: r["profit"], reverse=True)
    return rows


def main():
    data = json.load(open("scan_result.json", encoding="utf-8"))
    rows = build_rows(data)

    print(f"{'#':>2} {'商':>1} {'利益/ｺﾝﾌﾟ':>8} {'/ｶｰﾄﾝ':>7} {'実売':>6} {'定価':>6} {'件':>3}  商品")
    print("-" * 92)
    for i, r in enumerate(rows, 1):
        flag = "⚠" if r["est"] else "✓"
        print(f"{i:>2} {flag} ¥{r['profit']:>+7,} ¥{r['carton']:>+6,} ¥{r['median']:>5,} ¥{r['retail']:>5,} {r['n']:>3}  {r['name']}")

    json.dump(rows, open("rank_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    pos = [r for r in rows if r["profit"] > 0]
    print(f"\n黒字候補 {len(pos)}件 / 試算対象 {len(rows)}件（実売5件以上のみ）")


if __name__ == "__main__":
    main()
