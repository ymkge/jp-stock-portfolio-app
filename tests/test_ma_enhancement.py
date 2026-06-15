import pytest
from app import calculate_score, calculate_buy_signal, calculate_sell_signal

def test_golden_cross_detection():
    """ゴールデンクロスの検知とスコアリングのテスト"""
    # 中期GCが発生するデータを作成
    stock_data = {
        "asset_type": "jp_stock",
        "price": 1000,
        "moving_average_25": 1010,
        "moving_average_25_prev": 990,
        "moving_average_75": 1005,
        "moving_average_75_prev": 1005,
        "score_details": {"is_reliable": True} # ダミー
    }
    # 25日線: 990 -> 1010 (上昇)
    # 75日線: 1005 -> 1005 (横ばい)
    # 前日: 25(990) <= 75(1005) -> True
    # 当日: 25(1010) > 75(1005) -> True -> GC!

    score, details = calculate_score(stock_data)
    assert details["gc_25_75"] == 1
    
    # 長期GC
    stock_data_long = {
        "asset_type": "jp_stock",
        "price": 1000,
        "moving_average_75": 1010,
        "moving_average_75_prev": 990,
        "moving_average_200": 1005,
        "moving_average_200_prev": 1005,
        "score_details": {"is_reliable": True}
    }
    score, details = calculate_score(stock_data_long)
    assert details["gc_75_200"] == 1

def test_buy_signal_with_gc_and_ma25_breakout():
    """GCと25日線突破による購入シグナル昇格のテスト"""
    # 25日線突破のテスト
    stock_data = {
        "asset_type": "jp_stock",
        "score_details": {
            "per": 1, "pbr": 1, "roe": 1, "yield": 1, "consecutive_increase": 0,
            "is_reliable": True
        },
        "rsi_14": 25.0, # Lv1条件を満たす (売られすぎ)
        "moving_average_25": 1000,
        "price": 1010 # 25日線突破
    }
    
    signal = calculate_buy_signal(stock_data)
    assert signal is not None
    assert signal["level"] == 2
    assert "25日線突破" in "".join(signal["reasons"])

    # 中期GCによるLv2昇格
    stock_data_gc = {
        "asset_type": "jp_stock",
        "score_details": {
            "per": 1, "pbr": 1, "roe": 1, "yield": 1, "consecutive_increase": 0,
            "is_reliable": True
        },
        "rsi_14": 25.0,
        "moving_average_25": 1010,
        "moving_average_25_prev": 990,
        "moving_average_75": 1005,
        "moving_average_75_prev": 1005,
        "price": 1000
    }
    signal = calculate_buy_signal(stock_data_gc)
    assert signal is not None
    assert signal["level"] == 2
    assert "中期GC" in "".join(signal["reasons"])

def test_sell_signal_with_dc_and_ma25_breakdown():
    """DCと25日線割れによる売却シグナルのテスト"""
    stock_data = {
        "asset_type": "jp_stock",
        "rsi_14": 80.0, # Lv1条件を満たす (買われすぎ)
        "moving_average_25": 1000,
        "price": 990, # 25日線割れ
        "moving_average_25_prev": 1010,
        "moving_average_75": 1005,
        "moving_average_75_prev": 1005
    }
    
    signal = calculate_sell_signal(stock_data)
    assert signal is not None
    assert signal["level"] == 2
    assert "25日線割れ" in "".join(signal["reasons"])
    assert "中期DC" in "".join(signal["reasons"])
