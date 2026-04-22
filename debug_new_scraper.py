
import requests
from bs4 import BeautifulSoup
import re
import json

def test_new_scraping(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }
    
    print(f"--- {code} の取得テスト開始 ---")
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 1. 銘柄名
    name_tag = soup.find('h1')
    name = name_tag.text if name_tag else "N/A"
    print(f"銘柄名: {name}")

    # 2. 現在値 (大きな文字で表示されているはず)
    # class名に 'StyledNumber' が含まれるものを探す
    price = "N/A"
    price_tags = soup.find_all(class_=re.compile("StyledNumber__value"))
    if price_tags:
        # 最初の大きな数値が株価である可能性が高い
        price = price_tags[0].text
    print(f"現在値: {price}")

    # 3. 各種指標 (PER, PBR, 利回りなど)
    # dtタグ(ラベル)とddタグ(値)のペアを全取得
    indicators = {}
    for dt in soup.find_all('dt'):
        label = dt.text.strip()
        dd = dt.find_next_sibling('dd')
        if dd:
            # dd内の StyledNumber__value を探すか、なければテキストそのまま
            val_tag = dd.find(class_=re.compile("StyledNumber__value"))
            val = val_tag.text if val_tag else dd.text.strip()
            indicators[label] = val
    
    print("抽出された指標:")
    for k, v in indicators.items():
        if k in ["PER（会社予想）", "PBR（実績）", "配当利回り（会社予想）", "時価総額"]:
            print(f"  {k}: {v}")

    # 4. Next.jsのストリーミングデータから隠れたJSONを探す (おまけ)
    print("\n--- ストリーミングデータの解析 ---")
    found_json = False
    for script in soup.find_all('script'):
        content = script.string if script else ""
        if content and "self.__next_f.push" in content:
            # 非常に複雑な形式なので、キーワードで検索
            if "marketCap" in content or "per" in content:
                print("  データを含みそうなScriptタグを発見しました")
                found_json = True
                break
    if not found_json:
        print("  有効なストリーミングデータは見つかりませんでした")

if __name__ == "__main__":
    test_new_scraping("2802")
