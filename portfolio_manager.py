import json
import os
import csv
import io
from typing import List, Dict, Any

PORTFOLIO_FILE = "portfolio.json"

def _migrate_old_format(data: Any) -> List[Dict[str, Any]]:
    """古いデータ形式を新しい形式に変換する。"""
    if isinstance(data, dict) and "codes" in data and isinstance(data["codes"], list):
        print("Old portfolio format detected. Migrating to new format.")
        new_portfolio = [
            {
                "code": str(code),
                "is_managed": False,
                "purchase_price": None,
                "quantity": None
            }
            for code in data["codes"]
        ]
        save_portfolio(new_portfolio)
        return new_portfolio
    # If it's already a list of dicts (new format), or something unexpected, return as is
    if isinstance(data, list):
        return data
    return []

def load_portfolio() -> List[Dict[str, Any]]:
    """
    portfolio.jsonからポートフォリオデータを読み込む。
    古い形式の場合は新しい形式に変換する。
    """
    if not os.path.exists(PORTFOLIO_FILE):
        return []
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            # ファイルが空の場合の対策
            content = f.read()
            if not content:
                return []
            data = json.loads(content)
        
        # 古い形式かどうかをチェックし、必要なら移行
        if isinstance(data, dict) and "codes" in data:
            return _migrate_old_format(data)
        
        # 新しい形式（オブジェクトのリスト）であることを期待
        if isinstance(data, list):
            return data
            
        return []
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading portfolio file: {e}")
        return []

def save_portfolio(portfolio: List[Dict[str, Any]]):
    """
    ポートフォリオデータをportfolio.jsonに保存する。
    """
    # 銘柄コードでソートして保存
    sorted_portfolio = sorted(portfolio, key=lambda x: x.get("code", ""))
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_portfolio, f, indent=4, ensure_ascii=False)

def add_stock(code: str) -> bool:
    """
    新しい銘柄をポートフォリオに追加する。
    成功すればTrue、既に存在する場合はFalseを返す。
    """
    portfolio = load_portfolio()
    if any(stock['code'] == code for stock in portfolio):
        return False  # 既に存在する

    new_stock = {
        "code": code,
        "is_managed": False,
        "purchase_price": None,
        "quantity": None
    }
    portfolio.append(new_stock)
    save_portfolio(portfolio)
    return True

def delete_stocks(codes_to_delete: List[str]):
    """
    指定された複数の銘柄コードをポートフォリオから削除する。
    """
    portfolio = load_portfolio()
    updated_portfolio = [stock for stock in portfolio if stock.get("code") not in codes_to_delete]
    save_portfolio(updated_portfolio)

def update_stock(code: str, data: Dict[str, Any]) -> bool:
    """
    指定された銘柄の情報を更新する。
    """
    portfolio = load_portfolio()
    stock_found = False
    for stock in portfolio:
        if stock.get("code") == code:
            stock.update(data)
            stock_found = True
            break
    
    if stock_found:
        save_portfolio(portfolio)
        return True
    return False

def create_csv_data(data: list[dict]) -> str:
    """
    銘柄データのリストからCSV文字列を生成する。
    """
    if not data:
        return ""

    output = io.StringIO()
    output.write('\ufeff')  # BOM for Excel
    writer = csv.writer(output)

    headers = [
        "code", "name", "industry", "score", "price", "change", "change_percent",
        "market_cap", "per", "pbr", "roe", "eps", "yield",
        "investment_amount", "market_value", "profit_loss", "profit_loss_rate", "estimated_annual_dividend"
    ]
    display_headers = [
        "銘柄コード", "銘柄名", "業種", "スコア", "現在株価", "前日比", "前日比(%)",
        "時価総額(億円)", "PER(倍)", "PBR(倍)", "ROE(%)", "EPS(円)", "配当利回り(%)",
        "投資額", "評価額", "損益", "損益率(%)", "年間配当金予想"
    ]
    writer.writerow(display_headers)

    for item in data:
        row = []
        for h in headers:
            value = item.get(h, "")
            if h == 'market_cap' and value not in ["N/A", "", None]:
                try:
                    yen_value = float(str(value).replace(',', ''))
                    oku_yen_value = yen_value / 100_000_000
                    value = f"{oku_yen_value:.2f}"
                except (ValueError, TypeError):
                    value = "N/A"
            row.append(value)
        writer.writerow(row)

    return output.getvalue()

def create_analysis_csv_data(data: list[dict]) -> str:
    """
    分析ページ用の銘柄データリストからCSV文字列を生成する。
    """
    if not data:
        return ""

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    headers = [
        "code", "name", "industry", "quantity", "purchase_price", "price",
        "market_value", "profit_loss", "profit_loss_rate", "estimated_annual_dividend"
    ]
    display_headers = [
        "銘柄コード", "銘柄名", "業種", "数量", "取得単価", "現在株価",
        "評価額", "損益", "損益率(%)", "年間配当"
    ]
    writer.writerow(display_headers)

    for item in data:
        row = [item.get(h, "") for h in headers]
        writer.writerow(row)

    return output.getvalue()


if __name__ == '__main__':
    # --- テスト ---
    print("--- Running portfolio_manager tests ---")

    # 1. 古い形式のファイルを作成して移行をテスト
    print("\n1. Testing migration from old format...")
    old_format_data = {"codes": ["7203", "9432"]}
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(old_format_data, f)
    
    migrated_portfolio = load_portfolio()
    print(f"   Loaded and migrated portfolio: {migrated_portfolio}")
    assert len(migrated_portfolio) == 2
    assert migrated_portfolio[0]['code'] == '7203'
    assert migrated_portfolio[0]['is_managed'] is False

    # 2. 新しい銘柄を追加
    print("\n2. Testing add_stock...")
    add_stock("8058")
    portfolio = load_portfolio()
    print(f"   Portfolio after adding 8058: {portfolio}")
    assert len(portfolio) == 3
    assert any(s['code'] == '8058' for s in portfolio)

    # 3. 存在する銘柄を追加しようとする
    print("\n3. Testing adding an existing stock...")
    result = add_stock("7203")
    print(f"   Result of adding existing stock 7203: {result}")
    assert result is False

    # 4. 銘柄を更新
    print("\n4. Testing update_stock...")
    update_stock("7203", {"is_managed": True, "quantity": 100})
    portfolio = load_portfolio()
    updated_stock = next(s for s in portfolio if s['code'] == '7203')
    print(f"   Portfolio after updating 7203: {portfolio}")
    assert updated_stock['is_managed'] is True
    assert updated_stock['quantity'] == 100

    # 5. 複数の銘柄を削除
    print("\n5. Testing delete_stocks...")
    delete_stocks(["9432", "8058"])
    portfolio = load_portfolio()
    print(f"   Portfolio after deleting 9432 and 8058: {portfolio}")
    assert len(portfolio) == 1
    assert portfolio[0]['code'] == '7203'

    # クリーンアップ
    if os.path.exists(PORTFOLIO_FILE):
        os.remove(PORTFOLIO_FILE)
        print(f"\nCleaned up {PORTFOLIO_FILE}")
    
    print("\n--- All tests passed ---")