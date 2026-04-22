
import requests
import re

def test_headers_for_data(code):
    url = f"https://finance.yahoo.co.jp/quote/{code}.T"
    
    header_variants = [
        # 1. 既存のブラウザ偽装
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        },
        # 2. スマホブラウザ偽装
        {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        },
        # 3. クローラー (Googlebot) 偽装
        {
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        }
    ]
    
    target_values = ["35.02", "6.04", "1.03", "4,554,292"]
    
    for i, headers in enumerate(header_variants):
        print(f"\n--- パターン {i+1} テスト中 (UA: {headers['User-Agent'][:30]}...) ---")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            text = response.text
            
            # 指標データが含まれているかチェック
            found_any = False
            for val in target_values:
                if val in text:
                    print(f"  [SUCCESS] 値 '{val}' を発見しました！")
                    found_any = True
                
            if "__PRELOADED_STATE__" in text:
                print("  [SUCCESS] __PRELOADED_STATE__ が復活しました！")
                found_any = True
                
            if not found_any:
                print("  [FAILURE] 重要なデータは見つかりませんでした。")
                
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    # 味の素 (2802)
    test_headers_for_data("2802")
