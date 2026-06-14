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
