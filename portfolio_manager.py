import json
import os
import csv
import io

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

def delete_multiple_codes(codes_to_delete: list[str]):
    """
    指定された複数の銘柄コードをportfolio.jsonから削除する。
    """
    current_codes = load_codes()
    updated_codes = [code for code in current_codes if code not in codes_to_delete]
    save_codes(updated_codes)

def create_csv_data(data: list[dict]) -> str:
    """
    銘柄データのリストからCSV文字列を生成する。
    """
    if not data:
        return ""

    # StringIOを使い、メモリ上でCSVを作成
    output = io.StringIO()
    # Unicode-BOM付きUTF-8でエンコード指定
    output.write('\ufeff')
    writer = csv.writer(output)

    # ヘッダーを書き込む (データのキーから取得)
    # scraper.pyの返す辞書のキーの順序を想定
    headers = [
        "code", "name", "industry", "score", "price", "change", "change_percent",
        "market_cap", "per", "pbr", "roe", "eps", "yield"
    ]
    # 表示用の日本語ヘッダー
    display_headers = [
        "銘柄コード", "銘柄名", "業種", "スコア", "現在株価", "前日比", "前日比(%)",
        "時価総額(億円)", "PER(倍)", "PBR(倍)", "ROE(%)", "EPS(円)", "配当利回り(%)"
    ]
    writer.writerow(display_headers)

    # 各行のデータを書き込む
    for item in data:
        row = []
        for h in headers:
            value = item.get(h, "")
            if h == 'market_cap':
                try:
                    # 円単位の値を億円単位に変換
                    yen_value = float(str(value).replace(',', ''))
                    oku_yen_value = yen_value / 100_000_000
                    # 小数点以下2桁にフォーマット
                    value = f"{oku_yen_value:.2f}"
                except (ValueError, TypeError):
                    value = "N/A" # 変換に失敗した場合はN/A
            row.append(value)
        writer.writerow(row)

    return output.getvalue()

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
