import pytest
import re
import json
from scraper import JPStockScraper, USStockScraper
from app import _enrich_stock_data

def test_jp_stock_payout_and_bps_scraping():
    scraper = JPStockScraper()
    
    # 1. Test BPS parsing
    # Simulated __NEXT_DATA__ JSON containing bps
    mock_json_q = '{"bps":{"name":"BPS","subText":"（実績）","value":"3,062.82","prefix":"(連)"}}'
    mock_html = '<title>テスト銘柄</title>'
    
    # Injecting private helper method testing
    data = scraper._scavenge_common_data(mock_html, mock_json_q)
    data['bps'] = "N/A"
    
    bps_m = re.search(r'\"bps\":\{[^{}]*?\"value\":\"([\d\.\-\,]+)\"', mock_json_q)
    if bps_m:
        data['bps'] = bps_m.group(1).replace(',', '')
        
    assert data['bps'] == "3062.82"

def test_jp_stock_payout_ratio_history_scraping():
    scraper = JPStockScraper()
    
    # Simulated __NEXT_DATA__ JSON from dividend detail page
    mock_json_div = '{"payoutRatioAndEps":[{"settlementDate":"202603","settlementDateFormatted":"2026年3月期","payoutRatioValue":32.1,"payoutRatioFormattedWithUnit":"32.1%","correctedEpsValue":295.25}]}'
    
    data = {}
    payout_ratio_history = []
    payout_ratio_m = re.search(r'\"payoutRatioAndEps\":(\[.*?\])', mock_json_div)
    if payout_ratio_m:
        payout_data = json.loads(payout_ratio_m.group(1))
        if payout_data and len(payout_data) > 0:
            val = payout_data[0].get('payoutRatioValue')
            if val is not None:
                data['payout_ratio'] = str(val)
        payout_ratio_history = payout_data
    data['payout_ratio_history'] = payout_ratio_history
    
    assert data['payout_ratio'] == "32.1"
    assert len(data['payout_ratio_history']) == 1
    assert data['payout_ratio_history'][0]['settlementDateFormatted'] == "2026年3月期"

def test_doe_calculation_in_enrich():
    # Test for JP Stock DOE calculation: annual_dividend / BPS * 100
    merged_data = {
        "code": "7203",
        "asset_type": "jp_stock",
        "annual_dividend": 90.0,
        "bps": "3000.00"
    }
    
    enriched = _enrich_stock_data(merged_data)
    assert enriched["doe"] == 3.0  # 90 / 3000 * 100 = 3%

def test_us_stock_payout_ratio_calculation_in_enrich():
    # Test for US Stock payout ratio calculation: yield * PER
    merged_data = {
        "code": "AAPL",
        "asset_type": "us_stock",
        "yield": "1.20%",
        "per": "25.0"
    }
    
    enriched = _enrich_stock_data(merged_data)
    assert enriched["payout_ratio"] == 30.0  # 1.2% * 25 = 30%

def test_payout_ratio_scoring_in_calculate_score():
    from app import calculate_score
    
    # 1. 適正レンジ (20.0% 〜 60.0%) の場合、+1 点が加算される
    stock_in_range = {
        "per": "15.0",
        "pbr": "1.0",
        "roe": "10.0",
        "yield": "3.0",
        "consecutive_increase_years": 0,
        "payout_ratio": "35.0"  # 範囲内
    }
    score, details = calculate_score(stock_in_range)
    # PER(1), PBR(1), ROE(1), 利回り(1), consecutive_increase(0) + payout_ratio(1) = 5
    assert details["payout_ratio"] == 1
    assert score == 5

    # 2. 範囲外 (60.0% 超) の場合、加算されない (0点)
    stock_over_range = {
        "per": "15.0",
        "pbr": "1.0",
        "roe": "10.0",
        "yield": "3.0",
        "consecutive_increase_years": 0,
        "payout_ratio": "65.0"  # 範囲外
    }
    score, details = calculate_score(stock_over_range)
    assert details["payout_ratio"] == 0
    assert score == 4

    # 3. 範囲外 (20.0% 未満) の場合、加算されない (0点)
    stock_under_range = {
        "per": "15.0",
        "pbr": "1.0",
        "roe": "10.0",
        "yield": "3.0",
        "consecutive_increase_years": 0,
        "payout_ratio": "15.0"  # 範囲外
    }
    score, details = calculate_score(stock_under_range)
    assert details["payout_ratio"] == 0
    assert score == 4

    # 4. データ欠損 (N/A) の場合、加算されない (0点) が、is_reliable には影響しない
    stock_na = {
        "per": "15.0",
        "pbr": "1.0",
        "roe": "10.0",
        "yield": "3.0",
        "consecutive_increase_years": 0,
        "payout_ratio": "N/A"
    }
    score, details = calculate_score(stock_na)
    assert details["payout_ratio"] == 0
    assert "配当性向" in details["missing_items"]
    assert details["is_reliable"] == True  # 配当性向は is_reliable に影響しない
    assert score == 4

