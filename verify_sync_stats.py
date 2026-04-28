
import sys
import json
import re
from datetime import datetime
from scraper import JPStockScraper

def test_stats_extraction(code):
    scraper = JPStockScraper()
    print(f"--- Testing stats extraction for {code} ---")
    
    # 1. 現在値の取得 (パース時のフィルタに使用されるため)
    main_url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    res_m = scraper._make_request(main_url)
    current_price = 0.0
    if res_m:
        json_m = scraper._extract_next_data(res_m.text)
        m_data = scraper._scavenge_common_data(res_m.text, json_m)
        p_val = m_data.get('price')
        if isinstance(p_val, str): p_val = p_val.replace(',', '')
        try:
            current_price = float(p_val)
            print(f"Current Price (for filter): {current_price}")
        except:
            print("Could not get current price, skipping filter.")

    # 2. 履歴ページ(1ページ目)の取得
    url = f"https://finance.yahoo.co.jp/quote/{code}.T/history"
    res = scraper._make_request(url)
    if not res:
        print("Error: Failed to fetch data.")
        return

    # 3. データのパース
    json_data = scraper._extract_next_data(res.text)
    norm_text = (json_data if json_data else res.text).replace('\\"', '"')
    records = re.findall(r'\{"date":"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",\s*"values":\s*\[(.*?\}\s*\])', norm_text, re.S)
    
    if records:
        for dt_str, val_block in records:
            if "2025/12/19" in dt_str:
                print(f"Debug: Record for {dt_str} values:")
                vals = re.findall(r'"value":"([\d\.\-\,]+)"', val_block)
                for i, v in enumerate(vals):
                    print(f"  Index {i}: {v}")
    
    # パース時に current_price を渡す
    raw_histories = scraper._parse_histories(json_data if json_data else res.text, current_price=current_price)
    
    if not raw_histories:
        print("Warning: No history data found.")
        # 生データを少し出力して原因調査
        print("Raw data sample (first 500 chars):")
        print(res.text[:500])
        return

    print(f"Total records found in page 1: {len(raw_histories)}")
    
    # 4. 統計情報の計算テスト
    prices = []
    dates = []
    for h in raw_histories:
        try:
            p_str = h.get('closePrice', '0').replace(',', '')
            p = float(p_str)
            if p > 0:
                prices.append(p)
                dates.append(h.get('baseDatetime'))
        except ValueError:
            continue
            
    if prices:
        min_p = min(prices)
        max_p = max(prices)
        avg_p = sum(prices) / len(prices)
        
        # 異常値の特定用
        for h in raw_histories:
            p = float(h.get('closePrice', '0'))
            if p == max_p or p == min_p:
                 print(f"Debug: Edge Case Record: Date={h.get('baseDatetime')}, Price={p}, Volume={h.get('volume')}")
        
        # 日付文字列をdatetimeオブジェクトに変換して比較
        dt_objects = []
        for d in dates:
            try:
                dt_objects.append(datetime.strptime(d.replace('-', '/'), '%Y/%m/%d'))
            except ValueError:
                continue
        
        if dt_objects:
            start_d = min(dt_objects).strftime('%Y-%m-%d')
            end_d = max(dt_objects).strftime('%Y-%m-%d')
            
            print(f"Stats Result:")
            print(f"  - Valid Count: {len(prices)}")
            print(f"  - Period: {start_d} to {end_d}")
            print(f"  - Price Min: {min_p}")
            print(f"  - Price Max: {max_p}")
            print(f"  - Price Avg: {avg_p:.2f}")
        else:
            print("Error: Could not parse dates.")
    else:
        print("Error: Could not extract valid prices from records.")

if __name__ == "__main__":
    # 引数があればそれを使用、なければトヨタ(7203)
    test_code = sys.argv[1] if len(sys.argv) > 1 else "7203"
    test_stats_extraction(test_code)
