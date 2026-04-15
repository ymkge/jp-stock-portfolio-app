import requests
from bs4 import BeautifulSoup
import json
import re
import time
import logging
import asyncio
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from cachetools import cachedmethod, TTLCache, cached

# ロガーの設定
logger = logging.getLogger(__name__)

# 定数
MAX_RETRIES = 3
RETRY_DELAY = 2
CACHE_TTL = 3600  # 1時間

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1"
}

FX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Referer": "https://finance.yahoo.co.jp/"
}

# --- 共通ベースクラス ---
class BaseScraper(ABC):
    """
    スクレイパークラスのベースとなる抽象クラス。
    共通のリクエスト処理とキャッシュの仕組みを提供する。
    """
    def __init__(self, cache_size=128):
        self.cache = TTLCache(maxsize=cache_size, ttl=CACHE_TTL)
        # セッションを初期化し、接続を維持 (Keep-Alive) する
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.last_error = None

    def is_cached(self, code: str) -> bool:
        """指定されたコードのデータがキャッシュに存在するか確認する"""
        return code in self.cache

    def _make_request(self, url: str, headers: dict = None) -> Optional[requests.Response]:
        """指定されたURLに対してリトライ機能付きでリクエストを送信する"""
        # 直近のエラー情報をクリア
        self.last_error = None
        
        # 個別のヘッダー指定があれば優先し、なければセッションのデフォルトを使用
        request_headers = headers or self.session.headers
        for attempt in range(MAX_RETRIES):
            try:
                # requests.get ではなく self.session.get を使用して接続を使い回す
                response = self.session.get(url, headers=request_headers, timeout=10)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                status_code = e.response.status_code if e.response is not None else "N/A"
                self.last_error = {"status_code": status_code, "url": url, "type": type(e).__name__}
                
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
        # Refererを設定してメインページからの遷移を装う
        headers = self.session.headers.copy()
        headers["Referer"] = f"https://finance.yahoo.co.jp/quote/{stock_code}.T"
        
        response = self._make_request(dividend_url, headers=headers)
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

    def _calculate_moving_average(self, sorted_histories: list, days: int) -> Optional[float]:
        """直近N日間の終値の平均を計算する"""
        if not sorted_histories or len(sorted_histories) < days:
            return None
        
        # 直近N日分のデータを取得 (リストの末尾が最新と仮定)
        recent_data = sorted_histories[-days:]
        try:
            total_close = sum(float(item["closePrice"]) for item in recent_data if "closePrice" in item)
            return total_close / days
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    def _calculate_rci(self, sorted_histories: list, days: int) -> Optional[float]:
        """RCI (Rank Correlation Index) を計算する"""
        if not sorted_histories or len(sorted_histories) < days:
            return None

        # 直近N日分の終値を取得
        recent_data = sorted_histories[-days:]
        try:
            prices = [float(item["closePrice"]) for item in recent_data if "closePrice" in item]
            if len(prices) < days:
                return None
            
            # 日付の順位 (最新が1、古いほど大きい) -> 計算式上は古い順に 1, 2, ..., n
            # ここでは 1, 2, ..., n を日付順位 X とする
            x_ranks = list(range(1, days + 1))
            
            # 価格の順位 (値が高いほど 1) -> 価格が高い順に 1, 2, ..., n
            sorted_prices = sorted(enumerate(prices), key=lambda x: x[1], reverse=True)
            y_ranks_temp = [0] * days
            for rank, (original_index, _) in enumerate(sorted_prices, 1):
                y_ranks_temp[original_index] = rank
            
            # RCI計算用に日付順（古い順）にする。
            y_ranks = y_ranks_temp 

            d_squared_sum = sum((x - y)**2 for x, y in zip(x_ranks, y_ranks))
            rci = (1 - (6 * d_squared_sum) / (days * (days**2 - 1))) * 100
            return rci
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    def _calculate_rsi(self, sorted_histories: list, days: int) -> Optional[float]:
        """RSI (Relative Strength Index) を計算する"""
        if not sorted_histories or len(sorted_histories) < days + 1:
            return None

        recent_data = sorted_histories[-(days + 1):]
        try:
            prices = [float(item["closePrice"]) for item in recent_data if "closePrice" in item]
            if len(prices) < days + 1: return None

            diffs = [prices[i+1] - prices[i] for i in range(days)]
            up = sum(d for d in diffs if d > 0)
            down = sum(-d for d in diffs if d < 0)

            if up + down == 0: return 50.0
            return (up / (up + down)) * 100
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    def _calculate_fibonacci(self, sorted_histories: list) -> Optional[dict]:
        """フィボナッチ・リトレースメントを計算する"""
        if not sorted_histories or len(sorted_histories) < 2:
            return None

        try:
            prices = [float(item["closePrice"]) for item in sorted_histories if "closePrice" in item]
            if not prices: return None
            
            high = max(prices)
            low = min(prices)
            current = prices[-1]
            
            if high == low: return None
            
            # 下落率 (最高値からの戻し)
            retracement = (high - current) / (high - low) * 100
            
            return {
                "high": high, "low": low, "current": current,
                "retracement": retracement,
                "period": len(prices)
            }
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    @cachedmethod(lambda self: self.cache, key=lambda self, code, **kwargs: code)
    def fetch_data(self, code: str, num_years_dividend: int = 10) -> Optional[Dict[str, Any]]:
        url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        response = self._make_request(url)
        if not response:
            error_msg = "銘柄情報の取得に失敗しました（通信エラー）"
            return {"code": code, "name": f"{code}", "error": error_msg, "error_details": self.last_error}
        
        # メインページ取得後、配当履歴取得前に1秒待機（バーストアクセス防止）
        time.sleep(1.0)

        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match:
                return {"code": code, "name": f"{code}", "error": "銘柄情報が見つかりません", "error_details": {"type": "ParseError", "status_code": 200}}

            data = json.loads(match.group(1))
            price_board = data.get("mainStocksPriceBoard", {}).get("priceBoard", {})
            ref_index = data.get("mainStocksDetail", {}).get("referenceIndex", {})
            
            # --- 決算月を取得 (メインページのデータから抽出) ---
            settlement_month = "N/A"
            try:
                # 1. 指標データ(PER, EPS等)に紐付く日付から決算月を特定 (JSONベース)
                # 例: "2026/03" -> "3月"
                for key in ["shareDividendYield", "eps", "per"]:
                    item = ref_index.get(key)
                    if isinstance(item, dict) and item.get("date"):
                        date_str = item.get("date")
                        month_match = re.search(r"/(\d{2})", date_str)
                        if month_match:
                            settlement_month = f"{int(month_match.group(1))}月"
                            break
                
                # 2. JSONで取れなかった場合、HTMLから直接抽出を試みる (表示されている日付を優先)
                # <span class="DataListItem__date___6wH">(<!-- -->2026/03<!-- -->)</span> の形式を検索
                if settlement_month == "N/A":
                    html_date_match = re.search(r'class="DataListItem__date___6wH">\(<!-- -->(\d{4})/(\d{2})<!-- -->\)', response.text)
                    if html_date_match:
                        settlement_month = f"{int(html_date_match.group(2))}月"
                
                # 3. それでも取れなかった場合、配当基準日(dpsPeriod)から特定 (メタデータ補完)
                # "2026-02-01" などの形式を想定
                if settlement_month == "N/A":
                    dps_period = price_board.get("dpsPeriod")
                    if dps_period:
                        month_match = re.search(r"-(\d{2})", dps_period)
                        if month_match:
                            settlement_month = f"{int(month_match.group(1))}月"
            except Exception as e:
                logger.warning(f"銘柄 {code} の決算月解析中にエラー: {e}")
            # --------------------

            # --- トレンド分析用のデータ取得と計算 ---
            ma_25 = None
            ma_75 = None
            trend_signal = "N/A"
            rci_26 = None
            fibonacci = None
            
            try:
                chart_setting = data.get("mainItemDetailChartSetting", {})
                histories = chart_setting.get("timeSeriesData", {}).get("histories", [])
                
                if histories:
                    # 日付順にソート
                    sorted_histories = sorted(histories, key=lambda x: x.get("baseDatetime", ""))
                    
                    # 移動平均線の計算
                    ma_5 = self._calculate_moving_average(sorted_histories, 5)
                    ma_25 = self._calculate_moving_average(sorted_histories, 25)
                    ma_75 = self._calculate_moving_average(sorted_histories, 75)
                    
                    if ma_25 and ma_75:
                        trend_signal = "uptrend" if ma_25 > ma_75 else "downtrend"
                    
                    # RCI (26日) の計算
                    rci_26 = self._calculate_rci(sorted_histories, 26)
                    
                    # RSI (14日) の計算
                    rsi_14 = self._calculate_rsi(sorted_histories, 14)
                    rsi_14_prev = self._calculate_rsi(sorted_histories[:-1], 14)
                    
                    # フィボナッチの計算 (全期間を使用、通常125日程度)
                    fibonacci = self._calculate_fibonacci(sorted_histories)
            except Exception as e:
                logger.warning(f"銘柄 {code} のトレンドデータ計算中にエラー: {e}")
            # --------------------------------------

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
                # dividend_historyのキーは文字列의年なので、数値に変換して最大値を取得
                latest_year = max(dividend_history.keys(), key=int) 
                latest_annual_dividend = dividend_history[latest_year]

            # --- 配当利回りのリカバリ対応 ---
            dividend_yield = get_ref_value("shareDividendYield")
            if dividend_yield in [None, "N/A", "", "--"]:
                try:
                    # 現在株価を取得 (文字列の場合はカンマを除去)
                    price_str = price_board.get("price")
                    if isinstance(price_str, str):
                        price_str = price_str.replace(',', '')
                    price_val = float(price_str)
                    
                    if price_val > 0 and isinstance(latest_annual_dividend, (int, float)):
                        calculated_yield = (latest_annual_dividend / price_val) * 100
                        dividend_yield = f"{calculated_yield:.2f}%"
                        logger.info(f"銘柄 {code}: 配当利回りをリカバリしました ({dividend_yield})")
                except (ValueError, TypeError):
                    pass
            # ------------------------------

            return {
                "code": code, "name": price_board.get("name", "N/A"),
                "industry": price_board.get("industry", {}).get("industryName", "N/A"),
                "price": price_board.get("price", "N/A"), "change": price_board.get("priceChange", "N/A"),
                "change_percent": price_board.get("priceChangeRate", "N/A"), "market_cap": market_cap,
                "per": get_ref_value("per"),
                "pbr": get_ref_value("pbr"),
                "roe": get_ref_value("roe"),
                "eps": get_ref_value("eps"),
                "yield": dividend_yield,
                "annual_dividend": latest_annual_dividend,
                "dividend_history": dividend_history,
                "settlement_month": settlement_month, # 取得した決算月を追加
                "moving_average_5": ma_5, # 追加
                "moving_average_25": ma_25, # トレンド分析用
                "moving_average_75": ma_75, # トレンド分析用
                "trend_signal": trend_signal, # トレンド分析用
                "rci_26": rci_26, # 追加
                "rsi_14": rsi_14, # 追加
                "rsi_14_prev": rsi_14_prev, # 追加
                "fibonacci": fibonacci, # 追加
                "asset_type": "jp_stock", "currency": "JPY"
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"銘柄 {code} の株価データ解析中にエラー: {e}", exc_info=True)
            return {"code": code, "name": f"{code}", "error": "データ解析失敗", "error_details": {"type": "ParseError", "status_code": 200}}

# --- 投資信託スクレイパー ---
class InvestTrustScraper(BaseScraper):
    """投資信託のデータをYahoo!ファイナンスから取得する"""
    @cachedmethod(lambda self: self.cache, key=lambda self, code: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        url = f"https://finance.yahoo.co.jp/quote/{code}"
        response = self._make_request(url)
        if not response:
            error_msg = "銘柄情報の取得に失敗しました（通信エラー）"
            return {"code": code, "name": f"{code}", "error": error_msg, "error_details": self.last_error}

        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match:
                return {"code": code, "name": f"{code}", "error": "銘柄情報が見つかりません", "error_details": {"type": "ParseError", "status_code": 200}}

            data = json.loads(match.group(1))
            price_board = data.get("mainFundPriceBoard", {}).get("fundPrices", {})
            detail_items = data.get("mainFundDetail", {}).get("items", {})

            rate = price_board.get("changePriceRate")
            net_assets_price = detail_items.get("netAssetBalance", {}).get("price", "N/A")
            trust_fee_rate = detail_items.get("payRateTotal", {}).get("rate", "N/A")

            return {
                "code": code, "name": price_board.get("name", "N/A"),
                "price": price_board.get("price", "N/A"), "change": price_board.get("changePrice", "N/A"),
                "change_percent": f'{rate}' if rate is not None else "N/A",
                "net_assets": f"{net_assets_price}百万円" if net_assets_price != "N/A" else "N/A",
                "trust_fee": f"{trust_fee_rate}%" if trust_fee_rate != "N/A" else "N/A",
                "asset_type": "investment_trust", "currency": "JPY"
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"投資信託 {code} のデータ解析中にエラー: {e}", exc_info=True)
            return {"code": code, "name": f"{code}", "error": "データ解析失敗", "error_details": {"type": "ParseError", "status_code": 200}}

# --- 米国株式スクレイパー ---
class USStockScraper(BaseScraper):
    """米国株式のデータをYahoo!ファイナンス (JP) から取得する"""
    @cachedmethod(lambda self: self.cache, key=lambda self, code: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        url = f"https://finance.yahoo.co.jp/quote/{code}"
        response = self._make_request(url)
        if not response:
            error_msg = "銘柄情報の取得に失敗しました（通信エラー）"
            return {"code": code, "name": f"{code}", "error": error_msg, "error_details": self.last_error}

        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match:
                return {"code": code, "name": f"{code}", "error": "銘柄情報が見つかりません", "error_details": {"type": "ParseError", "status_code": 200}}

            data = json.loads(match.group(1))
            price_board = data.get("mainUsStocksPriceBoard", {})
            ref_index = data.get("mainUsStocksReferenceIndex", {})

            # --- 決算月を取得 (詳細ページのデータから抽出) ---
            settlement_month = "N/A"
            try:
                # 1. 指標データ(PER, EPS等)の日付から決算月を特定 (JSONベース)
                for key in ["per", "eps", "pbr"]:
                    item = ref_index.get(key)
                    if isinstance(item, dict) and item.get("date"):
                        date_str = item.get("date") # 例: "2026/03"
                        month_match = re.search(r"/(\d{2})", date_str)
                        if month_match:
                            settlement_month = f"{int(month_match.group(1))}月"
                            break
                
                # 2. JSONで取れなかった場合、HTMLから日付パターンを探す (フォールバック)
                if settlement_month == "N/A":
                    # "(2026/03)" または "2026年12月31日" などの形式を幅広く探す
                    html_date_match = re.search(r'\(<!-- -->(\d{4})/(\d{2})<!-- -->\)', response.text)
                    if html_date_match:
                        settlement_month = f"{int(html_date_match.group(2))}月"
                    else:
                        # "2024年12月31日" のような形式を探す
                        jp_date_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', response.text)
                        if jp_date_match:
                            settlement_month = f"{int(jp_date_match.group(2))}月"
            except Exception as e:
                logger.warning(f"米国株 {code} の決算月解析中にエラー: {e}")
            # --------------------

            # 時価総額の整形
            market_cap_data = ref_index.get("totalPrice", {})
            market_cap = "N/A"
            logger.debug(f"米国株 {code} の market_cap_data: {market_cap_data}")
            if market_cap_data and market_cap_data.get("value"):
                try:
                    value_str = market_cap_data.get("value", "0").replace(',', '')
                    suffix = market_cap_data.get("suffix", "")
                    if value_str.endswith(".00"):
                        value_str = value_str[:-3]
                    value = float(value_str)

                    market_cap_usd = 0
                    if "千ドル" in suffix:
                        market_cap_usd = value * 1000
                    elif "百万ドル" in suffix:
                        market_cap_usd = value * 1_000_000
                    elif "億ドル" in suffix:
                        market_cap_usd = value * 100_000_000
                    else:
                        market_cap_usd = value

                    exchange_rate = get_exchange_rate('USDJPY=X')
                    if exchange_rate and market_cap_usd > 0:
                        market_cap_jpy = market_cap_usd * exchange_rate
                        market_cap = str(int(market_cap_jpy)) # 小数点以下は不要なのでintに変換
                    else:
                        market_cap = f"{value_str} {suffix}".strip()
                        logger.warning(f"米国株 {code}: 為替レート取得失敗、または時価総額が0のため、ドル表記のままにします: {market_cap}")

                except (ValueError, TypeError) as e:
                    logger.warning(f"米国株 {code} の時価総額解析中にエラー: {e}")
                    original_str = market_cap_data.get("value", "N/A")
                    if original_str.endswith(".00"):
                        original_str = original_str[:-3]
                    market_cap = f"{original_str} {market_cap_data.get('suffix', '')}".strip()

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
            return {"code": code, "name": f"{code}", "error": "データ解析失敗", "error_details": {"type": "ParseError", "status_code": 200}}

# --- 市場指標スクレイパー ---
class IndexScraper(BaseScraper):
    """市場指標（日経平均、TOPIX、先物等）のデータをYahoo!ファイナンスから取得する"""
    @cachedmethod(lambda self: self.cache, key=lambda self, code: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        # 指標・先物の場合はコードをそのままURLに使用（.Tを付加しない）
        url = f"https://finance.yahoo.co.jp/quote/{code}"
        response = self._make_request(url)
        if not response:
            error_msg = "指標情報の取得に失敗しました（通信エラー）"
            return {"code": code, "name": f"{code}", "error": error_msg, "error_details": self.last_error}

        try:
            match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
            if not match:
                return {"code": code, "name": f"{code}", "error": "指標情報が見つかりません", "error_details": {"type": "ParseError", "status_code": 200}}

            data = json.loads(match.group(1))
            
            # 探索順序: 国内指数(現物・先物) -> インデックスリスト
            price_board = None
            
            # 1. mainDomesticIndexPriceBoard (日経平均, TOPIX, 先物等)
            domestic_board = data.get("mainDomesticIndexPriceBoard", {})
            if domestic_board:
                price_board = domestic_board.get("indexPrices")
            
            # 2. mainIndicesPriceBoard (複数の指標が並ぶページ)
            if not price_board:
                indices = data.get("mainIndicesPriceBoard", {}).get("indices", [])
                for idx in indices:
                    if idx.get("code") == code:
                        price_board = idx
                        break
            
            if not price_board:
                return {"code": code, "name": f"{code}", "error": "指標データ構造の解析に失敗しました", "error_details": {"type": "ParseError", "status_code": 200}}

            # 前日比（%）の正規化
            rate = price_board.get("changePriceRate")
            change_percent = f"{rate}" if rate is not None else "N/A"

            return {
                "code": code,
                "name": price_board.get("name", "N/A"),
                "price": price_board.get("price", "N/A"),
                "change": price_board.get("changePrice", "N/A"),
                "change_percent": change_percent,
                "asset_type": "market_index",
                "currency": "JPY"
            }
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.error(f"指標 {code} のデータ解析中にエラー: {e}", exc_info=True)
            return {"code": code, "name": f"{code}", "error": "データ解析失敗", "error_details": {"type": "ParseError", "status_code": 200}}

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
        elif asset_type == 'market_index':
            _scraper_instances[asset_type] = IndexScraper()
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
    test_scraper(us_scraper, "NVDA", "米国株式 (NVDA)")

    # 指標
    index_scraper = get_scraper('market_index')
    test_scraper(index_scraper, "998407.O", "日経平均")
    test_scraper(index_scraper, "5040469.O", "日経先物")

    # 為替レート
    print("\n--- 為替レート ---")
    usd_jpy = get_exchange_rate('USDJPY=X')
    print(f"USD/JPY: {usd_jpy}")
