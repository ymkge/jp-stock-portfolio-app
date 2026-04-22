import requests, re, time
from typing import Dict, Any

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
        title_match = re.search(r'<title>(.*?)</title>', html)
        data['name'] = title_match.group(1).split('【')[0].split('：')[0].replace(' - Yahoo!ファイナンス', '').strip() if title_match else 'N/A'
        
        price_match = re.search(r'\"price\":\{\"value\":\"([\d,\.]+)\"\}', json_text)
        if price_match:
            data['price'] = price_match.group(1).replace(',', '')
        else:
            candidates = re.findall(r'value__[\w]+\">([\d,\.]+)<', html)
            prices = [c.replace(',', '') for c in candidates if c != '0.00']
            data['price'] = prices[0] if prices else 'N/A'
            
        for key, pattern in {'per': r'\"per\":\{.*?\"value\":\"([\d,\.]+)\"', 'yield': r'\"shareDividendYield\":\{.*?\"value\":\"([\d,\.]+)\"'}.items():
            match = re.search(pattern, json_text)
            data[key] = match.group(1).replace(',', '') if match and match.group(1) != '---' else 'N/A'
        
        data['histories_count'] = 0
        hist_match = re.search(r'\"histories\":(\[.*?\])', json_text)
        if hist_match:
            records = re.findall(r'\{"date":"(.*?)","values":\[(.*?\])\}', hist_match.group(1))
            data['histories_count'] = len(records)
        return data

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0"})

samples = [
    ("7203", "jp_stock", "トヨタ"),
    ("9984", "jp_stock", "ソフトバンクG"),
    ("8306", "jp_stock", "三菱UFJ"),
    ("9101", "jp_stock", "日本郵船"),
    ("AAPL", "us_stock", "Apple"),
    ("NVDA", "us_stock", "Nvidia"),
    ("TSLA", "us_stock", "Tesla"),
    ("0331418A", "investment_trust", "オルカン"),
    ("0331113C", "investment_trust", "S&P500"),
    ("998407.O", "index", "日経平均")
]

print("| 銘柄コード | 資産タイプ | 期待 | 取得銘柄名 | 価格 | PER | 利回り | 履歴数 | 判定 |")
print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

for code, atype, expected in samples:
    suffix = ".T" if atype == "jp_stock" else ""
    url = f"https://finance.yahoo.co.jp/quote/{code}{suffix}"
    try:
        res = session.get(url, timeout=10)
        json_text = LightweightNextEngine.extract_json_data(res.text)
        data = LightweightNextEngine.scavenger_extract(res.text, json_text, atype)
        
        if data['histories_count'] == 0:
            res_h = session.get(f"{url}/history", timeout=10)
            json_h = LightweightNextEngine.extract_json_data(res_h.text)
            data_h = LightweightNextEngine.scavenger_extract(res_h.text, json_h, atype)
            data['histories_count'] = data_h['histories_count']
        
        is_ok = "✅" if data['name'] != "N/A" and data['price'] != "N/A" else "❌"
        if atype == "jp_stock" and data['per'] == "N/A" and data['yield'] == "N/A": is_ok = "⚠️"
        h_mark = " (履歴OK)" if data['histories_count'] > 0 else " (履歴×)"
        
        print(f"| {code} | {atype} | {expected} | {data['name']} | {data['price']} | {data['per']} | {data['yield']} | {data['histories_count']} | {is_ok}{h_mark} |")
    except Exception as e:
        print(f"| {code} | {atype} | {expected} | ERROR | - | - | - | - | ❌ ({str(e)}) |")
    time.sleep(1.0)
