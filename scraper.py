import requests
import json
import re
import time
import logging
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
from requests.exceptions import RequestException
from bs4 import BeautifulSoup
from cachetools import cached, TTLCache, cachedmethod

# --- ロガー設定 ---
logger = logging.getLogger(__name__)

# --- 定数 ---
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
}
# 為替レート取得用のヘッダー
FX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# --- キャッシュ設定 ---
# 各キャッシュの有効期限を1時間 (3600秒) に設定
CACHE_TTL = 3600

# --- 基底クラス ---
class BaseScraper(ABC):
    """
    すべてのスクレイパーの基底クラス。
    共通のリクエスト処理とキャッシュの仕組みを提供する。
    """
    def __init__(self, cache_size=128):
        self.cache = TTLCache(maxsize=cache_size, ttl=CACHE_TTL)

    def _make_request(self, url: str, headers: dict = None) -> Optional[requests.Response]:
        """指定されたURLに対してリトライ機能付きでリクエストを送信する"""
        final_headers = headers or DEFAULT_HEADERS
        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(url, headers=final_headers, timeout=10)
                response.raise_for_status()
                return response
            except RequestException as e:
                status_code = e.response.status_code if e.response is not None else "N/A"
                logger.warning(f"リクエスト失敗 (試行 {attempt + 1}/{MAX_RETRIES}): {url} - ステータスコード: {status_code}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                else:
                    logger.error(f"リクエストに最終的に失敗しました: {url} - ステータスコード: {status_code}", exc_info=True)
        return None

    @abstractmethod
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        """
        指定されたコードのデータを取得する。
        サブクラスで必ず実装する必要がある。
        """
        pass

# --- 国内株式スクレイパー ---
class JPStockScraper(BaseScraper):
    """国内株式のデータをYahoo!ファイナンスから取得する"""
    def __init__(self, cache_size=128, dividend_cache_size=128):
        super().__init__(cache_size)
        self.dividend_cache = TTLCache(maxsize=dividend_cache_size, ttl=CACHE_TTL)

    @cachedmethod(lambda self: self.dividend_cache)
    def _fetch_dividend_history(self, stock_code: str, num_years: int = 10) -> dict:
        """過去の配当履歴を取得する"""
        dividend_url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T/dividend"
        response = self._make_request(dividend_url)
        if not response:
            return {}
        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match: return {}
            preloaded_state = json.loads(match.group(1))
            dividend_data = preloaded_state.get("mainStocksDividend", {}).get("dps", [])
            if not dividend_data: return {}
            
            yearly_dividends = {
                re.search(r"(\d{4})", item.get("settlementDate", "")).group(1): item["annualCorrectedActualValue"]
                for item in dividend_data
                if item.get("valueType") == "actual" and "annualCorrectedActualValue" in item and re.search(r"(\d{4})", item.get("settlementDate", ""))
            }
            return {year: yearly_dividends[year] for year in sorted(yearly_dividends.keys(), reverse=True)[:num_years]}
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.error(f"銘柄 {stock_code} の配当データ解析中にエラー: {e}", exc_info=True)
            return {}

    @cachedmethod(lambda self: self.cache)
    def fetch_data(self, code: str, num_years_dividend: int = 10) -> Optional[Dict[str, Any]]:
        url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        response = self._make_request(url)
        if not response:
            return {"code": code, "name": f"{code}", "error": "ネットワークエラー"}

        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match:
                return {"code": code, "name": f"{code}", "error": "銘柄情報が見つかりません"}

            data = json.loads(match.group(1))
            price_board = data.get("mainStocksPriceBoard", {}).get("priceBoard", {})
            ref_index = data.get("mainStocksDetail", {}).get("referenceIndex", {})

            market_cap_str = ref_index.get("totalPrice", "N/A")
            market_cap = "N/A"
            if market_cap_str != "N/A":
                mc_val_str = re.sub(r'[^\d]', '', market_cap_str)
                if mc_val_str and mc_val_str.isdigit(): # isdigit() を追加
                    try:
                        market_cap = f"{int(mc_val_str) * 1_000_000:,}"
                    except (ValueError, TypeError):
                        market_cap = "N/A"
                else:
                    market_cap = "N/A" # 数字でない場合はN/Aとする

            dividend_history = self._fetch_dividend_history(code, num_years_dividend)
            
            return {
                "code": code, "name": price_board.get("name", "N/A"),
                "industry": price_board.get("industry", {}).get("industryName", "N/A"),
                "price": price_board.get("price", "N/A"), "change": price_board.get("priceChange", "N/A"),
                "change_percent": price_board.get("priceChangeRate", "N/A"), "market_cap": market_cap,
                "per": ref_index.get("per", "N/A"), "pbr": ref_index.get("pbr", "N/A"),
                "roe": ref_index.get("roe", "N/A"), "eps": ref_index.get("eps", "N/A"),
                "yield": price_board.get("shareDividendYield") or ref_index.get("shareDividendYield", "N/A"),
                "annual_dividend": ref_index.get("shareAnnualDividend", "N/A"),
                "dividend_history": dividend_history, "asset_type": "jp_stock", "currency": "JPY"
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"銘柄 {code} の株価データ解析中にエラー: {e}", exc_info=True)
            return {"code": code, "name": f"{code}", "error": "データ解析失敗"}

# --- 投資信託スクレイパー ---
class InvestTrustScraper(BaseScraper):
    """投資信託のデータをYahoo!ファイナンスから取得する"""
    @cachedmethod(lambda self: self.cache)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        url = f"https://finance.yahoo.co.jp/quote/{code}"
        response = self._make_request(url)
        if not response:
            return {"code": code, "name": f"{code}", "error": "ネットワークエラー"}

        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match:
                return {"code": code, "name": f"{code}", "error": "投信情報が見つかりません"}

            data = json.loads(match.group(1))
            price_board = data.get("mainFundPriceBoard", {}).get("fundPrices", {})
            detail_items = data.get("mainFundDetail", {}).get("items", {})

            rate = price_board.get("changePriceRate")
            net_assets_price = detail_items.get("netAssetBalance", {}).get("price", "N/A")
            trust_fee_rate = detail_items.get("payRateTotal", {}).get("rate", "N/A")

            return {
                "code": code, "name": price_board.get("name", "N/A"),
                "price": price_board.get("price", "N/A"), "change": price_board.get("changePrice", "N/A"),
                "change_percent": f'{rate}%' if rate is not None else "N/A",
                "net_assets": f"{net_assets_price}百万円" if net_assets_price != "N/A" else "N/A",
                "trust_fee": f"{trust_fee_rate}%" if trust_fee_rate != "N/A" else "N/A",
                "asset_type": "investment_trust", "currency": "JPY"
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"投資信託 {code} のデータ解析中にエラー: {e}", exc_info=True)
            return {"code": code, "name": f"{code}", "error": "データ解析失敗"}

# --- 米国株式スクレイパー ---
class USStockScraper(BaseScraper):
    """米国株式のデータをYahoo! Finance (US) から取得する"""
    @cachedmethod(lambda self: self.cache)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        url = f"https://finance.yahoo.com/quote/{code}"
        response = self._make_request(url)
        if not response:
            logger.error(f"米国株 {code}: ネットワークエラーにより情報を取得できませんでした。")
            return {"code": code, "name": f"{code}", "error": "ネットワークエラー"}

        try:
            soup = BeautifulSoup(response.content, "lxml")
            
            # デバッグログ: 取得したHTMLの一部を出力
            logger.debug(f"米国株 {code}: 取得したHTMLの先頭部分:\n{response.text[:500]}...")

            soup = BeautifulSoup(response.content, "lxml")
            
            logger.debug(f"米国株 {code}: 取得したHTMLの先頭部分:\n{response.text[:500]}...")

            # 銘柄名
            name_tag = soup.find("h1", {"data-test": "quote-header-info"})
            if not name_tag:
                name_tag = soup.find("h1", class_="D(ib) Fz(24px) Fw(b) Lh(24px) Mend(0px) D(ib)") # 新しいクラス名
            name = name_tag.text.replace(f"({code})", "").strip() if name_tag else "N/A"
            logger.debug(f"米国株 {code}: Name: {name}")

            # 市場情報
            market_info_div = soup.find("h1", {"data-test": "quote-header-info"})
            if market_info_div:
                market_info_div = market_info_div.find_next_sibling("div", class_="D(ib) Fz(12px) C($tertiaryColor) My(0px) Mstart(15px)")
            
            market_tag = None
            if market_info_div:
                market_span = market_info_div.find("span", class_="C($tertiaryColor) Fz(12px)")
                if market_span:
                    market = market_span.text.split(" - ")[0].strip()
                else:
                    market = "N/A"
            else:
                market = "N/A"
            logger.debug(f"米国株 {code}: Market: {market}")

            # 株価
            price_tag = soup.find("fin-streamer", {"data-field": "regularMarketPrice"})
            price = price_tag.text.strip() if price_tag else "N/A"
            logger.debug(f"米国株 {code}: Price: {price}")

            # 前日比
            change_tag = soup.find("fin-streamer", {"data-field": "regularMarketChange"})
            change = change_tag.text.strip() if change_tag else "N/A"
            logger.debug(f"米国株 {code}: Change: {change}")

            # 前日比率
            change_percent_tag = soup.find("fin-streamer", {"data-field": "regularMarketChangePercent"})
            change_percent_raw = change_percent_tag.text.strip("() ") if change_percent_tag else "N/A"
            logger.debug(f"米国株 {code}: Change Percent: {change_percent_raw}")
            
            # PER, 時価総額などの指標を取得
            summary_table = soup.find("div", {"data-test": "summary-detail"})
            market_cap, per, yield_val = "N/A", "N/A", "N/A"
            if summary_table:
                mc_tag = summary_table.find("td", {"data-test": "MARKET_CAP-value"})
                market_cap = mc_tag.text.strip() if mc_tag else "N/A"
                
                per_tag = summary_table.find("td", {"data-test": "PE_RATIO-value"})
                per = per_tag.text.strip() if per_tag else "N/A"

                yield_tag = summary_table.find("td", {"data-test": "DIVIDEND_AND_YIELD-value"})
                if yield_tag:
                    yield_text = yield_tag.text.strip()
                    yield_match = re.search(r'\((\d+\.\d+)%\)', yield_text)
                    yield_val = yield_match.group(1) if yield_match else "N/A"
                
            logger.debug(f"米国株 {code}: Market Cap: {market_cap}, PER: {per}, Yield: {yield_val}")

            return {
                "code": code, "name": name, "market": market, "price": price, "change": change,
                "change_percent": change_percent_raw, "market_cap": market_cap,
                "per": per, "pbr": "N/A", "roe": "N/A", "eps": "N/A", "yield": yield_val,
                "asset_type": "us_stock", "currency": "USD"
            }
        except Exception as e:
            logger.error(f"米国株 {code} のデータ解析中にエラー: {e}", exc_info=True)
            return {"code": code, "name": f"{code}", "error": "データ解析失敗"}

# --- 為替レート取得 ---
@cached(TTLCache(maxsize=10, ttl=CACHE_TTL))
def get_exchange_rate(pair: str = 'USDJPY=X') -> Optional[float]:
    """Yahoo! Financeから為替レートを取得する"""
    url = f"https://finance.yahoo.com/quote/{pair}"
    # BaseScraperのインスタンスを作成して_make_requestメソッドを利用
    scraper_instance = BaseScraper()
    response = scraper_instance._make_request(url, headers=FX_HEADERS)
    if not response:
        return None
    try:
        soup = BeautifulSoup(response.content, "lxml")
        price_tag = soup.find("fin-streamer", {"data-field": "regularMarketPrice", "data-symbol": pair})
        if price_tag and price_tag.text:
            return float(price_tag.text.replace(',', ''))
    except (ValueError, AttributeError) as e:
        logger.error(f"為替レート ({pair}) の解析中にエラー: {e}", exc_info=True)
    return None

# --- ファクトリ関数 ---
def get_scraper(asset_type: str) -> BaseScraper:
    """資産種別に応じて適切なScraperインスタンスを返す"""
    if asset_type == 'jp_stock':
        return JPStockScraper()
    if asset_type == 'investment_trust':
        return InvestTrustScraper()
    if asset_type == 'us_stock':
        return USStockScraper()
    raise ValueError(f"Unsupported asset type: {asset_type}")

# --- テスト用 ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    def test_scraper(scraper: BaseScraper, code: str, title: str):
        print(f"\n--- {title}: {code} ---")
        data = scraper.fetch_data(code)
        print(json.dumps(data, indent=2, ensure_ascii=False))

    # 国内株
    jp_scraper = get_scraper('jp_stock')
    test_scraper(jp_scraper, "7203", "国内株式")
    
    # 投資信託
    it_scraper = get_scraper('investment_trust')
    test_scraper(it_scraper, "0331418A", "投資信託")

    # 米国株
    us_scraper = get_scraper('us_stock')
    test_scraper(us_scraper, "AAPL", "米国株式")

    # 為替レート
    print("\n--- 為替レート ---")
    usd_jpy = get_exchange_rate('USDJPY=X')
    print(f"USD/JPY: {usd_jpy}")

    # エラーケース
    test_scraper(jp_scraper, "99999", "存在しない国内株式")
    test_scraper(us_scraper, "INVALID", "存在しない米国株式")