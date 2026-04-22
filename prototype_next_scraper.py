
import requests
import re
import logging
import time
import json
from typing import Dict, Any

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LightweightNextEngine:
    @staticmethod
    def extract_json_data(html: str) -> str:
        chunks = []
        for match in re.finditer(r'self\.__next_f\.push\(\[\d+,"(.*?)"\]\)', html):
            chunks.append(match.group(1).replace('\\"', '"').replace('\\\\', '\\'))
        return "".join(chunks)

    @staticmethod
    def scavenger_extract(html: str, json_text: str, asset_type: str) -> Dict[str, Any]:
        data = {}
        
        # 1. 銘柄名
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            name = title_match.group(1).split('【')[0].split('：')[0].replace(' - Yahoo!ファイナンス', '').strip()
            data['name'] = name
        else:
            data['name'] = "N/A"

        # 2. 現在値 (ハイブリッド)
        # JSON優先
        price_match = re.search(r'\"price\":\{\"value\":\"([\d,\.]+)\"\}', json_text)
        if price_match:
            data['price'] = price_match.group(1).replace(',', '')
        else:
            # HTMLフォールバック: 0.00以外の数値を優先して探す
            # 米国株の価格表示によく使われるパターン
            candidates = re.findall(r'value__[\w]+">([\d,\.]+)<', html)
            prices = [c.replace(',', '') for c in candidates if c != "0.00"]
            data['price'] = prices[0] if prices else "N/A"

        # 3. 指標
        patterns = {
            'per': r'\"per\":\{.*?\"value\":\"([\d,\.]+)\"',
            'pbr': r'\"pbr\":\{.*?\"value\":\"([\d,\.]+)\"',
            'yield': r'\"shareDividendYield\":\{.*?\"value\":\"([\d,\.]+)\"',
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, json_text)
            if match:
                val = match.group(1).replace(',', '')
                data[key] = val if val != "---" else "N/A"
            else:
                data[key] = "N/A"

        # 4. 時系列 (安定化版)
        data['histories'] = []
        # "histories":[...] の中身だけをまず切り出す
        hist_match = re.search(r'\"histories\":(\[.*?\])', json_text)
        if hist_match:
            hist_json_str = hist_match.group(1)
            # 各レコードを個別に抜く {"date":"...","values":[...]}
            records = re.findall(r'\{"date":"(.*?)","values":\[(.*?\])\}', hist_json_str)
            for dt, val_block in records:
                # 各レコード内の数値を抜く
                vals = re.findall(r'\"value\":\"([\d,\.]+)\"', val_block)
                if len(vals) >= 4:
                    data['histories'].append({
                        "baseDatetime": dt,
                        "closePrice": vals[3].replace(',', '')
                    })
        
        return data

class HybridScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})

    def fetch(self, code: str, asset_type: str = "jp_stock"):
        suffix = ".T" if asset_type == "jp_stock" else ""
        url = f"https://finance.yahoo.co.jp/quote/{code}{suffix}/history"
        logger.info(f"Fetching: {code}")
        
        try:
            res = self.session.get(url, timeout=10)
            html = res.text
            json_text = LightweightNextEngine.extract_json_data(html)
            results = LightweightNextEngine.scavenger_extract(html, json_text, asset_type)
            
            # 指標補完
            time.sleep(0.5)
            main_url = f"https://finance.yahoo.co.jp/quote/{code}{suffix}"
            res_main = self.session.get(main_url, timeout=10)
            if res_main.status_code == 200:
                html_main = res_main.text
                json_main = LightweightNextEngine.extract_json_data(html_main)
                main_data = LightweightNextEngine.scavenger_extract(html_main, json_main, asset_type)
                for k, v in main_data.items():
                    if k == 'histories': continue
                    if v != "N/A" or results.get(k) == "N/A":
                        results[k] = v
            return results
        except Exception as e:
            return {"error": str(e)}

if __name__ == "__main__":
    scraper = HybridScraper()
    for c, t in [("7203", "jp_stock"), ("AAPL", "us_stock"), ("0331418A", "investment_trust")]:
        print(f"\n--- Testing {c} ({t}) ---")
        data = scraper.fetch(c, t)
        print(f"Name: {data.get('name')} | Price: {data.get('price')}")
        print(f"PER: {data.get('per')} | Yield: {data.get('yield')}")
        print(f"Histories: {len(data.get('histories', []))} records")
        if data.get('histories'):
            print(f"Latest History: {data['histories'][0]}")
