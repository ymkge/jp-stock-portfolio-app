import json
import os

PORTFOLIO_FILE = "portfolio.json"

def load_codes() -> list:
    """
    portfolio.jsonから銘柄コードのリストを読み込む。
    ファイルが存在しない場合は空のリストを返す。
    """
    if not os.path.exists(PORTFOLIO_FILE):
        return []
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "codes" in data and isinstance(data["codes"], list):
                return data["codes"]
            return []
    except (json.JSONDecodeError, IOError):
        return []

def save_codes(codes: list):
    """
    銘柄コードのリストをportfolio.jsonに保存する。
    """
    # 重複を除き、ソートして保存する
    unique_codes = sorted(list(set(codes)))
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump({"codes": unique_codes}, f, indent=4)

if __name__ == '__main__':
    # テスト用
    test_codes = ["7203", "9432", "8058", "7203"]
    save_codes(test_codes)
    print(f"Saved codes: {test_codes}")

    loaded_codes = load_codes()
    print(f"Loaded codes: {loaded_codes}")

    # クリーンアップ
    if os.path.exists(PORTFOLIO_FILE):
        os.remove(PORTFOLIO_FILE)
        print(f"Cleaned up {PORTFOLIO_FILE}")
