
import requests
import re
import json
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EnhancedNextParser:
    """さらに堅牢なNext.jsパースエンジン"""
    
    @staticmethod
    def extract_full_text(html: str) -> str:
        # push配列を回収
        chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
        # エスケープを段階的に解除 (Next.js特有の多重エスケープ対応)
        raw_text = "".join(chunks)
        # 1. \" -> "
        decoded = raw_text.replace('\\"', '"')
        # 2. \\n -> 実際の改行 (もしあれば)
        decoded = decoded.replace('\\n', '\n')
        # 3. その他、Unicode等のデコードは Pythonの文字列処理に任せる
        return decoded

    @staticmethod
    def scavenger_hunt(text: str, asset_type: str):
        res = {}
        
        # 1. 銘柄名 ( "name":"..." のうち、viewport等ではないもの)
        # 株価ボード付近の名前を狙う
        name_match = re.search(r'"priceBoard":\{"name":"(.*?)"', text)
        if not name_match:
            name_match = re.search(r'"name":"((?:(?!viewport|default).)+?)"', text)
        res['name'] = name_match.group(1) if name_match else "N/A"

        # 2. 現在値
        price_match = re.search(r'"price":"([\d,]+\.?\d*)"', text)
        res['price'] = price_match.group(1).replace(',', '') if price_match else "N/A"

        # 3. 国内株指標 (正規表現をより柔軟に)
        if asset_type == "jp_stock":
            targets = {
                'per': r'"per":\{.*?"value":"([\d\.]+)"',
                'pbr': r'"pbr":\{.*?"value":"([\d\.]+)"',
                'yield': r'"shareDividendYield":\{.*?"value":"([\d\.]+)"',
                'market_cap': r'"totalPrice":\{.*?"value":"([\d,]+)"',
                'roe': r'"roe":\{.*?"value":"([\d\.]+)"',
                'industry': r'"industryName":"(.*?)"'
            }
            for key, pattern in targets.items():
                match = re.search(pattern, text)
                res[key] = match.group(1) if match else "N/A"

        # 4. 時系列 (ここが最重要)
        # histories配列の中身を強引に抽出
        # 文字列として "baseDatetime":"...","closePrice":"..." が並んでいるはず
        history_items = re.findall(r'\{"baseDatetime":"(.*?)"(?:,.*?)?"closePrice":"([\d,]+(?:\.\d+)?)"\}', text)
        res['histories'] = []
        for dt, pr in history_items:
            res['histories'].append({
                "baseDatetime": dt,
                "closePrice": pr.replace(',', '')
            })
            
        return res

def test_recovery():
    scraper = requests.Session()
    scraper.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"})
    
    code = "8306"
    print(f"\n--- {code} 最終リカバリテスト ---")
    
    # 時系列ページから全ての情報を抜くことを試みる
    url = f"https://finance.yahoo.co.jp/quote/{code}.T/history"
    res = scraper.get(url)
    full_text = EnhancedNextParser.extract_full_text(res.text)
    
    data = EnhancedNextParser.scavenger_hunt(full_text, "jp_stock")
    
    print(f"銘柄名: {data['name']}")
    print(f"現在値: {data['price']}")
    print(f"PER: {data['per']} | PBR: {data['pbr']} | 利回り: {data['yield']}%")
    print(f"取得できた時系列データ数: {len(data['histories'])}")
    if data['histories']:
        print(f"直近の終値: {data['histories'][-1]}")
        print(f"最古の終値: {data['histories'][0]}")

if __name__ == "__main__":
    test_recovery()
