
import requests
import re
import json
import time

def extract_next_data(html):
    """Next.jsのストリーミングデータ(self.__next_f.push)から情報を抽出する"""
    results = {}
    # push([1, "内容"]) の形式をすべて抽出
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
    
    combined_text = "".join(chunks).replace('\\"', '"').replace('\\\\', '\\')
    
    # 1. 指標データ (PER, PBR, 利回り等)
    # indicators の開始位置を探す
    if '"indicators":{' in combined_text:
        try:
            # indicatorsから始まるJSONに近い部分を強引に切り出す
            start_idx = combined_text.find('"indicators":{') - 1
            # 簡易的なブラケットバランスで抽出（深追いはせず、ある程度の長さで切る）
            segment = combined_text[start_idx : start_idx + 10000]
            # JSONとして成立するように末尾を調整するか、正規表現で個別に抜く
            results['per'] = re.search(r'"per":\{"name":"PER",.*?"value":"([\d\.]+)"', segment)
            results['pbr'] = re.search(r'"pbr":\{"name":"PBR",.*?"value":"([\d\.]+)"', segment)
            results['yield'] = re.search(r'"shareDividendYield":\{"name":"配当利回り",.*?"value":"([\d\.]+)"', segment)
            results['market_cap'] = re.search(r'"totalPrice":\{"name":"時価総額",.*?"value":"([\d,]+)"', segment)
            results['name'] = re.search(r'"name":"(.*?)"', combined_text) # 銘柄名
        except Exception:
            pass

    # 2. 時系列データ (移動平均用)
    if '"histories":[' in combined_text:
        results['has_history'] = True
    else:
        results['has_history'] = False
        
    return results

def test_multi_stocks():
    stocks = [
        {"code": "7203", "name": "トヨタ"},
        {"code": "6758", "name": "ソニー"},
        {"code": "8306", "name": "三菱UFJ"},
        {"code": "9984", "name": "ソフトバンクG"},
        {"code": "4502", "name": "武田薬品"}
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }

    print(f"{'コード':<6} | {'銘柄名':<15} | {'PER':<7} | {'PBR':<7} | {'利回り':<7} | {'時系列'}")
    print("-" * 70)

    for stock in stocks:
        code = stock['code']
        url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            data = extract_next_data(res.text)
            
            per = data.get('per').group(1) if data.get('per') else "N/A"
            pbr = data.get('pbr').group(1) if data.get('pbr') else "N/A"
            yld = data.get('yield').group(1) if data.get('yield') else "N/A"
            hist = "OK" if data.get('has_history') else "NG"
            name = data.get('name').group(1) if data.get('name') else stock['name']
            
            print(f"{code:<6} | {name[:15]:<15} | {per:<7} | {pbr:<7} | {yld:<7}% | {hist}")
            
            time.sleep(1.0) # お行儀よく
        except Exception as e:
            print(f"{code:<6} | Error: {e}")

if __name__ == "__main__":
    test_multi_stocks()
