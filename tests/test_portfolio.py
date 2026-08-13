import pytest
from portfolio_manager import calculate_holding_values

def test_calculate_holding_values_jp_stock_taxable():
    """国内株式（課税口座）の計算テスト"""
    asset_data = {
        "price": "1000",
        "annual_dividend": "40",
        "currency": "JPY",
        "asset_type": "jp_stock"
    }
    holding = {
        "purchase_price": 800,
        "quantity": 100,
        "account_type": "特定口座"
    }
    exchange_rates = {"JPY": 1.0}
    tax_config = {
        "non_taxable_accounts": ["新NISA", "旧NISA"],
        "tax_info": {
            "jp_stock": {"tax_rate": 0.20315}
        }
    }
    
    result = calculate_holding_values(asset_data, holding, exchange_rates, tax_config)
    
    assert result["market_value"] == 100000
    assert result["profit_loss"] == 20000
    assert result["profit_loss_rate"] == 25.0
    assert result["estimated_annual_dividend"] == 4000
    # 4000 * (1 - 0.20315) = 4000 * 0.79685 = 3187.4
    assert pytest.approx(result["estimated_annual_dividend_after_tax"], 0.1) == 3187.4

def test_calculate_holding_values_us_stock_nontaxable():
    """米国株式（非課税口座）の計算テスト"""
    asset_data = {
        "price": "150",
        "annual_dividend": "3.5",
        "currency": "USD",
        "asset_type": "us_stock"
    }
    holding = {
        "purchase_price": 100,
        "quantity": 10,
        "account_type": "新NISA"
    }
    exchange_rates = {"USD": 150.0}
    tax_config = {
        "non_taxable_accounts": ["新NISA", "旧NISA"],
        "tax_info": {
            "us_stock": {"tax_rate": 0.20315} # 課税口座用
        }
    }
    
    result = calculate_holding_values(asset_data, holding, exchange_rates, tax_config)
    
    # 150 USD * 150 JPY/USD * 10 = 225000 JPY
    assert result["market_value"] == 225000
    # 投資額: 100 USD * 150 JPY/USD * 10 = 150000 JPY
    # 損益: 225000 - 150000 = 75000 JPY
    assert result["profit_loss"] == 75000
    assert result["estimated_annual_dividend"] == 3.5 * 10 * 150 # 5250
    # 非課税口座なので税引き後も同じ
    assert result["estimated_annual_dividend_after_tax"] == 5250

def test_calculate_holding_values_missing_price():
    """価格データ欠損時のテスト"""
    asset_data = {
        "price": "N/A",
        "annual_dividend": "40",
        "currency": "JPY"
    }
    holding = {"purchase_price": 800, "quantity": 100}
    result = calculate_holding_values(asset_data, holding, {}, {})
    assert result["market_value"] is None
    assert result["estimated_annual_dividend"] == 4000


def test_calculate_daily_change_rankings_normal():
    """案件 #261: 当日資産増減ランキング(TOP10)の計算・合算・ソートのテスト"""
    from portfolio_manager import calculate_daily_change_rankings

    raw_holdings = [
        # 銘柄A (国内株 7203): 口座1 100株 + 口座2 200株 (前日比 +50円 ➔ 50 * 300 = +15,000円)
        {"code": "7203", "name": "トヨタ", "asset_type": "jp_stock", "currency": "JPY", "quantity": 100, "change": 50.0, "change_percent": 2.0, "market_value": 250000},
        {"code": "7203", "name": "トヨタ", "asset_type": "jp_stock", "currency": "JPY", "quantity": 200, "change": 50.0, "change_percent": 2.0, "market_value": 500000},
        # 銘柄B (米国株 AAPL): 10株 (前日比 +10ドル, 為替 150円/$ ➔ 10 * 10 * 150 = +15,000円と同額だが合算動作確認)
        {"code": "AAPL", "name": "Apple", "asset_type": "us_stock", "currency": "USD", "quantity": 10, "change": 10.0, "change_percent": 4.0, "market_value": 300000},
        # 銘柄C (国内株 9432): 1000株 (前日比 -5円 ➔ -5 * 1000 = -5,000円)
        {"code": "9432", "name": "NTT", "asset_type": "jp_stock", "currency": "JPY", "quantity": 1000, "change": -5.0, "change_percent": -3.0, "market_value": 150000},
        # 銘柄D (投資信託): 100,000口 (基準価額前日比 +100円/10,000口 ➔ (100/10000) * 100000 = +1,000円)
        {"code": "IT_TEST", "name": "オルカン", "asset_type": "investment_trust", "currency": "JPY", "quantity": 100000, "change": 100.0, "change_percent": 0.5, "market_value": 200000},
    ]

    exchange_rates = {"JPY": 1.0, "USD": 150.0}

    res = calculate_daily_change_rankings(raw_holdings, exchange_rates)

    gainers = res["day_gainers_top10"]
    losers = res["day_losers_top10"]

    assert len(gainers) == 3
    assert len(losers) == 1

    # トヨタ(7203) と AAPL はともに +15,000円で上位
    gainer_codes = [g["code"] for g in gainers]
    assert "7203" in gainer_codes
    assert "AAPL" in gainer_codes
    assert "IT_TEST" in gainer_codes

    # NTT(9432) は -5,000円で減少トップ
    assert losers[0]["code"] == "9432"
    assert losers[0]["daily_change_jpy"] == -5000.0
    assert losers[0]["rank"] == 1


def test_calculate_daily_change_rankings_edge_cases():
    """案件 #261: N/A・データ欠損・前日比0の除外セーフガードテスト"""
    from portfolio_manager import calculate_daily_change_rankings

    raw_holdings = [
        {"code": "NO_CHANGE", "quantity": 100, "change": 0.0},
        {"code": "NA_CHANGE", "quantity": 100, "change": "N/A"},
        {"code": "NONE_CHANGE", "quantity": 100, "change": None},
    ]

    res = calculate_daily_change_rankings(raw_holdings, {"JPY": 1.0})
    assert len(res["day_gainers_top10"]) == 0
    assert len(res["day_losers_top10"]) == 0


def test_calculate_daily_change_rankings_string_formats_and_top10_limit():
    """案件 #261: 文字列フォーマットの前日比・10件超のTOP10制限テスト"""
    from portfolio_manager import calculate_daily_change_rankings

    raw_holdings = []
    # 15銘柄の増加データを作成 (前日比 +1円 〜 +15円, 100株)
    for i in range(1, 16):
        raw_holdings.append({
            "code": f"STOCK_{i:02d}",
            "name": f"銘柄{i}",
            "asset_type": "jp_stock",
            "currency": "JPY",
            "quantity": 100,
            "change": f"+{i}.0",
            "change_percent": f"+{i * 0.1}%",
            "market_value": 10000 * i
        })
    # 12銘柄の減少データを作成 (前日比 -1円 〜 -12円, 100株)
    for i in range(1, 13):
        raw_holdings.append({
            "code": f"LOSS_{i:02d}",
            "name": f"損失銘柄{i}",
            "asset_type": "jp_stock",
            "currency": "JPY",
            "quantity": 100,
            "change": f"-{i}.0",
            "change_percent": f"-{i * 0.1}%",
            "market_value": 10000 * i
        })

    res = calculate_daily_change_rankings(raw_holdings, {"JPY": 1.0})

    gainers = res["day_gainers_top10"]
    losers = res["day_losers_top10"]

    # 10件に制限されていること
    assert len(gainers) == 10
    assert len(losers) == 10

    # 増加1位はSTOCK_15 (15 * 100 = 1500円増)
    assert gainers[0]["code"] == "STOCK_15"
    assert gainers[0]["daily_change_jpy"] == 1500.0
    assert gainers[0]["rank"] == 1

    # 減少1位はLOSS_12 (-12 * 100 = -1200円)
    assert losers[0]["code"] == "LOSS_12"
    assert losers[0]["daily_change_jpy"] == -1200.0
    assert losers[0]["rank"] == 1

