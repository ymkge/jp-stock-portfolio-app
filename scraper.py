import requests
import json
import re
from typing import Optional
from datetime import datetime
from bs4 import BeautifulSoup

def fetch_dividend_history(stock_code: str, num_years: int = 4) -> dict:
    """
    Yahoo!ファイナンスの時系列ページから過去数年分の1株あたり配当を取得する。
    スマートフォン用のUser-Agentを使用してアクセスする。
    """
    history_url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T/history"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.1.1 Mobile/15E148 Safari/604.1"
    }
    try:
        response = requests.get(history_url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        # スマートフォン版ページの構造を仮定してセレクタを変更
        # 日付と配当額がリストアイテム(`li`)の中に含まれていると仮定
        items = soup.select("li[class*='_HistoryItem_']")

        yearly_dividends = {}
        for item in items:
            if "配当" in item.get_text():
                try:
                    date_str = item.select_one("[class*='_Date_']").get_text(strip=True)
                    dividend_str = item.select_one("[class*='_Price_']").get_text(strip=True)

                    date_obj = datetime.strptime(date_str, '%Y/%m/%d')
                    year = date_obj.year
                    dividend = float(dividend_str.replace('円', '').replace(',', ''))

                    if year not in yearly_dividends:
                        yearly_dividends[year] = 0.0
                    yearly_dividends[year] += dividend
                except (AttributeError, ValueError, TypeError):
                    continue

        current_year = datetime.now().year
        result = {}
        for i in range(num_years):
            year = current_year - i
            result[str(year)] = round(yearly_dividends.get(year, 0.0), 2)

        return result

    except requests.exceptions.RequestException as e:
        print(f"Error fetching dividend history for {stock_code}: {e}")
        return {}
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

        dividend_history = fetch_dividend_history(stock_code, num_years=num_years_dividend)

        return {
            "code": stock_code,
            "name": price_board.get("name", "N/A"),
            "price": price_board.get("price", "N/A"),
            "market_cap": market_cap,
            "per": reference_index.get("per", "N/A"),
            "pbr": reference_index.get("pbr", "N/A"),
            "dividend_yield": reference_index.get("shareDividendYield", "N/A"),
            "dividend_history": dividend_history,
        }

    except Exception as e:
        print(f"An unexpected error occurred for {stock_code}: {e}")
        return None

if __name__ == '__main__':
    data = fetch_stock_data("8306", num_years_dividend=5)
    if data:
        print(json.dumps(data, indent=2, ensure_ascii=False))
