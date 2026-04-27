
import time
import random
import re
from scraper import JPStockScraper

def verify_stocks(codes):
    scraper = JPStockScraper()
    
    print("=== 時系列データ最終検証 (100% 共通ロジック) ===")
    
    for code in codes:
        print(f"\n銘柄コード: {code}")
        all_prices = []
        
        for page in range(1, 14):
            if page == 1:
                url = f"https://finance.yahoo.co.jp/quote/{code}.T/history"
            else:
                params = f"page={page}&_data=app%2Fpc%2F%5Btype%5D%2Fquote%2F%5Bcode%5D%2Fhistory%2Fpage"
                url = f"https://finance.yahoo.co.jp/quote/{code}.T/history?{params}"
            
            res = scraper._make_request(url)
            if not res:
                print(f"  Page {page}: 取得失敗")
                break
            
            # 【重要】実際のアプリと全く同じロジックを呼び出す
            histories = scraper._parse_histories(res.text)
            
            if not histories:
                print(f"  Page {page}: 有効な株価データなし (終了)")
                break
                
            page_prices = [float(h['closePrice']) for h in histories]
            all_prices.extend(page_prices)
            print(f"  Page {page}: {len(histories)}件取得 (安値: {min(page_prices):.1f}, 高値: {max(page_prices):.1f})")
            
            time.sleep(1.5 + random.uniform(0, 1))
            
        if all_prices:
            print(f"--- 最終検証結果: {code} ---")
            print(f"合計取得数: {len(all_prices)} 営業日 (約1年分)")
            print(f"期間内安値: {min(all_prices):.1f}")
            print(f"期間内高値: {max(all_prices):.1f}")
            # 株価の妥当性セルフチェック
            avg_price = sum(all_prices) / len(all_prices)
            is_valid = True
            for p in all_prices:
                if p > avg_price * 5 or p < avg_price * 0.2:
                    print(f"  [ALERT] 異常値の可能性あり: {p:.1f}")
                    is_valid = False
            
            if is_valid:
                print("  => データ妥当性: 合格 (出来高混入の疑いなし)")
            else:
                print("  => データ妥当性: 不合格 (要再調査)")
        else:
            print(f"--- 結果: {code} 取得失敗 ---")

if __name__ == "__main__":
    verify_stocks(["7203", "9432", "8035"])
