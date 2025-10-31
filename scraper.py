import requests
import json
import re
from typing import Optional
from datetime import datetime

def fetch_dividend_history(stock_code: str, num_years: int = 4) -> dict:
    """
    Yahoo!ファイナンスの時系列ページから過去数年分の1株あたり配当を取得する。
    """
    history_url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T/history"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(history_url, headers=headers, timeout=10)
        response.raise_for_status()

        # 日付、"配当"、配当額を柔軟に抽出する正規表現
        pattern = re.compile(r'(\d{4}年\d{1,2}月\d{1,2}日).*?配当.*?([\d,.]+)', re.DOTALL)
        matches = pattern.findall(response.text)

        yearly_dividends = {}
        for date_str, dividend_str in matches:
            try:
                date_obj = datetime.strptime(date_str, '%Y年%m月%d日')
                year = date_obj.year
                # 配当額の後に株価などがマッチしてしまうのを防ぐため、数値の妥当性をある程度チェック
                dividend = float(dividend_str.replace(',', ''))
                if dividend > 10000: # 1株あたりの配当が1万円を超えることは稀なので、誤マッチと判断
                    continue

                if year not in yearly_dividends:
                    yearly_dividends[year] = 0.0
                yearly_dividends[year] += dividend
            except (ValueError, TypeError):
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
    Yahoo!ファイナンスのページに埋め込まれたJSONデータから株価情報を取得する。
    配当履歴も追加で取得する。
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
        if market_cap_str != "N/A" and "百万円" in market_cap_str:
            market_cap_value_str = re.sub(r'[^\d]', '', market_cap_str)
            if market_cap_value_str:
                market_cap_value = int(market_cap_value_str)
                market_cap = f"{market_cap_value * 1_000_000:,}"

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

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {stock_code}: {e}")
        return None
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"An error occurred while parsing JSON for {stock_code}: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {stock_code}: {e}")
        return None

if __name__ == '__main__':
    data = fetch_stock_data("8306", num_years_dividend=5)
    if data:
        print(json.dumps(data, indent=2, ensure_ascii=False))
