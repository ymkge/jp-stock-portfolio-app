import requests, re, time
from typing import Dict, Any

class FinalScraperEngine:
    @staticmethod
    def extract_from_html(html: str, asset_type: str) -> Dict[str, Any]:
        data = {'histories': []}
        
        # 1. 銘柄名 (titleタグから)
        title_m = re.search(r'<title>(.*?)</title>', html)
        data['name'] = title_m.group(1).split('【')[0].split('：')[0].replace(' - Yahoo!ファイナンス', '').strip() if title_m else 'N/A'
        
        # 2. 現在値 (HTMLタグから)
        # _StyledNumber クラスなどの数値部分を抽出
        price_m = re.search(r'value__[\w]+">([\d,\.]+)<', html)
        data['price'] = price_m.group(1).replace(',', '') if price_m else 'N/A'

        # 3. 時系列データ (HTMLのテーブル構造から)
        # 構造: <th ...>2026/4/22</th> ... <span ...>2,820</span> ... (x4つ)
        # 日付と、それに続く4つの価格（始値、高値、安値、終値）をセットで抜く
        # re.DOTALL (S) を使用して改行を跨ぐ
        pattern = r'>(\d{4}/\d{1,2}/\d{1,2})</th>.*?value__[\w]+">([\d,\.]+)<.*?value__[\w]+">([\d,\.]+)<.*?value__[\w]+">([\d,\.]+)<.*?value__[\w]+">([\d,\.]+)<'
        records = re.findall(pattern, html, re.S)
        
        for rec in records:
            dt, o, h, l, c = rec
            data['histories'].append({
                "baseDatetime": dt,
                "closePrice": c.replace(',', '')
            })
            
        return data

    @staticmethod
    def extract_indicators_from_json(html: str) -> Dict[str, Any]:
        # 指標(PER/Yield)はJSON断片に含まれている
        chunks = []
        for match in re.finditer(r'self\.__next_f\.push\(\[\d+,"(.*?)"\]\)', html):
            chunks.append(match.group(1).replace('\\"', '"').replace('\\\\', '\\'))
        json_text = "".join(chunks)
        
        results = {}
        for key, pattern in {'per': r'\"per\":\{.*?\"value\":\"([\d,\.]+)\"', 'yield': r'\"shareDividendYield\":\{.*?\"value\":\"([\d,\.]+)\"'}.items():
            match = re.search(pattern, json_text)
            results[key] = match.group(1).replace(',', '') if match and match.group(1) != '---' else 'N/A'
        return results

if __name__ == "__main__":
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    
    code = "7203.T"
    print(f"--- Final Validation for {code} ---")
    
    # 1. /history ページ取得 (1回目のリクエスト)
    res_h = session.get(f"https://finance.yahoo.co.jp/quote/{code}/history")
    data = FinalScraperEngine.extract_from_html(res_h.text, "jp_stock")
    
    # 2. /quote ページ取得 (2回目のリクエスト: 指標補完)
    res_q = session.get(f"https://finance.yahoo.co.jp/quote/{code}")
    indicators = FinalScraperEngine.extract_indicators_from_json(res_q.text)
    data.update(indicators)
    
    print(f"Name: {data['name']}")
    print(f"Price: {data['price']}")
    print(f"PER: {data['per']} | Yield: {data['yield']}%")
    print(f"Histories Found: {len(data['histories'])}")
    if data['histories']:
        print(f"Latest 3 days:")
        for h in data['histories'][:3]:
            print(f"  - {h['baseDatetime']}: {h['closePrice']}")
