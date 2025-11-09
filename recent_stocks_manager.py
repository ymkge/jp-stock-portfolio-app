import json
import os

RECENT_STOCKS_FILE = "recent_stocks.json"
MAX_RECENT_STOCKS = 10

def load_recent_codes() -> list[str]:
    """
    recent_stocks.jsonから直近追加された銘柄コードのリストを読み込む。
    ファイルが存在しない場合は空のリストを返す。
    """
    if not os.path.exists(RECENT_STOCKS_FILE):
        return []
    try:
        with open(RECENT_STOCKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "recent_codes" in data and isinstance(data["recent_codes"], list):
                return data["recent_codes"]
            return []
    except (json.JSONDecodeError, IOError):
        return []

def save_recent_codes(codes: list[str]):
    """
    直近追加された銘柄コードのリストをrecent_stocks.jsonに保存する。
    """
    with open(RECENT_STOCKS_FILE, "w", encoding="utf-8") as f:
        json.dump({"recent_codes": codes}, f, indent=4)

def add_recent_code(code: str):
    """
    新しい銘柄コードを直近追加リストに追加し、最大件数を維持して保存する。
    """
    recent_codes = load_recent_codes()
    
    # 既存のコードがあれば削除して、最新の位置に移動
    if code in recent_codes:
        recent_codes.remove(code)
    
    # リストの先頭に追加
    recent_codes.insert(0, code)
    
    # 最大件数を超えたら古いものを削除
    if len(recent_codes) > MAX_RECENT_STOCKS:
        recent_codes = recent_codes[:MAX_RECENT_STOCKS]
        
    save_recent_codes(recent_codes)

if __name__ == '__main__':
    # テスト用
    print("--- Testing recent_stocks_manager ---")

    # 初期状態
    print(f"Initial recent codes: {load_recent_codes()}")

    # 銘柄を追加
    add_recent_code("7203")
    print(f"After adding 7203: {load_recent_codes()}")

    add_recent_code("9432")
    print(f"After adding 9432: {load_recent_codes()}")

    add_recent_code("8058")
    print(f"After adding 8058: {load_recent_codes()}")

    # 既存の銘柄を追加 (先頭に移動することを確認)
    add_recent_code("7203")
    print(f"After adding 7203 again: {load_recent_codes()}")

    # 10件以上追加して、最大件数を超えないことを確認
    for i in range(1, 15):
        add_recent_code(f"100{i:02d}")
    print(f"After adding many codes: {load_recent_codes()}")
    print(f"Length: {len(load_recent_codes())}")

    # クリーンアップ
    if os.path.exists(RECENT_STOCKS_FILE):
        os.remove(RECENT_STOCKS_FILE)
        print(f"Cleaned up {RECENT_STOCKS_FILE}")
