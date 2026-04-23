
import requests
import re
import json

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
}

def extract_next_data(html: str) -> str:
    chunks = []
    for match in re.finditer(r'self\.__next_f\.push\(\[\d+,"(.*?)"\]\)', html):
        chunk = match.group(1)
        chunk = chunk.replace('\\"', '"').replace('\\\\', '\\').replace('\\n', '\n')
        chunks.append(chunk)
    return "".join(chunks)

def inspect_stock(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    res = requests.get(url, headers=DEFAULT_HEADERS)
    html = res.text
    next_data = extract_next_data(html)
    
    with open(f"debug_{code}_next.txt", "w", encoding="utf-8") as f:
        f.write(next_data)
    
    print(f"--- Inspecting {code}.T ---")
    
    # ROEの探索
    print("\n[ROE Search]")
    roe_matches = re.findall(r'\"roe\":\{.*?\"value\":\"(.*?)\"', next_data)
    print(f"ROE (standard): {roe_matches}")
    
    roe_raw_matches = re.findall(r'\"roe\":([\d\.]+)', next_data)
    print(f"ROE (raw): {roe_raw_matches}")

    # 配当履歴の探索
    print("\n[Dividend History Search]")
    # 配当に関わりそうなキーワードを抽出
    div_keywords = re.findall(r'\"(dividend|dps|dividendYield|dividendAmount)\":.*?(?=\{|\"|\[)', next_data)
    print(f"Keywords found: {set(div_keywords)}")
    
    # 業績データ（年次）の構造を把握
    # {"date":"202303","amount":...} のような箇所を探す
    financial_blocks = re.findall(r'\"date\":\"\d{4,6}\",.*?(?=\})', next_data)
    print(f"Financial blocks sample: {financial_blocks[:5]}")

if __name__ == "__main__":
    inspect_stock("7203") # トヨタ
    inspect_stock("8001") # 伊藤忠 (増配傾向)
