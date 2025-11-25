import requests
import json
import re
import time
from typing import Optional
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
import logging
from cachetools import cached, TTLCache

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2 # seconds

# キャッシュの有効期限を1時間 (3600秒) に設定
STOCK_DATA_CACHE = TTLCache(maxsize=128, ttl=3600)
DIVIDEND_HISTORY_CACHE = TTLCache(maxsize=128, ttl=3600)
FUND_DATA_CACHE = TTLCache(maxsize=128, ttl=3600) # 投資信託用キャッシュ

def _make_request(url: str, headers: dict) -> Optional[requests.Response]:
    """指定されたURLに対してリトライ機能付きでリクエストを送信する"""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status() # 4xx or 5xx status will raise an HTTPError
            return response
        except RequestException as e:
            status_code = e.response.status_code if e.response is not None else "N/A"
            logger.warning(f"リクエスト失敗 (試行 {attempt + 1}/{MAX_RETRIES}): {url} - ステータスコード: {status_code} - エラー: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"リクエストに最終的に失敗しました: {url} - ステータスコード: {status_code}", exc_info=True)
    return None

@cached(cache=DIVIDEND_HISTORY_CACHE)
def fetch_dividend_history(stock_code: str, num_years: int = 10) -> dict:
    """
    Yahoo!ファイナンスの配当ページから過去数年分の1株あたり配当を取得する。
    """
    dividend_url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T/dividend"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
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

@cached(cache=STOCK_DATA_CACHE)
def fetch_stock_data(stock_code: str, num_years_dividend: int = 10) -> Optional[dict]:
    """
    Yahoo!ファイナンスのページから株価情報と配当履歴を取得する。
    """
    url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
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
        reference_index = preloaded_index = preloaded_state.get("mainStocksDetail", {}).get("referenceIndex", {})

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

@cached(cache=FUND_DATA_CACHE)
def fetch_fund_data(fund_code: str) -> Optional[dict]:
    """
    Yahoo!ファイナンスの投資信託ページから情報を取得する。
    __PRELOADED_STATE__ のJSONを優先的に使用する。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    main_url = f"https://finance.yahoo.co.jp/quote/{fund_code}"
    response = _make_request(main_url, headers)

    if not response:
        return {"code": fund_code, "name": f"{fund_code}", "error": "ネットワークエラーにより情報を取得できませんでした。"}

    try:
        # __PRELOADED_STATE__ JSONの抽出を試みる
        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if match:
            preloaded_state = json.loads(match.group(1))
            
            price_board = preloaded_state.get("mainFundPriceBoard", {}).get("fundPrices", {})
            detail_items = preloaded_state.get("mainFundDetail", {}).get("items", {})

            name = price_board.get("name", "N/A")
            price = price_board.get("price", "N/A")
            change = price_board.get("changePrice", "N/A")
            
            rate_value = price_board.get("changePriceRate")
            change_percent = f'{rate_value}%' if rate_value is not None else "N/A"

            net_assets_info = detail_items.get("netAssetBalance", {})
            net_assets_price = net_assets_info.get("price", "N/A")
            net_assets = f"{net_assets_price}百万円" if net_assets_price != "N/A" else "N/A"

            trust_fee_info = detail_items.get("payRateTotal", {})
            trust_fee = trust_fee_info.get("rate", "N/A")
            if trust_fee != "N/A":
                trust_fee = f"{trust_fee}%"

            return {
                "code": fund_code,
                "name": name,
                "price": price,
                "change": change,
                "change_percent": change_percent,
                "net_assets": net_assets,
                "trust_fee": trust_fee,
                "asset_type": "investment_trust"
            }

        # JSONが取得できない場合、BeautifulSoupでのフォールバック
        logger.warning(f"投資信託 {fund_code} で __PRELOADED_STATE__ が見つかりませんでした。HTML解析にフォールバックします。")
        soup = BeautifulSoup(response.content, "lxml")

        if "ページが見つかりません" in soup.title.text:
            return {"code": fund_code, "name": f"{fund_code}", "error": "投資信託情報が見つかりません。コードを確認してください。"}

        name_tag = soup.select_one('h2.PriceBoard__name__166W')
        name = name_tag.text.strip() if name_tag else "N/A"

        price = "N/A"
        change = "N/A"
        change_percent = "N/A"
        price_info_area = soup.select_one('div.PriceBoard__priceInformation__78Tl')
        if price_info_area:
            price_tag = price_info_area.select_one('span.StyledNumber__value__3rXW')
            price = price_tag.text.strip() if price_tag else "N/A"
            
            change_label = price_info_area.select_one('dd.PriceChangeLabel__description__a5Lp')
            if change_label:
                change_parts = [item.text.strip() for item in change_label.select('span.StyledNumber__item__1-yu')]
                if len(change_parts) > 0:
                    change = change_parts[0]
                if len(change_parts) > 1:
                    # e.g. "(-0.82%)" -> "-0.82%"
                    change_percent = change_parts[1].strip('()')

        net_assets = "N/A"
        net_assets_th = soup.find('th', string='純資産残高')
        if net_assets_th:
            net_assets_td = net_assets_th.find_next_sibling('td')
            if net_assets_td:
                value = net_assets_td.select_one('span.number__1EHf').text.strip()
                unit = net_assets_td.find(string=re.compile(r'百万円|億円'))
                net_assets = f"{value}{unit}" if value and unit else (value if value else "N/A")

        trust_fee = "N/A"
        trust_fee_th = soup.find('th', string='信託報酬')
        if trust_fee_th:
            trust_fee_td = trust_fee_th.find_next_sibling('td')
            if trust_fee_td:
                trust_fee = trust_fee_td.text.strip()

        return {
            "code": fund_code,
            "name": name,
            "price": price,
            "change": change,
            "change_percent": change_percent,
            "net_assets": net_assets,
            "trust_fee": trust_fee,
            "asset_type": "investment_trust"
        }

    except Exception as e:
        logger.error(f"投資信託 {fund_code} のデータ解析中にエラーが発生しました。", exc_info=True)
        return {"code": fund_code, "name": f"{fund_code}", "error": "データ解析に失敗しました。サイトの仕様が変更された可能性があります。"}


if __name__ == '__main__':
    # Test stock data fetching
    stock_data = fetch_stock_data("8306", num_years_dividend=5)
    if stock_data:
        print("--- Stock Data ---")
        print(json.dumps(stock_data, indent=2, ensure_ascii=False))

    # Test fund data fetching
    fund_data = fetch_fund_data("0331418A") # eMAXIS Slim 全世界株式(オール・カントリー)
    if fund_data:
        print("\n--- Fund Data ---")
        print(json.dumps(fund_data, indent=2, ensure_ascii=False))

    # Test non-existent stock
    invalid_stock = fetch_stock_data("99999", num_years_dividend=5)
    if invalid_stock:
        print("\n--- Invalid Stock ---")
        print(json.dumps(invalid_stock, indent=2, ensure_ascii=False))

    # Test non-existent fund
    invalid_fund = fetch_fund_data("XXXXXXXX")
    if invalid_fund:
        print("\n--- Invalid Fund ---")
        print(json.dumps(invalid_fund, indent=2, ensure_ascii=False))
