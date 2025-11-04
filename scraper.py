import requests
import json
import re
from typing import Optional
from datetime import datetime
from bs4 import BeautifulSoup

def fetch_dividend_history(stock_code: str, num_years: int = 4) -> dict:
    """
    Yahoo!ファイナンスの配当ページから過去数年分の1株あたり配当を取得する。
    ページの__PRELOADED_STATE__からJSONデータを抽出する。
    """
    dividend_url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T/dividend"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(dividend_url, headers=headers, timeout=10)
        response.raise_for_status()

        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if not match:
            print(f"Could not find __PRELOADED_STATE__ for {stock_code} on dividend page.")
            return {}

        preloaded_state = json.loads(match.group(1))
        
        dividend_data = preloaded_state.get("mainStocksDividend", {}).get("dps", [])
        if not dividend_data:
            return {}

        yearly_dividends = {}
        for item in dividend_data:
            if item.get("valueType") == "actual" and "annualCorrectedActualValue" in item:
                year_match = re.search(r"(\d{4})", item.get("settlementDate", ""))
                if year_match:
                    year = year_match.group(1)
                    yearly_dividends[year] = item["annualCorrectedActualValue"]

        # num_years に基づいて結果をフィルタリングし、降順にソート
        sorted_years = sorted(yearly_dividends.keys(), reverse=True)
        
        result = {}
        for year in sorted_years[:num_years]:
            result[year] = yearly_dividends[year]
        
        return result

    except Exception as e:
        print(f"An unexpected error occurred in fetch_dividend_history for {stock_code}: {e}")
        return {}

def fetch_stock_data(stock_code: str, num_years_dividend: int = 4) -> Optional[dict]:
    """
    Yahoo!ファイナンスのページから株価情報と配当履歴を取得する。
    """
    url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if not match:
            print(f"Could not find __PRELOADED_STATE__ for {stock_code}")
            return None

        preloaded_state = json.loads(match.group(1))

        

        price_board = preloaded_state.get("mainStocksPriceBoard", {}).get("priceBoard", {})
        reference_index = preloaded_state.get("mainStocksDetail", {}).get("referenceIndex", {})

        market_cap_str = reference_index.get("totalPrice", "N/A")
        market_cap = "N/A"
        if market_cap_str != "N/A":
            market_cap_value_str = re.sub(r'[^\d]', '', market_cap_str)
            if market_cap_value_str:
                try:
                    market_cap_value = int(market_cap_value_str)
                    market_cap = f"{market_cap_value * 1_000_000:,}"
                except (ValueError, TypeError):
                    market_cap = "N/A"

        # 配当履歴を取得
        dividend_history = fetch_dividend_history(stock_code, num_years_dividend)

        # 配当利回りをpriceBoardから優先的に取得し、なければreferenceIndexから取得
        dividend_yield = price_board.get("shareDividendYield")
        if dividend_yield is None:
            dividend_yield = reference_index.get("shareDividendYield", "N/A")

        return {
            "code": stock_code,
            "name": price_board.get("name", "N/A"),
            "industry": price_board.get("industry", {}).get("industryName", "N/A"),
            "price": price_board.get("price", "N/A"),
            "change": price_board.get("priceChange", "N/A"),
            "change_percent": price_board.get("priceChangeRate", "N/A"),
            "market_cap": market_cap,
            "per": reference_index.get("per", "N/A"),
            "pbr": reference_index.get("pbr", "N/A"),
            "roe": reference_index.get("roe", "N/A"),
            "eps": reference_index.get("eps", "N/A"),
            "yield": dividend_yield,
            "dividend_history": dividend_history,
        }

    except Exception as e:
        print(f"An unexpected error occurred for {stock_code}: {e}")
        return None

if __name__ == '__main__':
    data = fetch_stock_data("8306", num_years_dividend=5)
    if data:
        print(json.dumps(data, indent=2, ensure_ascii=False))