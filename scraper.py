import requests
from bs4 import BeautifulSoup
import json
import re
import time
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from cachetools import cachedmethod, TTLCache, cached

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

    @cachedmethod(lambda self: self.cache, key=lambda self, code, **kwargs: code)
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching JP Stock (Hybrid): {code}.T")
        
        # 1. メインページから基本情報、現在値、財務指標を一括取得する
        url_q = f"https://finance.yahoo.co.jp/quote/{code}.T"
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
        url_h = f"https://finance.yahoo.co.jp/quote/{code}.T/history"
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
        url_div = f"https://finance.yahoo.co.jp/quote/{code}.T/dividend"
        res_div = self._make_request(url_div)
        if res_div:
            json_div = self._extract_next_data(res_div.text) or self._extract_legacy_data(res_div.text)
            if json_div:
                # 基準日ごとの年間合計値 (予想・修正実績・実績の優先順位で抽出)
                # 型: [{"settlementDate": "202409", "annualForecastValue": "20.0", ...}, ...]
                dps_matches_ext = re.findall(r'\"settlementDate\":\"(\d{4})\d{2}\"[^{}]*?\"(annualForecastValue|annualCorrectedActualValue|annualActualValue|annualActualDividend)\":\s*([\d\.]+)', json_div)
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
            m_list = re.findall(r'\"date\":\"(\d{4})\d{2}\".*?\"(?:dividend|dps)\":\s*([\d\.]+)', ctx)
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

        # 純資産総額 (mainFundDetail.items.netAssetBalance.price)
        na_m = re.search(r'\"?netAssetBalance\"?:\{[^{}]*?\"?price\"?:\s*\"?([\d\.\,]+)\"?', json_text)
        if na_m:
            try:
                # 百万円単位で取得されることが多い
                v = float(na_m.group(1).replace(',', ''))
                raw_value = v * 1_000_000
                data['market_cap'] = str(int(raw_value))
                # フロントエンド互換用
                if v >= 1000000: # 1兆円以上 (1,000,000百万)
                    data['net_assets'] = f"{(v/1000000):.2f}兆円"
                elif v >= 100: # 1億円以上 (100百万)
                    data['net_assets'] = f"{(v/100):.2f}億円"
                else:
                    data['net_assets'] = f"{v:.0f}百万円"
            except: 
                data['market_cap'] = "N/A"
                data['net_assets'] = "N/A"
        else:
            data['market_cap'] = "N/A"
            data['net_assets'] = "N/A"

        # 信託報酬 (mainFundDetail.items.payRateTotal.rate)
        tf_m = re.search(r'\"?payRateTotal\"?:\{[^{}]*?\"?rate\"?:\s*\"?([\d\.\,]+)\"?', json_text)
        if tf_m:
            data['trust_fee'] = f"{tf_m.group(1)}%"
        else:
            data['trust_fee'] = "N/A"
        
        data.update({"code": code, "asset_type": "investment_trust", "currency": "JPY"})
        return data

class USStockScraper(BaseScraper):
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

        # 決算月 (推測)
        month_m = re.search(r'\"?updateDate\"?:\s*\"?(\d{2})/', json_text)
        if not month_m:
            month_m = re.search(r'\"?date\"?:\s*\"?(\d{4})(\d{2})\"?', json_text)
            data['settlement_month'] = f"{int(month_m.group(2))}月" if month_m else "N/A"
        else:
            data['settlement_month'] = f"{int(month_m.group(1))}月"

        data.update({"code": code, "asset_type": "us_stock", "currency": "USD"})
        return data

class IndexScraper(BaseScraper):
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
def get_exchange_rate(pair: str = 'USDJPY=X') -> Optional[float]:
    res = requests.get(f"https://finance.yahoo.co.jp/quote/{pair}", headers=DEFAULT_HEADERS)
    m = re.search(r'\"counterCurrencyPrice\":([\d\.]+)', res.text)
    return float(m.group(1)) if m else None

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
