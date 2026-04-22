import requests, re, time
from typing import Dict, Any

class FinalScraperEngine:
    @staticmethod
    def extract_from_html(html: str) -> Dict[str, Any]:
        data = {'histories': []}
        
        # 銘柄名
        title_m = re.search(r'<title>(.*?)</title>', html)
        data['name'] = title_m.group(1).split('【')[0].split('：')[0].strip() if title_m else 'N/A'
        
        # 現在値 (HTML内の _StyledNumber__value のうち最初の方にあるものを探す)
        # メインページ用
        price_m = re.search(r'_StyledNumber__value[^\"]*\">([\d,\.]+)<', html)
        data['price'] = price_m.group(1).replace(',', '') if price_m else 'N/A'

        # 時系列 (日付と、それに続く4つの価格をセットで抜く)
        # 0:始値, 1:高値, 2:安値, 3:終値
        pattern = r'>(\d{4}/\d{1,2}/\d{1,2})</th>' + r'.*?_StyledNumber__value[^\"]*\">([\d,\.]+)<' * 4
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
        chunks = []
        for match in re.finditer(r'self\.__next_f\.push\(\[\d+,"(.*?)"\]\)', html):
            chunks.append(match.group(1).replace('\\"', '"').replace('\\\\', '\\'))
        json_text = "".join(chunks)
        results = {}
        for key, pat in {'per': r'\"per\":\{.*?\"value\":\"([\d,\.]+)\"', 'yield': r'\"shareDividendYield\":\{.*?\"value\":\"([\d,\.]+)\"'}.items():
            m = re.search(pat, json_text)
            results[key] = m.group(1).replace(',', '') if m and m.group(1) != '---' else 'N/A'
        return results

if __name__ == "__main__":
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    code = "7203.T"
    print(f"--- Final Validation (v3) for {code} ---")
    
    # Historyページ (1回目)
    res_h = session.get(f"https://finance.yahoo.co.jp/quote/{code}/history")
    data = FinalScraperEngine.extract_from_html(res_h.text)
    
    # Quoteページ (2回目: 指標)
    res_q = session.get(f"https://finance.yahoo.co.jp/quote/{code}")
    inds = FinalScraperEngine.extract_indicators_from_json(res_q.text)
    data.update(inds)
    # 現在値がhistoryから取れなかった場合の補完
    if data['price'] == 'N/A':
        data['price'] = FinalScraperEngine.extract_from_html(res_q.text)['price']

    print(f"Name: {data['name']} | Price: {data['price']}")
    print(f"PER: {data['per']} | Yield: {data['yield']}%")
    print(f"Histories Found: {len(data['histories'])}")
    if data['histories']:
        print(f"Latest: {data['histories'][0]['baseDatetime']} = {data['histories'][0]['closePrice']}")
