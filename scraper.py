import requests
from bs4 import BeautifulSoup
from typing import Optional

def fetch_stock_data(stock_code: str) -> Optional[dict]:
    """
    Yahoo!ファイナンスから指定された銘柄コードの株価、財務指標、配当情報を取得する。
    """
    url = f"https://finance.yahoo.co.jp/quote/{stock_code}.T"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # --- 銘柄名 ---
        name_tag = soup.select_one('h1._233f2Y_2')
        name = "N/A"
        if name_tag:
            name_full_text = name_tag.get_text(strip=True)
            # "株式会社"などを削除し、括弧の前までを取得
            name = name_full_text.split('(')[0].replace('株式会社', '').strip()

        # --- 株価 ---
        price_tag = soup.select_one('span._3rXWJKZF')
        price = price_tag.text.strip() if price_tag else "N/A"

        # --- 詳細情報テーブルから指標を取得 ---
        details = {}
        for tr in soup.select('div._2l3c02yI._1Fp_c3jC > ul > li'):
            if th := tr.select_one('th'):
                if td := tr.select_one('td'):
                    key = th.text.strip()
                    value = td.text.strip()
                    details[key] = value
        
        return {
            "code": stock_code,
            "name": name,
            "price": price,
            "market_cap": details.get("時価総額", "N/A"),
            "per": details.get("PER(連)", "N/A"),
            "pbr": details.get("PBR(連)", "N/A"),
            "dividend_yield": details.get("配当利回り(連)", "N/A"),
        }

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {stock_code}: {e}")
        return None
    except Exception as e:
        print(f"An error occurred while parsing data for {stock_code}: {e}")
        return None

if __name__ == '__main__':
    # テスト用
    data = fetch_stock_data("7203") # トヨタ自動車
    if data:
        print(data)
    data = fetch_stock_data("9432") # NTT
    if data:
        print(data)