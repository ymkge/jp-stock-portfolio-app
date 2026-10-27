import requests
from bs4 import BeautifulSoup
import json
import re
import time
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
from abc import ABC, abstractmethod
from cachetools import cachedmethod, TTLCache, cached
import yfinance as yf


# ロガーの設定
logger = logging.getLogger(__name__)

# 定数
MAX_RETRIES = 3
RETRY_DELAY = 5
CACHE_TTL = 3600  # 1時間

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# --- 共通ベースクラス ---
class BaseScraper(ABC):
    """
    スクレイパークラスのベースとなる抽象クラス。
    Next.js形式(新)と従来のJSON形式(旧)の両方に対応するハイブリッド抽出を提供する。
    """
    def __init__(self, cache_size=128):
        self.cache = TTLCache(maxsize=cache_size, ttl=CACHE_TTL)
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.last_error = None

    def _make_request(self, url: str, headers: dict = None) -> Optional[requests.Response]:
        self.last_error = None
        request_headers = headers or self.session.headers
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.get(url, headers=request_headers, timeout=10)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else "N/A"
                self.last_error = {
                    "status_code": status_code, 
                    "url": url, 
                    "type": "HTTPError",
                    "message": str(e)
                }
                # 403, 404などはリトライしても無駄なことが多いので即座にエラーとする
                if status_code in [403, 404]:
                    break
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
            except requests.exceptions.RequestException as e:
                self.last_error = {
                    "status_code": "N/A", 
                    "url": url, 
                    "type": type(e).__name__,
                    "message": str(e)
                }
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        return None

    def is_cached(self, code: str) -> bool:
        """指定されたコードのデータがキャッシュに存在するか確認する"""
        return code in self.cache

    def _extract_next_data(self, html: str) -> str:
        """Next.jsのストリーミングデータ(self.__next_f.push)を外科的に抽出・結合する"""
        chunks = []
        # re.S を追加して、チャンクが複数行に渡る可能性に対応
        # また、\"] \) などの並びを考慮し、より安全な終端マッチングを行う
        for match in re.finditer(r'self\.__next_f\.push\(\[\d+,\s*"(.*?)"\]\)', html, re.S):
            chunk = match.group(1)
            # JSONとしてのエスケープをデコード
            chunk = chunk.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n').replace('\\r', '\r').replace('\\t', '\t')
            chunks.append(chunk)
        return "".join(chunks)

    def _extract_legacy_data(self, html: str) -> str:
        """従来のJSON埋め込み形式(__PRELOADED_STATE__)を抽出する"""
        # 強欲マッチ (.*) を使用して、最後の </script> 直前の閉じ括弧まで拾う
        match = re.search(r'__PRELOADED_STATE__\s*=\s*(\{.*\}?)\s*</script>', html, re.S)
        return match.group(1).strip() if match else ""

    def _scavenge_common_data(self, html: str, json_text: str) -> Dict[str, Any]:
        """JSONとHTMLの両方から銘柄名と現在値を回収するハイブリッド抽出"""
        data = {}

        # 1. 銘柄名
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            name_raw = title_match.group(1)
            name = re.split(r'【|：|-', name_raw)[0].strip()
            data['name'] = name
        else:
            data['name'] = "N/A"

        # 2. 出来高 (JSON優先)
        vol_m = re.search(r'\"?volume\"?:\{[^{}]*?\"?value\"?:\s*\"?([\d\.\-\,]+)\"?', json_text)
        if vol_m:
            data['volume'] = vol_m.group(1).replace(',', '')

        # 3. 現在値 (JSON優先、特定構造を優先的に探索)
        # 投資信託の価格 (fundPrices) を優先
        it_p_match = re.search(r'\"?(fundPrices|mainFundPriceBoard)\"?:\{[^{}]*?\"?price\"?:\s*\"?([\d\.\,]+)\"?', json_text)
        if it_p_match:
            data['price'] = it_p_match.group(2).replace(',', '')
            # 投資信託の前日比
            it_c_match = re.search(r'\"?(fundPrices|mainFundPriceBoard)\"?:\{[^{}]*?\"?priceChange\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
            if it_c_match: data['change'] = it_c_match.group(2).replace(',', '')
            it_r_match = re.search(r'\"?(fundPrices|mainFundPriceBoard)\"?:\{[^{}]*?\"?priceChangeRate\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
            if it_r_match: data['change_percent'] = it_r_match.group(2)
            return data
            
        # 指数・先物の価格 (indexPrices / futurePrices)
        idx_p_match = re.search(r'\"?(indexPrices|futurePrices|mainDomesticIndexPriceBoard)\"?:\{[^{}]*?\"?price\"?:\s*\"?([\d\.\,]+)\"?', json_text)
        if idx_p_match:
            data['price'] = idx_p_match.group(2).replace(',', '')
            # 前日比 (priceChange または changePrice)
            idx_c_match = re.search(r'\"?(indexPrices|futurePrices|mainDomesticIndexPriceBoard)\"?:\{[^{}]*?\"?(priceChange|changePrice)\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
            if idx_c_match: data['change'] = idx_c_match.group(3).replace(',', '')
            
            # 前日比率 (priceChangeRate または changePriceRate)
            idx_r_match = re.search(r'\"?(indexPrices|futurePrices|mainDomesticIndexPriceBoard)\"?:\{[^{}]*?\"?(priceChangeRate|changePriceRate)\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
            if idx_r_match: data['change_percent'] = idx_r_match.group(3)
        elif not it_p_match:
            # フォールバック: previousPrice (本来は現在値が取れない場合の最終手段)
            idx_p_match_fallback = re.search(r'\"?(indexPrices|futurePrices)\"?:\{[^{}]*?\"?previousPrice\"?:\s*\"?([\d\.\,]+)\"?', json_text)
            if idx_p_match_fallback:
                data['price'] = idx_p_match_fallback.group(2).replace(',', '')

        # 一般的な価格オブジェクト (新・旧両方の構造に対応)
        price_match = re.search(r'\"?price\"?:\{[^{}]*?\"?value\"?:\s*\"?([\d\.\-\,]+)\"?', json_text)
        if not price_match:
            # 米国株等のフラットな構造
            price_match = re.search(r'\"?price\"?:\s*\"?([\d,]{4,}|[\d,]+\.[\d]+)\"?', json_text)
            if price_match:
                data['price'] = price_match.group(1).replace(',', '')
            else:
                # HTMLフォールバック (より具体的なクラスを狙う)
                # メインの価格ボードに含まれる数値を優先
                pb_area = re.search(r'class=\"[^\"]*PriceBoard.*?\">.*?([\d\.\,]{2,})<', html, re.S)
                if pb_area:
                    data['price'] = pb_area.group(1).replace(',', '')
                else:
                    candidates = re.findall(r'value[^\"]*\">([\d\.\,]+)<', html)
                    prices = [c.replace(',', '') for c in candidates if c != "0.00" and ('.' in c or len(c) >= 4)]
                    if prices:
                        data['price'] = prices[0]
                    else:
                        it_price_match = re.search(r'>([\d,]{4,})</span>', html)
                        data['price'] = it_price_match.group(1).replace(',', '') if it_price_match else "N/A"
        else:
            data['price'] = price_match.group(1).replace(',', '')

        return data

    def _parse_histories(self, json_text: str, current_price: float = None) -> List[Dict[str, Any]]:
        """株価履歴のみを抽出し、現在値に基づいた動的フィルタで異常値を除外する"""
        histories = []
        norm_text = json_text.replace('\\"', '"')
        
        # 1. 通常の株価構造 ({"date":"2024/01/01", "values": [...]})
        records = re.findall(r'\{"date":"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",\s*"values":\s*\[(.*?\}\s*\])', norm_text, re.S)
        
        for dt_str, val_block in records:
            vals = re.findall(r'"value":"([\d\.\-\,]*)"', val_block)
            if len(vals) < 6: continue
            try:
                cl_p_raw = vals[3].replace(',', '')
                vol_raw  = vals[4].replace(',', '')
                cl_p = float(cl_p_raw)
                if '.' in vol_raw and not vol_raw.endswith('.0'): continue
                vol = float(vol_raw)
                if cl_p <= 0: continue
                if current_price and current_price > 0:
                    if abs(cl_p - current_price) / current_price > 0.5: continue
                histories.append({"baseDatetime": dt_str, "closePrice": str(cl_p), "volume": str(int(vol))})
            except (ValueError, IndexError): continue

        # 2. 市場指標等の別構造 ({"date":"2024年1月1日","closePrice":"..."}) への対応
        if not histories:
            # 「2024年1月1日」という形式をパース
            index_records = re.findall(r'\{"date":"(\d{4})年(\d{1,2})月(\d{1,2})日".*?"closePrice":"([\d\.,\-]+)"\}', norm_text)
            for y, m, d, cp in index_records:
                try:
                    cl_p = float(cp.replace(',', ''))
                    if cl_p <= 0: continue
                    histories.append({
                        "baseDatetime": f"{y}/{m}/{d}",
                        "closePrice": str(cl_p),
                        "volume": "0"
                    })
                except ValueError: continue

        unique_histories = {}
        for h in histories:
            dt_s = h['baseDatetime'].replace('-', '/')
            try:
                dt_obj = datetime.strptime(dt_s, '%Y/%m/%d')
                if dt_obj not in unique_histories:
                    unique_histories[dt_obj] = h
            except ValueError: continue

        sorted_keys = sorted(unique_histories.keys(), reverse=True)
        return [unique_histories[k] for k in sorted_keys]
    @abstractmethod
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        pass

# --- 国内株式スクレイパー ---
class JPStockScraper(BaseScraper):
    def __init__(self, cache_size=128):
        super().__init__(cache_size)

    def _calculate_moving_average(self, histories: list, days: int, cur_p: float = None) -> Optional[float]:
        if not histories or len(histories) < days: return None
        try:
            # 現在値から大きく乖離しているゴミ（出来高等）を排除
            valid = [float(h["closePrice"]) for h in histories if not cur_p or (abs(float(h["closePrice"]) - cur_p) / cur_p < 2.0)]
            if len(valid) < days: return None
            return sum(valid[:days]) / days
        except: return None

    def _calculate_rci(self, histories: list, days: int, cur_p: float = None) -> Optional[float]:
        if not histories or len(histories) < days: return None
        try:
            prices = [float(h["closePrice"]) for h in histories if not cur_p or (abs(float(h["closePrice"]) - cur_p) / cur_p < 2.0)]
            if len(prices) < days: return None
            prices = prices[:days]
            prices.reverse()
            n = len(prices)
            x_ranks = list(range(1, n + 1))
            sorted_p = sorted(enumerate(prices), key=lambda x: x[1], reverse=True)
            y_ranks = [0] * n
            for r, (i, _) in enumerate(sorted_p, 1): y_ranks[i] = r
            d_sq = sum((x - y)**2 for x, y in zip(x_ranks, y_ranks))
            return (1 - (6 * d_sq) / (n * (n**2 - 1))) * 100
        except: return None

    def _calculate_rsi(self, histories: list, days: int, cur_p: float = None) -> Optional[float]:
        if not histories or len(histories) < days + 1: return None
        try:
            prices = [float(h["closePrice"]) for h in histories if not cur_p or (abs(float(h["closePrice"]) - cur_p) / cur_p < 2.0)]
            if len(prices) < days + 1: return None
            prices = prices[:days+1]
            prices.reverse()
            diffs = [prices[i+1] - prices[i] for i in range(days)]
            up = sum(d for d in diffs if d > 0)
            down = sum(-d for d in diffs if d < 0)
            return (up / (up + down)) * 100 if up + down > 0 else 50.0
        except: return None

    def _calculate_fibonacci(self, histories: list, cur_p: float = None) -> Optional[dict]:
        if not histories or len(histories) < 2: return None
        try:
            prices = [float(h["closePrice"]) for h in histories if not cur_p or (abs(float(h["closePrice"]) - cur_p) / cur_p < 2.0)]
            if not prices: return None
            hi, lo, cur = max(prices), min(prices), prices[0]
            if hi == lo: return None
            return {"high": hi, "low": lo, "current": cur, "retracement": (hi - cur) / (hi - lo) * 100, "period": len(prices)}
        except: return None

    def _get_quote_symbol(self, code: str) -> str:
        """銘柄コードに既にドット(市場識別子)が含まれる場合はそのまま、含まれない場合は .T を付与"""
        return code if '.' in code else f"{code}.T"

    @cachedmethod(lambda self: self.cache, key=lambda self, code, **kwargs: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        symbol = self._get_quote_symbol(code)
        logger.info(f"Fetching JP Stock (Hybrid): {symbol}")
        
        # 1. メインページから基本情報、現在値、財務指標を一括取得する
        url_q = f"https://finance.yahoo.co.jp/quote/{symbol}"
        res_q = self._make_request(url_q)
        if not res_q:
            return {
                "code": code, 
                "error": "メインページの取得に失敗しました",
                "error_details": self.last_error
            }
        json_q = self._extract_next_data(res_q.text)
        
        # 基本データの抽出 (名称、現在値、出来高、騰落)
        data = self._scavenge_common_data(res_q.text, json_q)
        
        # デフォルト値の設定
        data['bps'] = "N/A"
        data['payout_ratio'] = "N/A"
        data['payout_ratio_history'] = []

        # 財務指標の抽出 (境界制約 [^{}]*? を導入して他項目への飛び越しを防止)
        per_m = re.search(r'\"per\":\{[^{}]*?\"value\":\"([\d\.\-\,]+)\"', json_q)
        data['per'] = per_m.group(1).replace(',', '') if per_m and per_m.group(1) != "---" else "N/A"
        
        pbr_m = re.search(r'\"pbr\":\{[^{}]*?\"value\":\"([\d\.\-\,]+)\"', json_q)
        data['pbr'] = pbr_m.group(1).replace(',', '') if pbr_m and pbr_m.group(1) != "---" else "N/A"
        
        y_m = re.search(r'\"shareDividendYield\":\{[^{}]*?\"value\":\"([\d\.\-\,]+)\"', json_q)
        data['yield'] = y_m.group(1).replace(',', '') if y_m and y_m.group(1) != "---" else "N/A"
        
        change_m = re.search(r'\"priceChange\":\{[^{}]*?\"value\":\"([\+\-\d\.\,]+)\"', json_q)
        data['change'] = change_m.group(1).replace(',', '') if change_m else "N/A"
        rate_m = re.search(r'\"priceChangeRate\":\{[^{}]*?\"value\":\"([\+\-\d\.\,]+)\"', json_q)
        data['change_percent'] = rate_m.group(1) if rate_m else "N/A"

        # EPSの抽出
        eps_m = re.search(r'\"eps\":\{[^{}]*?\"value\":\"([\d\.\-\,]+)\"', json_q)
        data['eps'] = eps_m.group(1).replace(',', '') if eps_m and eps_m.group(1) != "---" else "N/A"

        # BPSの抽出
        bps_m = re.search(r'\"bps\":\{[^{}]*?\"value\":\"([\d\.\-\,]+)\"', json_q)
        data['bps'] = bps_m.group(1).replace(',', '') if bps_m and bps_m.group(1) != "---" else "N/A"

        # PERのリカバリ (現在株価 / EPS)
        if (data.get('per') == "N/A" or data.get('per') == "---") and data.get('eps') not in ["N/A", "---"]:
            try:
                p = float(data.get('price', 0))
                e = float(data.get('eps'))
                if p > 0 and e > 0:
                    calc_per = p / e
                    data['per'] = f"{calc_per:.2f}"
            except: pass

        # ROE (多層検索の強化: 負の値対応と実績ラベル優先)
        roe_label_m = re.search(r'\"name\":\"ROE\",.*?\"value\":\"([\d\.\-\,]+)\"', json_q)
        if roe_label_m and roe_label_m.group(1) != "---":
            data['roe'] = roe_label_m.group(1).replace(',', '')
        else:
            roe_m = re.search(r'\"roe\":\{[^{}]*?\"value\":\"([\d\.\-\,]+)\"', json_q)
            if roe_m and roe_m.group(1) != "---":
                data['roe'] = roe_m.group(1).replace(',', '')
            else:
                roe_list = re.findall(r'\"roe\":([\d\.\-]+)', json_q)
                roe_list = [r for r in roe_list if r != "$undefined"]
                data['roe'] = roe_list[-1] if roe_list else "N/A"

        dps_m = re.search(r'\"dps\":\{[^{}]*?\"value\":\"([\d\.\,\-]+)\"', json_q)
        dps_raw = dps_m.group(1) if dps_m else "N/A"
        data['annual_dividend'] = float(dps_raw.replace(',', '')) if dps_raw not in ["N/A", "---"] else 0.0

        ind_m = re.search(r'\"industryName\":\"(.*?)\"', json_q)
        data['industry'] = ind_m.group(1) if ind_m else "N/A"
        
        cap_m = re.search(r'\"totalPrice\":\{.*?\"value\":\"([\d,\.]+)\".*?\"suffix\":\"(.*?)\"', json_q)
        if cap_m:
            v_str, s = cap_m.group(1).replace(',', ''), cap_m.group(2)
            try:
                v = float(v_str)
                if "兆" in s: data['market_cap'] = str(int(v * 1_000_000_000_000))
                elif "億" in s: data['market_cap'] = str(int(v * 100_000_000))
                elif "百万" in s: data['market_cap'] = str(int(v * 1_000_000))
                else: data['market_cap'] = v_str.split('.')[0]
            except: data['market_cap'] = "N/A"
        else: data['market_cap'] = "N/A"
        
        month_m = re.search(r'\"dpsPeriod\":\"\d{4}-(\d{2})-\d{2}\"', json_q)
        if not month_m:
            month_m = re.search(r'\"settlementDate\":\"\d{4}/(\d{2})\"', json_q)
        if not month_m:
            date_m = re.search(r'\"date\":\"\d{4}(\d{2})\"', json_q)
            if date_m: month_m = date_m
        data['settlement_month'] = f"{int(month_m.group(1))}月" if month_m else "N/A"

        cur_p = 0.0
        try:
            p_val = data.get('price', 0)
            if isinstance(p_val, str): p_val = p_val.replace(',', '')
            cur_p = float(p_val) if p_val not in [None, "N/A", "--", "---", ""] else 0.0
        except: pass

        # 2. 履歴ページを取得し、現在値を基準にパース
        time.sleep(1.2)
        url_h = f"https://finance.yahoo.co.jp/quote/{symbol}/history"
        res_h = self._make_request(url_h)
        if not res_h:
            return {
                "code": code, 
                "error": "履歴の取得に失敗しました",
                "error_details": self.last_error
            }
        
        json_h = self._extract_next_data(res_h.text)
        scraped_histories = self._parse_histories(json_h if json_h else res_h.text, current_price=cur_p)
        for h in scraped_histories: h['date'] = h.get('baseDatetime', '').replace('/', '-')

        # 2. DBから過去データを取得してマージ
        from history_manager import get_historical_data_for_analysis
        db_histories = get_historical_data_for_analysis(code, limit=300)
        
        # マージロジック (日付をキーにして重複排除)
        combined_map = {h['date']: h for h in db_histories}
        for h in scraped_histories:
            combined_map[h['date']] = h # 通信データを優先
        
        # 新しい順にソート
        sorted_dates = sorted(combined_map.keys(), reverse=True)
        histories = [combined_map[d] for d in sorted_dates]

        # 3. 分析の実行 (1年分のデータがあれば200日線、52週高安が算出可能)
        # 移動平均 (25, 75, 200)
        data['ma25'] = self._calculate_moving_average(histories, 25, cur_p)
        data['ma75'] = self._calculate_moving_average(histories, 75, cur_p)
        data['ma200'] = self._calculate_moving_average(histories, 200, cur_p)
        
        # フィボナッチ（マルチウィンドウ）: 1年、半年、3ヶ月
        data['fibonacci_1y'] = self._calculate_fibonacci(histories, cur_p)
        data['fibonacci_6m'] = self._calculate_fibonacci(histories[:125], cur_p)
        data['fibonacci_3m'] = self._calculate_fibonacci(histories[:63], cur_p)
        
        # 後方互換性のため fibonacci キーも保持 (デフォルトは1年)
        data['fibonacci'] = data['fibonacci_1y']

        data['rci26'] = self._calculate_rci(histories, 26, cur_p)
        data['rsi14'] = self._calculate_rsi(histories, 14, cur_p)
        
        # 判定の信頼性 (200日分あれば最高、最低でも75日は欲しい)
        data['is_reliable'] = len(histories) >= 75
        data['history_count'] = len(histories)

        # 4. 配当履歴の抽出 (詳細ページ)
        div_history = {}
        time.sleep(1.2)
        url_div = f"https://finance.yahoo.co.jp/quote/{symbol}/dividend"
        res_div = self._make_request(url_div)
        if res_div:
            json_div = self._extract_next_data(res_div.text) or self._extract_legacy_data(res_div.text)
            if json_div:
                # 配当性向の抽出 (payoutRatioAndEps)
                payout_ratio_history = []
                payout_ratio_m = re.search(r'\"payoutRatioAndEps\":(\[.*?\])', json_div)
                if payout_ratio_m:
                    try:
                        payout_data = json.loads(payout_ratio_m.group(1))
                        if payout_data and len(payout_data) > 0:
                            val = payout_data[0].get('payoutRatioValue')
                            if val is not None:
                                data['payout_ratio'] = str(val)
                        payout_ratio_history = payout_data
                    except: pass
                data['payout_ratio_history'] = payout_ratio_history

                # 基準日ごとの年間合計値 (予想・修正実績・実績の優先順位で抽出)
                # 型: [{"settlementDate": "202409", "annualForecastValue": "20.0", ...}, ...]
                dps_matches_ext = re.findall(r'\"settlementDate\":\"(\d{4})\d{2}\"[^{}]*?\"(annualForecastValue|annualCorrectedActualValue|annualActualValue|annualActualDividend)\":\s*\"?([\d\.]+)\"?', json_div)
                for year, type_key, val in dps_matches_ext:
                    v = float(val)
                    if v < 100000:
                        # 予想(Forecast)を最優先、なければ既存を上書き
                        if year not in div_history or type_key == "annualForecastValue":
                            div_history[year] = v
        else:
            # 配当詳細の取得失敗は致命的ではないが、一応ログ
            logger.warning(f"Failed to fetch dividend detail for {code}: {self.last_error}")

        # メインページのJSONデータからの配当補足 (1回目で取得済みの json_q を再利用)
        dps_area = re.search(r'\"dps\":\{.*?\}', json_q)
        if dps_area:
            ctx = dps_area.group(0)
            m_latest = re.search(r'\"updateDate\":\"(\d{4})/\d{2}\".*?\"value\":\"([\d\.]+)\"', ctx)
            if m_latest:
                year, val = m_latest.group(1), float(m_latest.group(2))
                if year not in div_history or val > div_history[year]:
                    div_history[year] = val
        
        div_list_area = re.search(r'\"dividend\":\[.*?\]', json_q)
        if div_list_area:
            ctx = div_list_area.group(0)
            m_list = re.findall(r'\"date\":\"(\d{4})\d{2}\".*?\"(?:dividend|dps)\":\s*\"?([\d\.]+)\"?', ctx)
            for year, val in m_list:
                v = float(val)
                if v < 100000:
                    if year not in div_history or v > div_history[year]:
                        div_history[year] = v
                        
        data['dividend_history'] = div_history

        # 1株配当のリカバリ
        # 実用性重視のハイブリッド対応: 
        # 1. 表示利回り(yield)はメインページが未定なら "---" 等を維持し、スコアへの誤加点を防ぐ。
        # 2. 配当金額(annual_dividend)は、分析ページでのシミュレーション用に前期実績等からのリカバリを許可する。
        def is_numeric_value(s):
            try:
                float(str(s).replace(',', ''))
                return True
            except (ValueError, TypeError):
                return False

        is_explicitly_undefined = not is_numeric_value(dps_raw) and dps_raw not in [None, "N/A", ""]
        
        # リカバリ実行判定 (取得失敗(N/A)時、または金額が0だが履歴がある場合)
        # 昨年実績(current_year-1)も対象に含める
        if (dps_raw in ["N/A"] or data['annual_dividend'] == 0.0 or is_explicitly_undefined) and div_history:
            current_year = datetime.now().year
            # 当期(current) または 来期(current+1) または 前期(current-1) を対象とする
            valid_years = [str(current_year - 1), str(current_year), str(current_year + 1)]
            recovery_candidates = {y: v for y, v in div_history.items() if y in valid_years}
            
            if recovery_candidates:
                # 未来の予想があればそれを優先、なければ最新(実績含む)
                best_year = max(recovery_candidates.keys())
                data['annual_dividend'] = recovery_candidates[best_year]
                
                # 明示的に未定なのにリカバリした場合は「信頼性なし」フラグを立て、利回りは記号を維持する
                if is_explicitly_undefined:
                    data['yield'] = dps_raw # "---" などを維持
                    data['is_reliable'] = False
                    logger.info(f"Recovered annual_dividend for {code} as REFERENCE ONLY (Year: {best_year}) while yield remains '{dps_raw}'")
                else:
                    logger.info(f"Recovered annual_dividend for {code} from dividend_history: {data['annual_dividend']} (Year: {best_year})")
        elif is_explicitly_undefined:
             data['yield'] = dps_raw
             data['is_reliable'] = False

        # 利回りリカバリ
        # デグレ防止: 明示的な未定(---)の場合は、計算による数値上書きを行わない(表示は---のまま、金額のみリカバリ値を保持)
        if not is_explicitly_undefined and (data.get('yield') == "N/A" or data.get('yield') == "---") and data['annual_dividend'] > 0:
            try:
                p = float(data['price'])
                if p > 0:
                    calc_yield = (data['annual_dividend'] / p) * 100
                    data['yield'] = f"{calc_yield:.2f}"
            except: pass

        # 株式分割直後のトップページ会社予想DPS更新遅延に対する整合性補正 (#330)
        # トップページが分割前の旧DPS(例: 180円)のままで、詳細タブの dividend_history に分割後DPS(例: 90円)が先行反映されている場合
        if data['annual_dividend'] > 0 and div_history:
            current_year = datetime.now().year
            forward_years = [str(current_year), str(current_year + 1), str(current_year + 2)]
            future_candidates = {y: v for y, v in div_history.items() if y in forward_years and v > 0}
            if future_candidates:
                latest_future_year = max(future_candidates.keys())
                latest_hist_div = future_candidates[latest_future_year]
                if latest_hist_div > 0:
                    div_ratio = data['annual_dividend'] / latest_hist_div
                    # 一般的な株式分割比率 (1:2, 1:3, 1:4, 1:5, 1:10等) の範囲内にあるか判定 (乖離が1.6倍以上)
                    is_split_mismatch = any(
                        (0.8 * r <= div_ratio <= 1.2 * r) for r in [2.0, 3.0, 4.0, 5.0, 10.0]
                    )
                    if is_split_mismatch:
                        logger.info(
                            f"Detected unadjusted top-page DPS for {code} ({data['annual_dividend']} vs history {latest_hist_div}). "
                            f"Overriding annual_dividend with split-adjusted dividend from dividend_history (Year: {latest_future_year})."
                        )
                        data['annual_dividend'] = latest_hist_div
                        # 利回りも最新分割後株価で再計算・更新
                        try:
                            p = float(data['price'])
                            if p > 0:
                                calc_yield = (data['annual_dividend'] / p) * 100
                                data['yield'] = f"{calc_yield:.2f}"
                        except Exception:
                            pass

        data.update({
            "code": code,
            "moving_average_5": self._calculate_moving_average(histories, 5, cur_p),
            "moving_average_25": self._calculate_moving_average(histories, 25, cur_p),
            "moving_average_25_prev": self._calculate_moving_average(histories[1:], 25) if len(histories) > 25 else None,
            "moving_average_75": self._calculate_moving_average(histories, 75, cur_p),
            "moving_average_75_prev": self._calculate_moving_average(histories[1:], 75) if len(histories) > 75 else None,
            "moving_average_200": self._calculate_moving_average(histories, 200, cur_p),
            "moving_average_200_prev": self._calculate_moving_average(histories[1:], 200) if len(histories) > 200 else None,
            "rci_26": self._calculate_rci(histories, 26, cur_p),
            "rsi_14": self._calculate_rsi(histories, 14, cur_p),
            "rsi_14_prev": self._calculate_rsi(histories[1:], 14, cur_p) if len(histories) > 15 else None,
            "fibonacci": self._calculate_fibonacci(histories, cur_p),
            "asset_type": "jp_stock", "currency": "JPY"
        })
        return data

class InvestTrustScraper(BaseScraper):
    @staticmethod
    def _parse_and_format_net_assets(value_str: Optional[str], suffix: str = "百万円") -> Tuple[str, str]:
        """
        純資産総額の数値文字列と単位から、
        market_cap（円単位整数文字列）および net_assets（表示用文字列 例: 13.98兆円）を生成する。
        """
        if not value_str:
            return "N/A", "N/A"
        try:
            clean_val = str(value_str).replace(',', '').strip()
            v = float(clean_val)
            if v <= 0:
                return "N/A", "N/A"

            clean_suffix = (suffix or "").strip()
            if "兆" in clean_suffix:
                multiplier = 1_000_000_000_000
            elif "億" in clean_suffix:
                multiplier = 100_000_000
            elif "百万" in clean_suffix:
                multiplier = 1_000_000
            elif "万" in clean_suffix:
                multiplier = 10_000
            elif "円" in clean_suffix:
                multiplier = 1
            else:
                multiplier = 1_000_000  # デフォルトは百万円

            raw_value_yen = v * multiplier
            market_cap_str = str(int(raw_value_yen))

            if raw_value_yen >= 1_000_000_000_000:
                net_assets_str = f"{(raw_value_yen / 1_000_000_000_000):.2f}兆円"
            elif raw_value_yen >= 100_000_000:
                net_assets_str = f"{(raw_value_yen / 100_000_000):.2f}億円"
            else:
                net_assets_str = f"{(raw_value_yen / 1_000_000):.0f}百万円"

            return market_cap_str, net_assets_str
        except (ValueError, TypeError):
            return "N/A", "N/A"

    @staticmethod
    def _format_trust_fee(rate_str: Optional[str]) -> str:
        """
        信託報酬の数値文字列（例: '0.05775' または '0.05775%'）を正規化し、
        末尾に1つだけ '%' を持つフォーマットに整える。
        """
        if not rate_str:
            return "N/A"
        clean_str = str(rate_str).replace('%', '').strip()
        if not clean_str or clean_str in ['N/A', '---', '--', '-']:
            return "N/A"
        try:
            val = float(clean_str)
            if val < 0:
                return "N/A"
            return f"{clean_str}%"
        except (ValueError, TypeError):
            return "N/A"

    @cachedmethod(lambda self: self.cache, key=lambda self, code, **kwargs: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching Invest Trust: {code}")
        res = self._make_request(f"https://finance.yahoo.co.jp/quote/{code}")
        if not res:
            return {
                "code": code, 
                "error": "通信エラー",
                "error_details": self.last_error
            }
        
        json_text = self._extract_next_data(res.text)
        if not json_text:
            json_text = self._extract_legacy_data(res.text)
            
        data = self._scavenge_common_data(res.text, json_text)
        
        # 投資信託特有の前日比 (クォート柔軟対応)
        change_m = re.search(r'\"?changePrice\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
        data['change'] = change_m.group(1).replace(',', '') if change_m else "N/A"
        rate_m = re.search(r'\"?changePriceRate\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
        data['change_percent'] = rate_m.group(1) if rate_m else "N/A"

        # --- 純資産総額の3層フォールバック抽出 (#364) ---
        na_val_str = None
        na_suffix_str = "百万円"

        # Tier 1: 新形式 JSON (Next.js RSC: "name":"純資産残高" ... "primary":{...})
        if json_text:
            rsc_na_block = re.search(r'\"name\":\"純資産残高\"[^{}]*?\"primary\":\{([^}]+)\}', json_text)
            if rsc_na_block:
                block_content = rsc_na_block.group(1)
                v_m = re.search(r'\"value\":\"([\d\.\,]+)\"', block_content)
                s_m = re.search(r'\"suffix\":\"([^\"]*)\"', block_content)
                if v_m:
                    na_val_str = v_m.group(1)
                    if s_m and s_m.group(1):
                        na_suffix_str = s_m.group(1)

        # Tier 2: 旧形式 JSON (Legacy: mainFundDetail.items.netAssetBalance.price)
        if not na_val_str and json_text:
            legacy_na_m = re.search(r'\"?netAssetBalance\"?:\s*\{[^{}]*?\"?price\"?:\s*\"?([\d\.\,]+)\"?', json_text)
            if legacy_na_m:
                na_val_str = legacy_na_m.group(1)
                na_suffix_str = "百万円"

        # Tier 3: HTML 直接抽出フォールバック (Next.js レンダリング結果)
        if not na_val_str and res.text:
            try:
                soup = BeautifulSoup(res.text, 'html.parser')
                for label_el in soup.find_all(string=re.compile(r'純資産残高')):
                    dt_candidate = label_el.find_parent('dt')
                    if dt_candidate:
                        dd_el = dt_candidate.find_next_sibling('dd')
                        if dd_el:
                            raw_text = dd_el.get_text(strip=True)
                            cleaned_text = re.sub(r'^[\d,]+位\s*', '', raw_text)
                            m = re.search(r'([\d\.\,]+)\s*(兆円|億円|百万円|万円|円)?', cleaned_text)
                            if m:
                                na_val_str = m.group(1)
                                if m.group(2):
                                    na_suffix_str = m.group(2)
                                break
            except Exception as e:
                logger.warning(f"HTML fallback failed for net assets {code}: {e}")

        market_cap, net_assets = self._parse_and_format_net_assets(na_val_str, na_suffix_str)
        data['market_cap'] = market_cap
        data['net_assets'] = net_assets

        # --- 信託報酬の3層フォールバック抽出 (#364) ---
        tf_val_str = None

        # Tier 1: 新形式 JSON (Next.js RSC: "name":"信託報酬" ... "primary":{...})
        if json_text:
            rsc_tf_block = re.search(r'\"name\":\"信託報酬\"[^{}]*?\"primary\":\{([^}]+)\}', json_text)
            if rsc_tf_block:
                block_content = rsc_tf_block.group(1)
                v_m = re.search(r'\"value\":\"([\d\.\,]+)\"', block_content)
                if v_m:
                    tf_val_str = v_m.group(1)

        # Tier 2: 旧形式 JSON (Legacy: mainFundDetail.items.payRateTotal.rate)
        if not tf_val_str and json_text:
            legacy_tf_m = re.search(r'\"?payRateTotal\"?:\s*\{[^{}]*?\"?rate\"?:\s*\"?([\d\.\,]+)\"?', json_text)
            if legacy_tf_m:
                tf_val_str = legacy_tf_m.group(1)

        # Tier 3: HTML 直接抽出フォールバック (Next.js レンダリング結果)
        if not tf_val_str and res.text:
            try:
                soup = BeautifulSoup(res.text, 'html.parser')
                for label_el in soup.find_all(string=re.compile(r'信託報酬')):
                    dt_candidate = label_el.find_parent('dt')
                    if dt_candidate:
                        dd_el = dt_candidate.find_next_sibling('dd')
                        if dd_el:
                            raw_text = dd_el.get_text(strip=True)
                            cleaned_text = re.sub(r'^[\d,]+位\s*', '', raw_text)
                            m = re.search(r'([\d\.\,]+%?)', cleaned_text)
                            if m:
                                tf_val_str = m.group(1)
                                break
            except Exception as e:
                logger.warning(f"HTML fallback failed for trust fee {code}: {e}")

        data['trust_fee'] = self._format_trust_fee(tf_val_str)
        
        data.update({"code": code, "asset_type": "investment_trust", "currency": "JPY"})
        return data

class USStockScraper(BaseScraper):
    @cachedmethod(lambda self: self.cache, key=lambda self, code, **kwargs: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching US Stock: {code}")
        res = self._make_request(f"https://finance.yahoo.co.jp/quote/{code}")
        if not res:
            return {
                "code": code, 
                "error": "通信エラー",
                "error_details": self.last_error
            }
        
        json_text = self._extract_next_data(res.text)
        if not json_text:
            json_text = self._extract_legacy_data(res.text)

        data = self._scavenge_common_data(res.text, json_text)
        
        # 米国株特有の構造 (mainUsStocksPriceBoard) からの抽出
        # 市場 (NASDAQ/NYSE等)
        m_label = re.search(r'\"?mainUsStocksPriceBoard\"?:\{[^{}]*?\"?label\"?:\s*\"?([^\"]+)\"?', json_text)
        data['market'] = m_label.group(1) if m_label else "N/A"

        # 現在値 (JSON優先)
        m_price = re.search(r'\"?mainUsStocksPriceBoard\"?:\{[^{}]*?\"?price\"?:\s*\"?([\d\.\,]+)\"?', json_text)
        if m_price:
            data['price'] = m_price.group(1).replace(',', '')

        # 前日比
        m_change = re.search(r'\"?mainUsStocksPriceBoard\"?:\{[^{}]*?\"?priceChange\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
        if m_change:
            data['change'] = m_change.group(1).replace(',', '')
        
        m_rate = re.search(r'\"?mainUsStocksPriceBoard\"?:\{[^{}]*?\"?priceChangeRate\"?:\s*\"?([\+\-\d\.\,]+)\"?', json_text)
        if m_rate:
            data['change_percent'] = m_rate.group(1)

        # 財務指標 (mainUsStocksReferenceIndex)
        per_m = re.search(r'\"?per\"?:\{[^{}]*?\"?value\"?:\s*\"?([\d\.\-\,]+)\"?', json_text)
        data['per'] = per_m.group(1).replace(',', '') if per_m and per_m.group(1) != "---" else "N/A"
        
        y_m = re.search(r'\"?(shareDividendYield|dividendYield|dividend)\"?:\{[^{}]*?\"?value\"?:\s*\"?([\d\.\-\,]+)\"?', json_text)
        if not y_m:
            y_m = re.search(r'\"?(dividendYield|yield)\"?:\s*\"?([\d\.\,]+)\"?', json_text)
            data['yield'] = y_m.group(2) if y_m else "N/A"
        else:
            data['yield'] = y_m.group(2).replace(',', '') if y_m.group(2) != "---" else "N/A"

        # 時価総額 (mainUsStocksReferenceIndex.totalPrice)
        # 米国株はドル建てなので円換算する
        cap_m = re.search(r'\"?totalPrice\"?:\{[^{}]*?\"?value\"?:\s*\"?([\d\.\,]+)\"?,\s*\"?move\"?:[^{}]*?\"?suffix\"?:\s*\"?([^\"]+)\"?', json_text)
        if cap_m:
            v_str, s = cap_m.group(1).replace(',', ''), cap_m.group(2)
            try:
                v = float(v_str)
                usd_cap = v
                if "千ドル" in s: usd_cap = v * 1000
                elif "百万ドル" in s: usd_cap = v * 1_000_000
                elif "億ドル" in s: usd_cap = v * 100_000_000
                
                # 為替換算
                rate = get_exchange_rate()
                if rate:
                    data['market_cap'] = str(int(usd_cap * rate))
                else:
                    data['market_cap'] = "N/A"
            except: data['market_cap'] = "N/A"
        else:
            data['market_cap'] = "N/A"

        # 決算月 (パース精度の向上)
        settlement_month = "N/A"
        # 1. eps（一株利益）の更新日 (YYYY/MM) からの抽出を試みる
        eps_update_m = re.search(r'\"?eps\"?:\{[^{}]*?\"?updateDate\"?:\s*\"?(\d{4})/(\d{2})\"?', json_text)
        if eps_update_m:
            settlement_month = f"{int(eps_update_m.group(2))}月"
        else:
            # 2. bps（一株純資産）の更新日からの抽出を試みる
            bps_update_m = re.search(r'\"?bps\"?:\{[^{}]*?\"?updateDate\"?:\s*\"?(\d{4})/(\d{2})\"?', json_text)
            if bps_update_m:
                settlement_month = f"{int(bps_update_m.group(2))}月"
            else:
                # 3. 従来のフォールバック
                date_m = re.search(r'\"?date\"?:\s*\"?(\d{4})(\d{2})\"?', json_text)
                if date_m:
                    settlement_month = f"{int(date_m.group(2))}月"
        
        data['settlement_month'] = settlement_month

        # 初期値設定
        data.update({
            "code": code, 
            "asset_type": "us_stock", 
            "currency": "USD",
            "payout_ratio": "N/A",
            "payout_ratio_history": [],
            "annual_dividend": 0.0
        })

        # yfinance による配当情報等の補完
        try:
            ticker = yf.Ticker(code)
            info = ticker.info
            if info:
                # 配当性向の補完
                p_ratio = info.get("payoutRatio")
                if p_ratio is not None:
                    # yfinanceのpayoutRatioは小数（例: 0.6478）なので100倍して%にする
                    data["payout_ratio"] = f"{float(p_ratio) * 100:.2f}"
                
                # 配当利回りの補完（すでに % 表記）
                div_yield = info.get("dividendYield")
                if div_yield is not None:
                    data["yield"] = f"{float(div_yield):.2f}"
                
                # 年間配当金額の補完
                div_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate")
                if div_rate is not None:
                    data["annual_dividend"] = float(div_rate)
                
                # 決算月のフォールバック補完 (yfinanceのlastFiscalYearEndを利用)
                if data.get('settlement_month') == "N/A" or not data.get('settlement_month'):
                    last_fye = info.get("lastFiscalYearEnd")
                    if last_fye:
                        try:
                            # タイムスタンプから決算月を取得
                            dt = datetime.fromtimestamp(last_fye)
                            data['settlement_month'] = f"{dt.month}月"
                        except: pass
        except Exception as e:
            logger.warning(f"Failed to fetch yfinance data for {code}: {e}")

        return data

class IndexScraper(BaseScraper):
    @cachedmethod(lambda self: self.cache, key=lambda self, code, **kwargs: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching Market Index: {code}")
        res = self._make_request(f"https://finance.yahoo.co.jp/quote/{code}")
        if not res:
            return {
                "code": code, 
                "error": "通信エラー",
                "error_details": self.last_error
            }
        
        json_text = self._extract_next_data(res.text)
        if not json_text:
            json_text = self._extract_legacy_data(res.text)
            
        data = self._scavenge_common_data(res.text, json_text)
        data.update({"code": code, "asset_type": "market_index", "currency": "JPY"})
        return data

@cached(TTLCache(maxsize=10, ttl=CACHE_TTL))
def get_exchange_rate_detail(pair: str = 'USDJPY=X') -> Dict[str, Any]:
    """
    為替レートの現在値・前日比・高値/安値・52週高値/安値・ピーク差等の詳細を取得する。
    """
    result = {
        "pair": pair,
        "name": "ドル円" if "USDJPY" in pair else pair,
        "price": None,
        "change": None,
        "change_percent": None,
        "is_up": True,
        "high": None,
        "low": None,
        "high_52w": None,
        "low_52w": None,
        "peak_diff_percent": None
    }
    try:
        scraper = get_scraper('market_index')
        data = scraper.fetch_data(pair)
        if data and "error" not in data:
            price_str = data.get("price")
            if price_str:
                result["price"] = str(price_str)
                result["change"] = data.get("change", "0.0")
                result["change_percent"] = data.get("change_percent", "0.0%")
                try:
                    chg_val = float(str(result["change"]).replace('+', '').replace(',', ''))
                    result["is_up"] = chg_val >= 0
                except (ValueError, TypeError):
                    result["is_up"] = not str(result["change_percent"]).startswith('-')

        # Yahoo! Finance HTML / Next.js JSON or yfinance fallback for high/low/52w
        try:
            res = requests.get(f"https://finance.yahoo.co.jp/quote/{pair}", headers=DEFAULT_HEADERS, timeout=5)
            if res.status_code == 200:
                html = res.text
                if not result["price"]:
                    m_price = re.search(r'\"counterCurrencyPrice\":([\d\.]+)', html) or re.search(r'\"price\":([\d\.]+)', html)
                    if m_price:
                        result["price"] = m_price.group(1)

                m_high = re.search(r'\"highPrice\":\s*\"?([\d\.\,]+)\"?', html) or re.search(r'\"high\":\s*\"?([\d\.\,]+)\"?', html)
                m_low = re.search(r'\"lowPrice\":\s*\"?([\d\.\,]+)\"?', html) or re.search(r'\"low\":\s*\"?([\d\.\,]+)\"?', html)
                if m_high: result["high"] = m_high.group(1).replace(',', '')
                if m_low: result["low"] = m_low.group(1).replace(',', '')

                m_52high = re.search(r'\"highPrice52w\":\s*\"?([\d\.\,]+)\"?', html) or re.search(r'\"yearHigh\":\s*\"?([\d\.\,]+)\"?', html)
                m_52low = re.search(r'\"lowPrice52w\":\s*\"?([\d\.\,]+)\"?', html) or re.search(r'\"yearLow\":\s*\"?([\d\.\,]+)\"?', html)
                if m_52high: result["high_52w"] = m_52high.group(1).replace(',', '')
                if m_52low: result["low_52w"] = m_52low.group(1).replace(',', '')
        except Exception as ex:
            logger.warning(f"HTML scraping for {pair} details failed: {ex}")

        # yfinance fallback for 52-week range if missing
        if not result["high_52w"] or not result["low_52w"]:
            try:
                yf_pair = "JPY=X" if pair == "USDJPY=X" else pair
                ticker = yf.Ticker(yf_pair)
                info = ticker.fast_info
                if hasattr(info, "year_high") and info.year_high:
                    result["high_52w"] = f"{float(info.year_high):.2f}"
                if hasattr(info, "year_low") and info.year_low:
                    result["low_52w"] = f"{float(info.year_low):.2f}"
                if hasattr(info, "day_high") and info.day_high and not result["high"]:
                    result["high"] = f"{float(info.day_high):.2f}"
                if hasattr(info, "day_low") and info.day_low and not result["low"]:
                    result["low"] = f"{float(info.day_low):.2f}"
                if hasattr(info, "last_price") and info.last_price and not result["price"]:
                    result["price"] = f"{float(info.last_price):.2f}"
            except Exception as ex:
                logger.warning(f"yfinance fallback for {pair} details failed: {ex}")

        if result["price"] and result["high_52w"]:
            try:
                curr_p = float(result["price"])
                high_52w = float(result["high_52w"])
                if high_52w > 0:
                    diff_pct = ((curr_p - high_52w) / high_52w) * 100.0
                    result["peak_diff_percent"] = f"{diff_pct:+.1f}%"
            except (ValueError, TypeError, ZeroDivisionError):
                result["peak_diff_percent"] = None
    except Exception as e:
        logger.error(f"Error in get_exchange_rate_detail for {pair}: {e}")

    return result

@cached(TTLCache(maxsize=10, ttl=CACHE_TTL))
def get_exchange_rate(pair: str = 'USDJPY=X') -> Optional[float]:
    detail = get_exchange_rate_detail(pair)
    if detail and detail.get("price"):
        try:
            return float(detail["price"])
        except (ValueError, TypeError):
            pass
    return None

_market_news_cache: Dict[str, Any] = {
    "timestamp": 0.0,
    "items": []
}
MARKET_NEWS_TTL = 1800  # 30分

def fetch_market_news_headlines(limit: int = 12, force: bool = False) -> List[Dict[str, str]]:
    """
    日経平均・TOPIX・為替（ドル円）等の変動要因を把握するため、
    公開RSS（Google News 市況/為替検索、Yahoo!ニュース経済）から最新ヘッドラインを収集する (#349)。
    - force=False の場合は30分間のメモリキャッシュを返却。
    - 通信エラー・不正XML発生時も例外を送出せず安全に空リストまたは取得済み分を返却。
    - URLスキーム（http:// または https://）を検証し XSS リスクを排除。
    """
    import html as html_lib
    import xml.etree.ElementTree as ET

    now = time.time()
    if not force and _market_news_cache["items"] and (now - _market_news_cache["timestamp"]) < MARKET_NEWS_TTL:
        return _market_news_cache["items"][:limit]

    feeds = [
        {
            "category": "株式市況",
            "url": "https://news.google.com/rss/search?q=%E6%97%A5%E7%B5%8C%E5%B9%B3%E5%9D%87+OR+TOPIX+OR+%E6%9D%B1%E4%BA%AC%E6%A0%AA%E5%BC%8F%E5%B8%82%E5%A0%B4+when:2d&hl=ja&gl=JP&ceid=JP:ja",
            "max_per_feed": 6
        },
        {
            "category": "為替・ドル円",
            "url": "https://news.google.com/rss/search?q=%E3%83%89%E3%83%AB%E5%86%86+OR+%E5%A4%96%E5%9B%BD%E7%82%BA%E6%9B%BF%E5%B8%82%E5%A0%B4+OR+%E5%86%86%E7%9B%B8%E5%A0%B4+when:2d&hl=ja&gl=JP&ceid=JP:ja",
            "max_per_feed": 5
        },
        {
            "category": "経済・市況",
            "url": "https://news.yahoo.co.jp/rss/categories/business.xml",
            "max_per_feed": 4
        }
    ]

    collected: List[Dict[str, str]] = []
    seen_titles = set()

    for feed in feeds:
        try:
            resp = requests.get(feed["url"], headers=DEFAULT_HEADERS, timeout=5.0)
            if resp.status_code != 200 or not resp.content:
                continue
            root = ET.fromstring(resp.content)
            count = 0
            for item in root.findall(".//item"):
                if count >= feed["max_per_feed"]:
                    break
                raw_title = (item.findtext("title") or "").strip()
                raw_link = (item.findtext("link") or "").strip()
                raw_pub = (item.findtext("pubDate") or "").strip()
                raw_source = (item.findtext("source") or "").strip()

                if not raw_title or not raw_link:
                    continue

                # XSS防止: http:// または https:// で始まるURLのみ許可
                if not (raw_link.startswith("http://") or raw_link.startswith("https://")):
                    continue

                clean_title = html_lib.unescape(raw_title)
                source_name = html_lib.unescape(raw_source) if raw_source else ""

                # Google News 形式 ("タイトル - メディア名") からメディア名を分離
                if " - " in clean_title:
                    parts = clean_title.rsplit(" - ", 1)
                    if len(parts) == 2 and len(parts[1]) <= 30:
                        clean_title = parts[0].strip()
                        if not source_name:
                            source_name = parts[1].strip()

                if not source_name:
                    source_name = feed["category"]

                # 重複タイトルの排除（先頭25文字でも類似判定）
                title_key = clean_title[:25]
                if clean_title in seen_titles or title_key in seen_titles:
                    continue
                seen_titles.add(clean_title)
                seen_titles.add(title_key)

                collected.append({
                    "title": clean_title,
                    "url": raw_link,
                    "link": raw_link,
                    "source": source_name,
                    "category": feed["category"],
                    "published": raw_pub,
                    "pub_date": raw_pub
                })
                count += 1
        except Exception as e:
            logger.warning(f"Failed to fetch or parse RSS feed ({feed['category']}): {e}")
            continue

    if collected:
        _market_news_cache["timestamp"] = now
        _market_news_cache["items"] = collected

    return collected[:limit]


_scraper_instances = {}
def get_scraper(asset_type: str) -> BaseScraper:
    if asset_type not in _scraper_instances:
        if asset_type == 'jp_stock': _scraper_instances[asset_type] = JPStockScraper()
        elif asset_type == 'investment_trust': _scraper_instances[asset_type] = InvestTrustScraper()
        elif asset_type == 'us_stock': _scraper_instances[asset_type] = USStockScraper()
        elif asset_type == 'market_index': _scraper_instances[asset_type] = IndexScraper()
    return _scraper_instances[asset_type]

if __name__ == '__main__':
    s = get_scraper('jp_stock')
    print(json.dumps(s.fetch_data("7203"), indent=2, ensure_ascii=False))
