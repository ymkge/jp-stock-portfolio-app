import requests
import json
import re
from typing import Optional

def fetch_stock_data(stock_code: str) -> Optional[dict]:
    """
    Yahoo!ファイナンスのページに埋め込まれたJSONデータから株価情報を取得する。
    CSSセレクタに依存しないため、より安定している。
    """
    url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # HTMLから window.__PRELOADED_STATE__ の内容を正規表現で抽出
        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if not match:
            print(f"Could not find __PRELOADED_STATE__ for {stock_code}")
            return None

        # JSON文字列をPythonの辞書に変換
        preloaded_state = json.loads(match.group(1))

        price_board = preloaded_state.get("mainStocksPriceBoard", {}).get("priceBoard", {})
        reference_index = preloaded_state.get("mainStocksDetail", {}).get("referenceIndex", {})

        # 時価総額の単位を「百万円」から「円」に変換し、数値として扱いやすくする
        market_cap_str = reference_index.get("totalPrice", "N/A")
        market_cap = "N/A"
        if market_cap_str != "N/A":
            # "50,307,035百万円" のような文字列を想定
            market_cap_value = int(market_cap_str.replace(",", "").replace("百万円", ""))
            market_cap = f"{market_cap_value * 1_000_000:,}" # 3桁区切りに戻す

        return {
            "code": stock_code,
            "name": price_board.get("name", "N/A"),
            "price": price_board.get("price", "N/A"),
            "market_cap": market_cap,
            "per": reference_index.get("per", "N/A"),
            "pbr": reference_index.get("pbr", "N/A"),
            "dividend_yield": reference_index.get("shareDividendYield", "N/A"),
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
    # テスト用
    data = fetch_stock_data("7203") # トヨタ自動車
    if data:
        print(data)
    data = fetch_stock_data("9432") # NTT
    if data:
        print(data)