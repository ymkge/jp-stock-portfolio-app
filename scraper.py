import requests
import json
import re
from typing import Optional
from datetime import datetime
from bs4 import BeautifulSoup

def fetch_dividend_history(stock_code: str, num_years: int = 4) -> dict:
    """
    Yahoo!ファイナンスの配当ページから過去数年分の1株あたり配当を取得する。
    """
    dividend_url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T/dividend"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(dividend_url, headers=headers, timeout=10)
        response.raise_for_status()
        # パーサーを 'html.parser' に変更
        soup = BeautifulSoup(response.text, "html.parser")
        
        yearly_dividends = {}
        
        table = soup.find("table", class_=re.compile(r"DpsHistoryTable__table"))
        if not table or not table.tbody:
            return {}

        rows = table.tbody.find_all("tr")
        current_year_text = None
        for row in rows:
            # 年度セルを探す
            year_cell = row.find("th", class_=re.compile(r"DpsHistoryTable__dateCol01__"))
            if year_cell and "年" in year_cell.get_text():
                current_year_text = year_cell.get_text(strip=True)

            # 「実績」行かどうかを判断し、かつ年度が特定できている場合
            if "実績" in row.get_text() and current_year_text:
                match = re.search(r'(\d{4})年', current_year_text)
                if match:
                    year = int(match.group(1))
                    # 実績行の最初のtdが年間配当(調整後)
                    dividend_cell = row.find("td")
                    if dividend_cell:
                        dividend_text = dividend_cell.get_text(strip=True)
                        try:
                            dividend = float(dividend_text)
                            yearly_dividends[str(year)] = dividend
                        except (ValueError, TypeError):
                            # "---" などの場合は 0.0 とする
                            yearly_dividends[str(year)] = 0.0
        
        # 結果を整形する
        result = {}
        latest_fiscal_year = 0
        if yearly_dividends:
            latest_fiscal_year = max(int(y) for y in yearly_dividends.keys())
        
        if latest_fiscal_year > 0:
             for i in range(num_years):
                year_to_check = latest_fiscal_year - i
                result[str(year_to_check)] = yearly_dividends.get(str(year_to_check), 0.0)
        
        # キーを降順にソートして返す
        return {k: v for k, v in sorted(result.items(), key=lambda item: item[0], reverse=True)}

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

        # READMEの課題にある通り配当履歴は現在取得できないため、一旦空のデータを返す
        dividend_history = {}

        # 配当利回りをpriceBoardから優先的に取得し、なければreferenceIndexから取得
        dividend_yield = price_board.get("shareDividendYield")
        if dividend_yield is None:
            dividend_yield = reference_index.get("shareDividendYield", "N/A")

        return {
            "code": stock_code,
            "name": price_board.get("name", "N/A"),
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