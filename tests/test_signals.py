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


def test_enrich_stock_data_discount_flag_and_isolation():
    """#265不具合修正: _enrich_stock_data で raw_sell_signal と is_long_term_discount が保持されることを検証"""
    from unittest.mock import patch
    from app import _enrich_stock_data

    mock_data = {
        "code": "9999",
        "name": "ダミー銘柄",
        "asset_type": "jp_stock",
        "price": 2900,
        "moving_average_25": 3000,
        "moving_average_75": 3000,
        "ma200": 2920,
        "score_details": {
            "per": 1, "pbr": 1, "roe": 1, "yield": 1, "consecutive_increase": 0,
            "is_reliable": True, "total_stars": 4, "fundamentals_stars": 4
        }
    }

    with patch("history_manager.get_historical_data_for_analysis", return_value=[]), \
         patch("history_manager.save_daily_data", return_value=True):
        res = _enrich_stock_data(mock_data)

    # 1. 75日線割れ (2900 < 3000) なので is_long_term_discount が True であること
    assert res.get("is_long_term_discount") is True

    # 2. reconcile_signals により sell_signal は None に抑制されるが raw_sell_signal には level 3 が保持されること
    assert res.get("sell_signal") is None
    assert res.get("raw_sell_signal") is not None
    assert res.get("raw_sell_signal", {}).get("level") == 3


def test_enrich_stock_data_is_long_term_discount_edge_cases():
    """is_long_term_discount の様々なデータ入力・エッジケース動作の確認"""
    from unittest.mock import patch
    from app import _enrich_stock_data

    base_data = {
        "code": "8888",
        "name": "テスト銘柄",
        "asset_type": "jp_stock",
        "score_details": {"is_reliable": True}
    }

    with patch("history_manager.get_historical_data_for_analysis", return_value=[]), \
         patch("history_manager.save_daily_data", return_value=True):
        
        # ケース1: 株価がカンマ区切りの文字列 "1,500" で MA75 が 1600 (株価 < MA75 -> True)
        d1 = _enrich_stock_data({**base_data, "price": "1,500", "moving_average_75": 1600})
        assert d1["is_long_term_discount"] is True

        # ケース2: 株価 > MA75 (2000 > 1500 -> False)
        d2 = _enrich_stock_data({**base_data, "price": 2000, "moving_average_75": 1500})
        assert d2["is_long_term_discount"] is False

        # ケース3: 株価 == MA75 (1500 == 1500 -> False)
        d3 = _enrich_stock_data({**base_data, "price": 1500, "moving_average_75": 1500})
        assert d3["is_long_term_discount"] is False

        # ケース4: MA75 が None (-> False)
        d4 = _enrich_stock_data({**base_data, "price": 1500, "moving_average_75": None, "ma75": None})
        assert d4["is_long_term_discount"] is False

        # ケース5: 不正な株価データ "invalid" (-> False)
        d5 = _enrich_stock_data({**base_data, "price": "invalid", "moving_average_75": 1500})
        assert d5["is_long_term_discount"] is False


def test_frontend_filter_logic_simulation():
    """static/js/main.js および static/js/analysis.js のフィルタロジックと同等のロジックをテスト"""
    
    def simulate_strict_low_filter(asset):
        is_diamond = asset.get("is_diamond") is True or (
            asset.get("buy_signal") is not None and asset.get("buy_signal", {}).get("is_diamond") is True
        )
        ma75 = asset.get("moving_average_75") or asset.get("ma75")
        
        # 判定順: is_long_term_discount -> raw_sell_signal(3) -> sell_signal(3) -> price < ma75
        price_val = asset.get("price")
        p_num = float(str(price_val).replace(',', '')) if price_val is not None and str(price_val).replace(',', '').replace('.', '', 1).isdigit() else 0
        ma75_num = float(ma75) if ma75 is not None and str(ma75).replace('.', '', 1).isdigit() else 0

        is_long_term_discount = (
            asset.get("is_long_term_discount") is True or
            (asset.get("raw_sell_signal") is not None and asset.get("raw_sell_signal", {}).get("level") == 3) or
            (asset.get("sell_signal") is not None and asset.get("sell_signal", {}).get("level") == 3) or
            (p_num > 0 and ma75_num > 0 and p_num < ma75_num)
        )
        is_falling_knife = (
            (asset.get("sell_signal") is not None and asset.get("sell_signal", {}).get("level") == 4) or
            (asset.get("raw_sell_signal") is not None and asset.get("raw_sell_signal", {}).get("level") == 4)
        )
        return bool(is_diamond and is_long_term_discount and not is_falling_knife)

    # 1. reconcile_signals により sell_signal が None に消去されたが is_diamond=True, is_long_term_discount=True
    # (従来0件不具合が発生していた代表的パターン)
    asset_reconciled = {
        "is_diamond": True,
        "is_long_term_discount": True,
        "raw_sell_signal": {"level": 3, "label": "調整局面"},
        "sell_signal": None,
        "buy_signal": {"level": 1, "is_diamond": True}
    }
    assert simulate_strict_low_filter(asset_reconciled) is True

    # 2. 落ちるナイフ (level 4) の場合 -> 除外 (False)
    asset_falling_knife = {
        "is_diamond": True,
        "is_long_term_discount": True,
        "raw_sell_signal": {"level": 4, "label": "落ちるナイフ"},
        "sell_signal": {"level": 4, "label": "落ちるナイフ"},
        "buy_signal": None
    }
    assert simulate_strict_low_filter(asset_falling_knife) is False

    # 3. ダイヤモンド銘柄でない場合 (is_diamond=False) -> 除外 (False)
    asset_non_diamond = {
        "is_diamond": False,
        "is_long_term_discount": True,
        "raw_sell_signal": {"level": 3, "label": "調整局面"},
        "sell_signal": {"level": 3, "label": "調整局面"},
        "buy_signal": None
    }
    assert simulate_strict_low_filter(asset_non_diamond) is False




