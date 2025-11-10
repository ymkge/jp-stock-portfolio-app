import requests
import json
import re
import time
from typing import Optional
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2 # seconds

def _make_request(url: str, headers: dict) -> Optional[requests.Response]:
    """指定されたURLに対してリトライ機能付きでリクエストを送信する"""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status() # 4xx or 5xx status will raise an HTTPError
            return response
        except RequestException as e:
            logger.warning(f"リクエスト失敗 (試行 {attempt + 1}/{MAX_RETRIES}): {url} - {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"リクエストに最終的に失敗しました: {url}", exc_info=True)
    return None

def fetch_dividend_history(stock_code: str, num_years: int = 10) -> dict:
    """
    Yahoo!ファイナンスの配当ページから過去数年分の1株あたり配当を取得する。
    """
    dividend_url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T/dividend"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    response = _make_request(dividend_url, headers)
    if not response:
        return {}

    try:
        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if not match:
            logger.warning(f"銘柄 {stock_code} の配当ページで __PRELOADED_STATE__ が見つかりませんでした。")
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

        sorted_years = sorted(yearly_dividends.keys(), reverse=True)
        
        result = {}
        for year in sorted_years[:num_years]:
            result[year] = yearly_dividends[year]
        
        return result

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"銘柄 {stock_code} の配当データ解析中にエラーが発生しました。", exc_info=True)
        return {}

def fetch_stock_data(stock_code: str, num_years_dividend: int = 10) -> Optional[dict]:
    """
    Yahoo!ファイナンスのページから株価情報と配当履歴を取得する。
    """
    url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    response = _make_request(url, headers)
    if not response:
        return {"code": stock_code, "name": f"{stock_code}", "error": "ネットワークエラーにより情報を取得できませんでした。"}

    try:
        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if not match:
            logger.warning(f"銘柄 {stock_code} の株価ページで __PRELOADED_STATE__ が見つかりませんでした。銘柄が存在しない可能性があります。")
            return {"code": stock_code, "name": f"{stock_code}", "error": "銘柄情報が見つかりません。コードを確認してください。"}

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

        dividend_history = fetch_dividend_history(stock_code, num_years_dividend)

        dividend_yield = price_board.get("shareDividendYield")
        if dividend_yield is None:
            dividend_yield = reference_index.get("shareDividendYield", "N/A")

        annual_dividend = reference_index.get("shareAnnualDividend")

        # メインページから取得できない場合のフォールバック
        if annual_dividend is None or str(annual_dividend).strip() in ["N/A", "---", ""]:
            if dividend_history:
                # 履歴の中から最新の年を取得して採用
                latest_year = max(dividend_history.keys(), key=int, default=None)
                if latest_year:
                    annual_dividend = dividend_history[latest_year]
                else:
                    annual_dividend = "N/A"
            else:
                annual_dividend = "N/A"

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
            "annual_dividend": annual_dividend,
            "dividend_history": dividend_history,
        }

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"銘柄 {stock_code} の株価データ解析中にエラーが発生しました。", exc_info=True)
        return {"code": stock_code, "name": f"{stock_code}", "error": "データ解析に失敗しました。サイトの仕様が変更された可能性があります。"}

if __name__ == '__main__':
    data = fetch_stock_data("8306", num_years_dividend=5)
    if data:
        print(json.dumps(data, indent=2, ensure_ascii=False))