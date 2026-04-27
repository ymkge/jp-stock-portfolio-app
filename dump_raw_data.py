
import requests
import json
from scraper import JPStockScraper

def dump():
    scraper = JPStockScraper()
    code = "7203"
    
    # 1ページ目 (HTML)
    print("Fetching Page 1...")
    url1 = f"https://finance.yahoo.co.jp/quote/{code}.T/history"
    res1 = scraper._make_request(url1)
    with open("debug_raw_p1.html", "w", encoding="utf-8") as f:
        f.write(res1.text)
    
    # 2ページ目 (Next.js Data)
    print("Fetching Page 2...")
    params = f"page=2&_data=app%2Fpc%2F%5Btype%5D%2Fquote%2F%5Bcode%5D%2Fhistory%2Fpage"
    url2 = f"https://finance.yahoo.co.jp/quote/{code}.T/history?{params}"
    res2 = scraper._make_request(url2)
    with open("debug_raw_p2.txt", "w", encoding="utf-8") as f:
        f.write(res2.text)
        
    print("Done. Files: debug_raw_p1.html, debug_raw_p2.txt")

if __name__ == "__main__":
    dump()
