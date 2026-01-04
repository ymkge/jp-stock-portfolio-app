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
# --------------------

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
            yearly_dividends = {}
            for item in dividend_data:
                settlement_date_match = re.search(r"(\d{4})", item.get("settlementDate", ""))
                if not settlement_date_match:
                    continue
                year = settlement_date_match.group(1)

                # 会社予想 (forecast) を優先的に取得
                if item.get("valueType") == "forecast" and "annualForecastValue" in item:
                    yearly_dividends[year] = item["annualForecastValue"]
                # 実績 (actual) があれば、forecastがない場合にのみ使用
                elif item.get("valueType") == "actual" and "annualCorrectedActualValue" in item and year not in yearly_dividends:
                    yearly_dividends[year] = item["annualCorrectedActualValue"]

            return {year: yearly_dividends[year] for year in sorted(yearly_dividends.keys(), key=int, reverse=True)[:num_years]}
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.error(f"銘柄 {stock_code} の配当データ解析中にエラー: {e}", exc_info=True)
            return {}

    @cachedmethod(lambda self: self.cache)
    def fetch_data(self, code: str, num_years_dividend: int = 10) -> Optional[Dict[str, Any]]:
        # --- 決算月を取得 ---
        settlement_month = "N/A"
        try:
            profile_url = f"https://finance.yahoo.co.jp/quote/{code}.T/profile"
            profile_response = self._make_request(profile_url)
            if profile_response:
                match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", profile_response.text)
                if match:
                    profile_data = json.loads(match.group(1))
                    profile_items = profile_data.get("mainStocksProfile", {}).get("items", [])
                    for item in profile_items:
                        if item.get("head") == "決算":
                            date_text = item.get("details", [{}])[0].get("text", "") # "2月末日"
                            month_match = re.search(r"(\d+)月", date_text)
                            if month_match:
                                settlement_month = month_match.group(0)
                            break
        except Exception as e:
            logger.warning(f"銘柄 {code} の決算月取得中にエラー: {e}")
        # --------------------

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

            # オブジェクトと文字列の両方に対応できる、より堅牢なヘルパー関数
            def get_ref_value(key, source_dict=ref_index):
                item = source_dict.get(key)
                if isinstance(item, dict):
                    return item.get("value", "N/A")
                # 辞書でない場合は、その値自体を返す (Noneの場合は"N/A"にフォールバック)
                return item if item is not None else "N/A"

            market_cap_item = ref_index.get("totalPrice")
            market_cap = "N/A"
            logger.debug(f"銘柄 {code} の market_cap_item (raw): {market_cap_item}")

            try:
                if isinstance(market_cap_item, dict) and market_cap_item.get("value"):
                    # パターンA: 辞書形式の場合 (米国株と同様の形式を想定)
                    logger.debug(f"銘柄 {code}: 時価総額を辞書として処理")
                    market_cap_str = market_cap_item["value"]
                    # 不要な ".00" を削除
                    if market_cap_str.endswith(".00"):
                        market_cap_str = market_cap_str[:-3]
                    market_cap = f"{market_cap_str}{market_cap_item.get('suffix', '')}".strip()

                elif isinstance(market_cap_item, str) and market_cap_item not in ["N/A", "--", ""]:
                    # パターンB: 文字列形式の場合 (例: "12,345")
                    logger.debug(f"銘柄 {code}: 時価総額を文字列として処理")
                    mc_val_str = re.sub(r'[^0-9]', '', market_cap_item) # カンマを除去
                    if mc_val_str.isdigit():
                        # 単位が「百万円」であることを前提とする既存のロジック
                        market_cap = f"{int(mc_val_str) * 1_000_000:,}"
                    else:
                        # "1.23兆円" のような形式は現状では正しくパースできないため、
                        # ひとまずそのままの値を使う
                        market_cap = market_cap_item
                else:
                    logger.debug(f"銘柄 {code}: 時価総額が N/A または空")

            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"銘柄 {code} の時価総額解析中に予期せぬエラー: {e}", exc_info=True)
                market_cap = "N/A"
            
            logger.debug(f"銘柄 {code} の最終的な market_cap: {market_cap}")

            dividend_history = self._fetch_dividend_history(code, num_years_dividend)
            
            # annual_dividend を dividend_history から取得するように変更
            latest_annual_dividend = "N/A"
            if dividend_history:
                # dividend_historyのキーは文字列の年なので、数値に変換して最大値を取得
                latest_year = max(dividend_history.keys(), key=int) 
                latest_annual_dividend = dividend_history[latest_year]

            return {
                "code": code, "name": price_board.get("name", "N/A"),
                "industry": price_board.get("industry", {}).get("industryName", "N/A"),
                "price": price_board.get("price", "N/A"), "change": price_board.get("priceChange", "N/A"),
                "change_percent": price_board.get("priceChangeRate", "N/A"), "market_cap": market_cap,
                "per": get_ref_value("per"),
                "pbr": get_ref_value("pbr"),
                "roe": get_ref_value("roe"),
                "eps": get_ref_value("eps"),
                "yield": get_ref_value("shareDividendYield"),
                "annual_dividend": latest_annual_dividend,
                "dividend_history": dividend_history,
                "settlement_month": settlement_month, # 取得した決算月を追加
                "asset_type": "jp_stock", "currency": "JPY"
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
    """米国株式のデータをYahoo!ファイナンス (JP) から取得する"""
    @cachedmethod(lambda self: self.cache)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        # --- 決算月を取得 ---
        settlement_month = "N/A"
        try:
            # 米国株の場合、/performance ページから取得
            performance_url = f"https://finance.yahoo.co.jp/quote/{code}/performance"
            performance_response = self._make_request(performance_url)
            if performance_response:
                match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", performance_response.text)
                if match:
                    performance_data = json.loads(match.group(1))
                    settlement_items = performance_data.get("mainUsStocksSettlement", {}).get("annualSettlement", {}).get("items", [])
                    for item in settlement_items:
                        if item.get("head") == "決算日":
                            date_text = item.get("details", [""])[0] # "2024年12月31日"
                            month_match = re.search(r"(\d+)月", date_text)
                            if month_match:
                                settlement_month = month_match.group(0)
                            break
        except Exception as e:
            logger.warning(f"銘柄 {code} の決算月取得中にエラー: {e}")
        # --------------------

        url = f"https://finance.yahoo.co.jp/quote/{code}"
        response = self._make_request(url)
        if not response:
            logger.error(f"米国株 {code}: ネットワークエラーにより情報を取得できませんでした。")
            return {"code": code, "name": f"{code}", "error": "ネットワークエラー"}

        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match:
                return {"code": code, "name": f"{code}", "error": "銘柄情報が見つかりません"}

            data = json.loads(match.group(1))
            price_board = data.get("mainUsStocksPriceBoard", {})
            ref_index = data.get("mainUsStocksReferenceIndex", {})

            # 時価総額の整形
            market_cap_data = ref_index.get("totalPrice", {})
            market_cap = "N/A"
            logger.debug(f"米国株 {code} の market_cap_data: {market_cap_data}") # 追加
            if market_cap_data and market_cap_data.get("value"):
                # 整形済み文字列をそのまま利用
                market_cap_str = market_cap_data["value"]
                logger.debug(f"米国株 {code} の market_cap_str (before .00 removal): {market_cap_str}") # 追加
                # 不要な ".00" を削除
                if market_cap_str.endswith(".00"):
                    market_cap_str = market_cap_str[:-3]
                logger.debug(f"米国株 {code} の market_cap_str (after .00 removal): {market_cap_str}") # 追加
                market_cap = f"{market_cap_str} {market_cap_data.get('suffix', '')}".strip()
                logger.debug(f"米国株 {code} の最終的な market_cap: {market_cap}") # 追加

            # PER, PBRなどの指標値を取得
            def get_ref_value(key):
                return ref_index.get(key, {}).get("value", "N/A")

            return {
                "code": code,
                "name": price_board.get("name", "N/A"),
                "market": price_board.get("label", "N/A"),
                "price": price_board.get("price", "N/A"),
                "change": price_board.get("priceChange", "N/A"),
                "change_percent": price_board.get("priceChangeRate", "N/A"),
                "market_cap": market_cap,
                "per": get_ref_value("per"),
                "pbr": get_ref_value("pbr"),
                "roe": "N/A",  # データソースに存在しないため
                "eps": get_ref_value("eps"),
                "yield": "N/A", # データソースに存在しないため
                "settlement_month": settlement_month, # 取得した決算月を追加
                "asset_type": "us_stock",
                "currency": "USD"
            }
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.error(f"米国株 {code} のデータ解析中にエラー: {e}", exc_info=True)
            return {"code": code, "name": f"{code}", "error": "データ解析失敗"}

# --- 為替レート取得 ---
@cached(TTLCache(maxsize=10, ttl=CACHE_TTL))
def get_exchange_rate(pair: str = 'USDJPY=X') -> Optional[float]:
    """Yahoo!ファイナンス (JP) から為替レートを取得する"""
    url = f"https://finance.yahoo.co.jp/quote/{pair}"
    
    # _make_requestを呼び出すためだけにインスタンスを作成
    scraper_instance = JPStockScraper() 
    response = scraper_instance._make_request(url, headers=FX_HEADERS)
    
    if not response:
        return None
    
    try:
        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if not match:
            logger.warning(f"為替レート ({pair}) の __PRELOADED_STATE__ が見つかりません。")
            return None

        data = json.loads(match.group(1))
        rate = data.get("mainCurrencyDetail", {}).get("counterCurrencyPrice")
        
        if rate and isinstance(rate, (int, float)):
            return float(rate)
        else:
            logger.warning(f"為替レート ({pair}) の値がJSON内に見つからないか、無効な形式です。")
            return None
            
    except (json.JSONDecodeError, KeyError, AttributeError) as e:
        logger.error(f"為替レート ({pair}) の解析中にエラー: {e}", exc_info=True)
        return None

# --- ファクトリ関数 ---
# --- グローバルなスクレイパーインスタンスを保持する辞書 ---
_scraper_instances: Dict[str, BaseScraper] = {}

def get_scraper(asset_type: str) -> BaseScraper:
    """資産種別に応じて適切なScraperインスタンスを返す"""
    if asset_type not in _scraper_instances:
        if asset_type == 'jp_stock':
            _scraper_instances[asset_type] = JPStockScraper()
        elif asset_type == 'investment_trust':
            _scraper_instances[asset_type] = InvestTrustScraper()
        elif asset_type == 'us_stock':
            _scraper_instances[asset_type] = USStockScraper()
        else:
            raise ValueError(f"Unsupported asset type: {asset_type}")
    return _scraper_instances[asset_type]

# --- テスト用 ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    def test_scraper(scraper_instance: BaseScraper, code: str, title: str):
        print(f"\n--- {title}: {code} ---")
        data = scraper_instance.fetch_data(code)
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
    test_scraper(us_scraper, "NVDA", "米国株式 (NVDA)") # NVDAのテストを追加

    # 為替レート
    print("\n--- 為替レート ---")
    usd_jpy = get_exchange_rate('USDJPY=X')
    print(f"USD/JPY: {usd_jpy}")

    # エラーケース
    test_scraper(jp_scraper, "99999", "存在しない国内株式")
    test_scraper(us_scraper, "INVALID", "存在しない米国株式")

    # 問題の銘柄をテスト
    test_scraper(jp_scraper, "8130", "国内株式 (問題の銘柄)")
