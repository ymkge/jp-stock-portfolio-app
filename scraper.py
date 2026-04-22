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
}

# --- 共通ベースクラス ---
class BaseScraper(ABC):
    """
    スクレイパークラスのベースとなる抽象クラス。
    Next.js形式のデータ抽出と共通のリクエスト処理を提供する。
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
            except requests.exceptions.RequestException as e:
                status_code = e.response.status_code if e.response is not None else "N/A"
                self.last_error = {"status_code": status_code, "url": url, "type": type(e).__name__}
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
        return None

    def is_cached(self, code: str) -> bool:
        """指定されたコードのデータがキャッシュに存在するか確認する"""
        return code in self.cache

    def _extract_next_data(self, html: str) -> str:
        """Next.jsのストリーミングデータ(self.__next_f.push)を外科的に抽出・結合する"""
        chunks = []
        for match in re.finditer(r'self\.__next_f\.push\(\[\d+,"(.*?)"\]\)', html):
            chunk = match.group(1)
            chunk = chunk.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n')
            chunks.append(chunk)
        return "".join(chunks)

    def _scavenge_common_data(self, html: str, json_text: str) -> Dict[str, Any]:
        """JSONとHTMLの両方から銘柄名と現在値を回収するハイブリッド抽出"""
        data = {}

        # 1. 銘柄名 (HTMLのtitleタグから)
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            name_raw = title_match.group(1)
            # 区切り文字（【, ：, -）で分割。IPO銘柄や投信に対応。
            name = re.split(r'【|：|-', name_raw)[0].strip()
            data['name'] = name
        else:
            data['name'] = "N/A"

        # 2. 現在値
        # JSON優先 ( \"price\":{\"value\":\"3,191\"} )
        price_match = re.search(r'\"price\":\{\"value\":\"([\d,\.]+)\"\}', json_text)
        if price_match:
            data['price'] = price_match.group(1).replace(',', '')
        else:
            # HTMLフォールバック: _StyledNumber 系のクラスを優先
            candidates = re.findall(r'value[^\"]*\">([\d,\.]+)<', html)
            prices = [c.replace(',', '') for c in candidates if c != "0.00" and ('.' in c or len(c) >= 4)]

            if prices:
                data['price'] = prices[0]
            else:
                # 投信等の最終手段: HTML全体の <span> 内にある4桁以上の数値を狙う
                it_price_match = re.search(r'>([\d,]{4,})</span>', html)
                data['price'] = it_price_match.group(1).replace(',', '') if it_price_match else "N/A"

        return data

    def _parse_histories(self, json_text: str) -> List[Dict[str, Any]]:
        """JSONテキストの正しい階層(histories)からのみ時系列データを回収する"""
        histories = []
        start_idx = json_text.find('"histories":[')
        if start_idx == -1: return []
        search_area = json_text[start_idx:start_idx + 100000]
        records = re.findall(r'\{\s*\"date\"\s*:\s*\"(\d{4}/\d{1,2}/\d{1,2})\"\s*,\s*\"values\"\s*:\s*\[(.*?\])\s*\}', search_area, re.S)
        for dt, val_block in records:
            vals = re.findall(r'\"value\"\s*:\s*\"([\d,\.]+)\"', val_block)
            if len(vals) >= 4:
                histories.append({"baseDatetime": dt, "closePrice": vals[3].replace(',', '')})
        unique_histories = {}
        for h in histories:
            if h['baseDatetime'] not in unique_histories:
                unique_histories[h['baseDatetime']] = h
        return sorted(unique_histories.values(), key=lambda x: x['baseDatetime'], reverse=True)

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
        logger.info(f"Fetching JP Stock: {code}.T")
        url_h = f"https://finance.yahoo.co.jp/quote/{code}.T/history"
        logger.info(f"Accessing History: {url_h}")
        res_h = self._make_request(url_h)
        if not res_h: return {"code": code, "error": "通信エラー"}

        json_h = self._extract_next_data(res_h.text)
        data = self._scavenge_common_data(res_h.text, json_h)
        histories = self._parse_histories(json_h)

        logger.info(f"Fetching History Page 2 for {code}.T")
        time.sleep(0.5)
        url_p2 = f"{url_h}?page=2&_data=app%2Fpc%2F%5Btype%5D%2Fquote%2F%5Bcode%5D%2Fhistory%2Fpage"
        res_p2 = self._make_request(url_p2)
        if res_p2: histories.extend(self._parse_histories(res_p2.text))

        logger.info(f"Complementing indicators from Main Page: {code}.T")
        time.sleep(0.5)
        url_q = f"https://finance.yahoo.co.jp/quote/{code}.T"
        res_q = self._make_request(url_q)

        json_q = self._extract_next_data(res_q.text)
        
        # 基本指標
        per_m = re.search(r'\"per\":\{.*?\"value\":\"([\d,\.]+)\"', json_q)
        data['per'] = per_m.group(1).replace(',', '') if per_m and per_m.group(1) != "---" else "N/A"
        pbr_m = re.search(r'\"pbr\":\{.*?\"value\":\"([\d,\.]+)\"', json_q)
        data['pbr'] = pbr_m.group(1).replace(',', '') if pbr_m and pbr_m.group(1) != "---" else "N/A"
        y_m = re.search(r'\"shareDividendYield\":\{.*?\"value\":\"([\d,\.]+)\"', json_q)
        data['yield'] = y_m.group(1).replace(',', '') if y_m and y_m.group(1) != "---" else "N/A"
        
        # 前日比・騰落率 (国内株追加)
        change_m = re.search(r'\"priceChange\":\{.*?\"value\":\"([\+\-\d,\.]+)\"', json_q)
        data['change'] = change_m.group(1).replace(',', '') if change_m else "N/A"
        rate_m = re.search(r'\"priceChangeRate\":\{.*?\"value\":\"([\+\-\d,\.]+)\"', json_q)
        data['change_percent'] = rate_m.group(1) if rate_m else "N/A"

        # ROE (多層検索)
        roe_m = re.search(r'\"roe\":\{.*?\"value\":\"([\d,\.]+)\"', json_q)
        if roe_m:
            data['roe'] = roe_m.group(1).replace(',', '')
        else:
            # 業績セクションから最新のROEを探す
            roe_list = re.findall(r'\"roe\":([\d\.]+)', json_q)
            data['roe'] = roe_list[-1] if roe_list else "N/A"

        # 1株配当 (dps)
        dps_m = re.search(r'\"dps\":\{.*?\"value\":\"([\d,\.]+)\"', json_q)
        data['annual_dividend'] = float(dps_m.group(1).replace(',', '')) if dps_m and dps_m.group(1) != "---" else 0.0

        # 配当履歴 (業績セクションから配当実績を抽出)
        # {"date":"202303","amount":...} のような構造から配当額を抜く
        div_history = {}
        div_matches = re.findall(r'\"date\":\"(\d{4})03\".*?\"dividend\":([\d\.]+)', json_q)
        for year, val in div_matches:
            div_history[year] = float(val)
        data['dividend_history'] = div_history

        # 配当利回りのリカバリ (N/Aの場合、予想配当から逆算)
        if data.get('yield') == "N/A" and data['annual_dividend'] > 0:
            try:
                p = float(data['price'])
                if p > 0:
                    calc_yield = (data['annual_dividend'] / p) * 100
                    data['yield'] = f"{calc_yield:.2f}"
            except: pass

        ind_m = re.search(r'\"industryName\":\"(.*?)\"', json_q)
        data['industry'] = ind_m.group(1) if ind_m else "N/A"
        
        # Market Cap (時価総額 - 百万円対応)
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
        
        # 決算月 (多層検索)
        month_m = re.search(r'\"dpsPeriod\":\"\d{4}-(\d{2})-\d{2}\"', json_q)
        if not month_m:
            month_m = re.search(r'\"settlementDate\":\"\d{4}/(\d{2})\"', json_q)
        if not month_m:
            # 業績データの最新日付から推測
            date_m = re.search(r'\"date\":\"\d{4}(\d{2})\"', json_q)
            if date_m: month_m = date_m
            
        data['settlement_month'] = f"{int(month_m.group(1))}月" if month_m else "N/A"

        cp = None
        try: cp = float(data['price'])
        except: pass

        data.update({
            "code": code,
            "moving_average_5": self._calculate_moving_average(histories, 5, cp),
            "moving_average_25": self._calculate_moving_average(histories, 25, cp),
            "moving_average_75": self._calculate_moving_average(histories, 75, cp),
            "rci_26": self._calculate_rci(histories, 26, cp),
            "rsi_14": self._calculate_rsi(histories, 14, cp),
            "rsi_14_prev": self._calculate_rsi(histories[1:], 14, cp) if len(histories) > 15 else None,
            "fibonacci": self._calculate_fibonacci(histories, cp),
            "asset_type": "jp_stock", "currency": "JPY"
        })
        return data

class InvestTrustScraper(BaseScraper):
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching Invest Trust: {code}")
        res = self._make_request(f"https://finance.yahoo.co.jp/quote/{code}")
        if not res: return {"code": code, "error": "通信エラー"}
        json_text = self._extract_next_data(res.text)
        data = self._scavenge_common_data(res.text, json_text)
        
        # 投資信託特有の項目 (前日比など)
        # "fundPrices":{"price":"35,766","changePrice":"+123","changePriceRate":"+0.34"
        change_m = re.search(r'\"changePrice\":\"([\+\-\d,\.]+)\"', json_text)
        data['change'] = change_m.group(1).replace(',', '') if change_m else "N/A"
        rate_m = re.search(r'\"changePriceRate\":\"([\+\-\d,\.]+)\"', json_text)
        data['change_percent'] = rate_m.group(1) if rate_m else "N/A"
        
        data.update({"code": code, "asset_type": "investment_trust", "currency": "JPY"})
        return data

class USStockScraper(BaseScraper):
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching US Stock: {code}")
        res = self._make_request(f"https://finance.yahoo.co.jp/quote/{code}")
        if not res: return {"code": code, "error": "通信エラー"}
        json_text = self._extract_next_data(res.text)
        data = self._scavenge_common_data(res.text, json_text)
        
        # 米国株特有の項目
        # "priceChange":{"value":"-1.23"},"priceChangeRate":{"value":"-0.45"}
        change_m = re.search(r'\"priceChange\":\{\"value\":\"([\+\-\d,\.]+)\"\}', json_text)
        data['change'] = change_m.group(1).replace(',', '') if change_m else "N/A"
        rate_m = re.search(r'\"priceChangeRate\":\{\"value\":\"([\+\-\d,\.]+)\"\}', json_text)
        data['change_percent'] = rate_m.group(1) if rate_m else "N/A"

        data.update({"code": code, "asset_type": "us_stock", "currency": "USD"})
        return data

class IndexScraper(BaseScraper):
    def fetch_data(self, code: str) -> Optional[Dict[str, Any]]:
        logger.info(f"Fetching Market Index: {code}")
        res = self._make_request(f"https://finance.yahoo.co.jp/quote/{code}")
        if not res: return {"code": code, "error": "通信エラー"}
        data = self._scavenge_common_data(res.text, "")
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
