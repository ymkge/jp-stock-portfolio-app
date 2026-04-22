
import requests
import re
import json

def inspect_histories(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers)
    html = response.text
    
    # self.__next_f.push の中身を結合
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
    combined_text = "".join(chunks).replace('\\"', '"').replace('\\\\', '\\')
    
    # histories 配列を探す
    # Next.jsのデータ構造上、"timeSeriesData":{"histories":[...]} の形式になっているはず
    match = re.search(r'"histories":(\[.*?\])', combined_text)
    if match:
        histories_raw = match.group(1)
        # 最初の2件程度を表示して構造を確認
        try:
            # histories_raw は不完全なJSONの可能性があるため、正規表現で個別の要素を抜くか
            # JSONとしてパースを試みる
            # ここではデータの断片をそのまま見せる
            print(f"--- {code} の時系列データ先頭部分 ---")
            print(histories_raw[:1000] + "...")
            
            # 具体的なキーの存在チェック
            has_close = "closePrice" in histories_raw
            has_date = "baseDatetime" in histories_raw
            print(f"\nキーの確認:")
            print(f"  closePrice (終値): {'あり' if has_close else 'なし'}")
            print(f"  baseDatetime (日付): {'あり' if has_date else 'なし'}")
            
        except Exception as e:
            print(f"解析エラー: {e}")
    else:
        print("histories が見つかりませんでした。")

if __name__ == "__main__":
    inspect_histories("8306")
