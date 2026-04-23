
import json
from scraper import get_scraper

def verify():
    scraper = get_scraper('jp_stock')
    
    # 調査対象銘柄
    yield_codes = ["6501", "4755", "8604", "6954", "3668", "3632"]
    roe_codes = ["3668", "6963"]
    all_codes = sorted(list(set(yield_codes + roe_codes)))
    
    print(f"{'コード':<8} | {'銘柄名':<20} | {'ROE':<8} | {'利回り':<8} | {'履歴数':<6} | {'最新履歴'}")
    print("-" * 80)
    
    for code in all_codes:
        # キャッシュを回避するために内部メソッドを直接呼ぶか、引数で調整
        data = scraper.fetch_data(code)
        name = data.get('name', 'N/A')[:20]
        roe = data.get('roe', 'N/A')
        yield_val = data.get('yield', 'N/A')
        div_hist = data.get('dividend_history', {})
        hist_count = len(div_hist)
        latest_div = sorted(div_hist.items(), reverse=True)[0] if div_hist else "N/A"
        
        print(f"{code:<8} | {name:<20} | {roe:<8} | {yield_val:<8} | {hist_count:<6} | {latest_div}")

if __name__ == "__main__":
    verify()
