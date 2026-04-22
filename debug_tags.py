
import requests
import re
from bs4 import BeautifulSoup

def analyze_tag_structure(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    print(f"--- {code} のタグ構造精密分析 ---")
    
    # PER (35.02) を含むタグをすべて探し、その周辺の構造を表示する
    per_val = "35.02"
    tags = soup.find_all(string=re.compile(per_val))
    
    for i, t in enumerate(tags):
        parent = t.parent
        print(f"\n[Match {i+1}]")
        print(f"  Tag: <{parent.name}>")
        print(f"  Classes: {parent.get('class')}")
        print(f"  Text: {t.strip()}")
        # 親の親まで辿って、ラベル（PER）が近くにあるか確認
        grandparent = parent.parent
        if grandparent:
            print(f"  Grandparent Text: {grandparent.get_text()[:100]}...")

if __name__ == "__main__":
    analyze_tag_structure("2802")
