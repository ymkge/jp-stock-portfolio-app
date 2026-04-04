import requests
import json
import re
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
}

def check_page(code, tab_name):
    url = f"https://finance.yahoo.co.jp/quote/{code}.T/{tab_name}"
    logger.info(f"Checking {url}...")
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        match = re.search(r"window.__PRELOADED_STATE__\s*=\s*(\{.*\})", response.text)
        if match:
            data = json.loads(match.group(1))
            # 取得できたキーの一覧を表示して構造を把握する
            logger.info(f"Keys found in {tab_name}: {list(data.keys())}")
            
            # 代表的な場所を深掘り
            if tab_name == "news":
                news_data = data.get("mainStocksNews", {}).get("news", [])
                logger.info(f"Found {len(news_data)} news items.")
                for item in news_data[:3]:
                    logger.info(f"- {item.get('title')}")
            
            elif tab_name == "performance":
                # 業績進捗の場所を探す
                # 過去の経験から mainStocksPerformance などのキーがあるはず
                perf_keys = [k for k in data.keys() if "Performance" in k]
                logger.info(f"Performance related keys: {perf_keys}")
                for pk in perf_keys:
                    perf_data = data.get(pk, {})
                    # 進捗率 (progress rate) を探す
                    # 構造をダンプ（一部）
                    logger.info(f"Snippet of {pk}: {str(perf_data)[:500]}...")

        else:
            logger.warning(f"No __PRELOADED_STATE__ found in {tab_name}")
            # HTMLをファイルに書き出して手動確認
            with open(f"debug_{tab_name}.html", "w") as f:
                f.write(response.text)
            logger.info(f"Wrote HTML to debug_{tab_name}.html")
            
    except Exception as e:
        logger.error(f"Error checking {tab_name}: {e}")

if __name__ == "__main__":
    test_code = "7203" # トヨタ自動車
    check_page(test_code, "news")
    check_page(test_code, "performance")
