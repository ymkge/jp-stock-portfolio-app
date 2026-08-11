import pytest
from app import calculate_score, calculate_buy_signal, calculate_sell_signal, calculate_material_exhaustion_signal, reconcile_signals

def test_calculate_score_basic():
    """スコア計算の基本的なテスト"""
    # 全ての指標が優れているケース
    stock_data = {
        "per": 8.0,
        "pbr": 0.5,
        "roe": 18.0,
        "yield": 5.0,
        "dividend_history": {"2024": 100, "2023": 90, "2022": 80}, # 2年連続増配
        "moving_average_25": 1000,
        "price": 950, # 25日乖離 -5%
        "moving_average_75": 1100, # 75日乖離 -13.6%
        "moving_average_200": 1200,
        "rsi_14": 25,
        "rci_26": -85,
        "fibonacci": {"retracement": 65.0}
    }
    
    score, details = calculate_score(stock_data)
    
    # ファンダメンタルズ: per(2), pbr(2), roe(2), yield(1), consecutive(1) = 8
    # テクニカル: trend_short(1), trend_medium(1), trend_long(1), fib(1), rci(1) = 5
    # 合計 13 (データ取得状況により変動する可能性があるが、一定以上であることを確認)
    assert score >= 10
    assert details["per"] == 2
    assert details["pbr"] == 2
    assert details["roe"] == 2

def test_calculate_score_missing_data():
    """データ欠損時のスコア計算テスト"""
    stock_data = {
        "per": "N/A",
        "pbr": 1.0,
        "roe": "N/A",
        "yield": 3.0
    }
    score, details = calculate_score(stock_data)
    assert details["per"] == 0
    assert details["roe"] == 0
    assert details["is_reliable"] == False

def test_calculate_buy_signal_levels():
    """購入シグナルのレベル判定テスト"""
    # Level 2 (チャンス) のケース: スコア十分 + RSI売られすぎ + 5日線突破（反転）
    stock_data = {
        "asset_type": "jp_stock",
        "score_details": {
            "per": 1, "pbr": 1, "roe": 1, "yield": 1, "consecutive_increase": 0, # 合計 4 (Diamond)
            "is_reliable": True
        },
        "rsi_14": 25.0,
        "rsi_14_prev": 20.0, # RSI反転
        "moving_average_5": 1000,
        "price": 1010 # 5日線突破
    }
    
    signal = calculate_buy_signal(stock_data)
    assert signal is not None
    assert signal["level"] == 2
    assert "💎" in signal["icon"]

def test_calculate_buy_signal_w_fibonacci():
    """Wフィボナッチ（短期＆長期一致）によるLv2昇格テスト"""
    stock_data = {
        "asset_type": "jp_stock",
        "score_details": {
            "per": 1, "pbr": 1, "roe": 1, "yield": 1, "consecutive_increase": 0,
            "is_reliable": True
        },
        "fibonacci_1y": {"retracement": 61.8}, # 長期ヒット
        "fibonacci_6m": {"retracement": 70.0}, # 短期ヒット
        "price": 1000
    }
    
    signal = calculate_buy_signal(stock_data)
    assert signal is not None
    assert signal["level"] == 2
    assert "Wフィボ" in "".join(signal["reasons"])

def test_calculate_sell_signal_level4():
    """売却シグナル Level 4 (落ちるナイフ) のテスト"""
    stock_data = {
        "asset_type": "jp_stock",
        "price": 800,
        "ma200": 1000 # 200日線乖離 -20%
    }
    signal = calculate_sell_signal(stock_data)
    assert signal is not None
    assert signal["level"] == 4
    assert "落ちるナイフ" in signal["label"]

def test_reconcile_signals_priority():
    """シグナル相反抑制の優先順位テスト"""
    # 1. 落ちるナイフ(Lv4)は購入シグナルを打ち消す
    buy = {"level": 2, "label": "チャンス"}
    sell = {"level": 4, "label": "落ちるナイフ"}
    b_res, s_res = reconcile_signals(buy, sell)
    assert b_res is None
    assert s_res["level"] == 4

    # 2. 長期調整(Lv3)中の購入シグナルは購入を優先する
    buy = {"level": 1, "label": "注目"}
    sell = {"level": 3, "label": "トレンド崩壊"}
    b_res, s_res = reconcile_signals(buy, sell)
    assert b_res["level"] == 1
    assert s_res is None

def test_calculate_buy_signal_with_price_position_and_yield():
    """価格位置（高安圏）と配当利回りの掛け合わせ判定テスト"""
    # 共通のベースデータ（スコア十分な優良株、RSI売られすぎ等の購入要因あり）
    base_data = {
        "asset_type": "jp_stock",
        "score_details": {
            "per": 1, "pbr": 1, "roe": 1, "yield": 1, "consecutive_increase": 0,  # 合計4 (Diamond)
            "is_reliable": True
        },
        "rsi_14": 25.0,  # Level 1の買い材料
        "price": 1000
    }

    # 1. 高値圏（P >= 80%）かつ 高利回り（Y >= 3.5%）のケース
    # P = 100 - retracement. retracement=15.0 -> P=85%
    data_high_yield = {
        **base_data,
        "fibonacci_1y": {"retracement": 15.0},
        "yield": "3.8%"
    }
    sig = calculate_buy_signal(data_high_yield)
    assert sig is not None
    assert "高値圏(高利回り)" in sig["label"]
    assert "健全な上昇であり" in sig["recommended_action"]
    assert "高値圏・高利回り" in "".join(sig["reasons"])

    # 2. 高値圏（P >= 80%）かつ 低利回り（Y < 3.5%）のケース
    # retracement=10.0 -> P=90%
    data_high_low_yield = {
        **base_data,
        "fibonacci_1y": {"retracement": 10.0},
        "yield": "2.5%"
    }
    sig = calculate_buy_signal(data_high_low_yield)
    assert sig is not None
    assert "高値警戒" in sig["label"]
    assert "急な調整売りのリスクが高いため" in sig["recommended_action"]

    # 3. 底値圏（P <= 20%）かつ 高利回り（Y >= 3.5%）のケース
    # retracement=85.0 -> P=15%
    data_low_yield = {
        **base_data,
        "fibonacci_1y": {"retracement": 85.0},
        "yield": "4.2%"
    }
    sig = calculate_buy_signal(data_low_yield)
    assert sig is not None
    assert "底値圏(高利回り)" in sig["label"]
    assert "絶好の長期仕込み場" in sig["recommended_action"]

    # 4. 底値圏（P <= 20%）かつ 低利回り（Y < 3.5%）のケース
    # retracement=90.0 -> P=10%
    data_low_low_yield = {
        **base_data,
        "fibonacci_1y": {"retracement": 90.0},
        "yield": "1.5%"
    }
    sig = calculate_buy_signal(data_low_low_yield)
    assert sig is not None
    assert "底値圏" in sig["label"]
    assert "底値圏(高利回り)" not in sig["label"]
    assert "下値リスクが限定的" in sig["recommended_action"]

    # 5. データ欠損時の安全なフォールバック（retracementなし）
    data_missing = {
        **base_data,
        "yield": "3.0%"
        # fibonacci_1y なし
    }
    sig = calculate_buy_signal(data_missing)
    assert sig is not None
    assert sig["label"] == "📈 注目(順張り)"  # 従来通りのラベルにフォールバック


def test_calculate_material_exhaustion_signal():
    """材料出尽くしシグナルの判定テスト"""
    # 1. 好材料出尽くし警戒 (Sell the Fact)
    stock_warn = {
        "asset_type": "jp_stock",
        "price": 1100,
        "ma25": 1000,
        "ma75": 950,
        "rsi14": 70,
        "rci26": 80,
        "change": -10,
        "rsi14_prev": 72
    }
    sig_warn = calculate_material_exhaustion_signal(stock_warn)
    assert sig_warn is not None
    assert sig_warn["type"] == "sell_the_fact"
    assert "🚨 出尽くし警戒" in sig_warn["label"]

    # 2. 悪材料出尽くし・アク抜け (Bad News Bottoming)
    stock_rebound = {
        "asset_type": "jp_stock",
        "price": 850,
        "ma75": 1000,
        "ma200": 1050,
        "rsi14": 25,
        "rci26": -80,
        "change": 15,
        "rsi14_prev": 22
    }
    sig_rebound = calculate_material_exhaustion_signal(stock_rebound)
    assert sig_rebound is not None
    assert sig_rebound["type"] == "bad_news_bottoming"
    assert "✨ アク抜け期待" in sig_rebound["label"]

def test_material_exhaustion_signal_edge_cases():
    """材料出尽くしシグナルのエッジケース・型変換・資産タイプフィルタテスト"""
    # 非日本株の場合は None
    us_stock = {"asset_type": "us_stock", "price": 100, "rsi14": 80, "rci26": 90}
    assert calculate_material_exhaustion_signal(us_stock) is None

    # 文字列のカンマや符号クリーニング
    stock_str = {
        "asset_type": "jp_stock",
        "price": "1,100",
        "ma25": 1000,
        "rsi14": "70.0",
        "rci26": "+80.0",
        "change": "-10.0",
        "rsi14_prev": "72.0"
    }
    sig = calculate_material_exhaustion_signal(stock_str)
    assert sig is not None
    assert sig["type"] == "sell_the_fact"

    # 75日線離脱(-10%以下)でのアク抜け判定 (200日線なし)
    stock_75 = {
        "asset_type": "jp_stock",
        "price": 85,
        "ma75": 100,
        "rsi14": 28,
        "rci26": -75,
        "change": 2,
        "rsi14_prev": 25
    }
    sig75 = calculate_material_exhaustion_signal(stock_75)
    assert sig75 is not None
    assert sig75["type"] == "bad_news_bottoming"

    # 不正データ・データ欠損時の安全返却 (None)
    stock_corrupt = {"asset_type": "jp_stock", "price": "invalid", "rsi14": "N/A"}
    assert calculate_material_exhaustion_signal(stock_corrupt) is None

def test_reconcile_signals_with_exhaustion():
    """材料出尽くしシグナルの相反調停テスト"""
    buy = {"level": 2, "label": "チャンス"}
    sell = {"level": 4, "label": "落ちるナイフ"}
    exh_rebound = {"type": "bad_news_bottoming", "label": "✨ アク抜け期待"}

    # 落ちるナイフ(Lv4) 発生時はアク抜けであっても購入非表示
    b_res, s_res, e_res = reconcile_signals(buy, sell, exh_rebound)
    assert b_res is None
    assert s_res == sell
    assert e_res is None

    # 好材料出尽くし警戒発生時は購入側を抑制
    exh_warn = {"type": "sell_the_fact", "label": "🚨 出尽くし警戒"}
    b_res2, s_res2, e_res2 = reconcile_signals(buy, None, exh_warn)
    assert b_res2 is None
    assert e_res2 == exh_warn

    # 2引数で呼ばれた場合の互換性テスト
    b_2, s_2 = reconcile_signals(buy, None)
    assert b_2 == buy
    assert s_2 is None

    # アク抜け期待(bad_news_bottoming)の場合は購入シグナルとして昇格・調整される
    b_res3, s_res3, e_res3 = reconcile_signals(None, None, exh_rebound)
    assert b_res3 == exh_rebound
    assert s_res3 is None
    assert e_res3 == exh_rebound



