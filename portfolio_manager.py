import json
import os
import csv
import io
import uuid
from typing import List, Dict, Any, Optional

PORTFOLIO_FILE = "portfolio.json"

def _migrate_to_multi_account(portfolio: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    単一保有情報形式から複数口座保有形式へのデータ移行を行う。
    is_managedキーの存在で古い形式かを判断する。
    """
    # 最初の要素をチェックして、移行が必要か判断
    if not portfolio or "holdings" in portfolio[0]:
        return portfolio  # 既に新しい形式か、空の場合は何もしない

    print("Old portfolio format detected. Migrating to multi-account format.")
    migrated_portfolio = []
    needs_migration = False
    for stock in portfolio:
        if "is_managed" in stock:
            needs_migration = True
            new_stock = {"code": stock["code"], "holdings": []}
            if stock.get("is_managed"):
                new_holding = {
                    "id": str(uuid.uuid4()),
                    "account_type": "デフォルト", # 移行用のデフォルト口座名
                    "purchase_price": stock.get("purchase_price"),
                    "quantity": stock.get("quantity")
                }
                new_stock["holdings"].append(new_holding)
            migrated_portfolio.append(new_stock)
        else:
            # 混合形式は想定しないが、念のため元のデータを維持
            migrated_portfolio.append(stock)

    if needs_migration:
        save_portfolio(migrated_portfolio)
        print("Migration complete.")
        return migrated_portfolio
    
    return portfolio


def load_portfolio() -> List[Dict[str, Any]]:
    """
    portfolio.jsonからポートフォリオデータを読み込む。
    必要に応じて古いデータ形式からの移行処理を行う。
    """
    if not os.path.exists(PORTFOLIO_FILE):
        return []
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            if not content:
                return []
            data = json.loads(content)
        
        # オブジェクトのリストであることを期待
        if isinstance(data, list):
            return _migrate_to_multi_account(data)
        # 初代の{"codes": []}形式からの移行
        elif isinstance(data, dict) and "codes" in data:
             print("Legacy format detected. Migrating...")
             new_portfolio = [{"code": code, "holdings": []} for code in data["codes"]]
             save_portfolio(new_portfolio)
             return new_portfolio

        return []
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading portfolio file: {e}")
        return []

def save_portfolio(portfolio: List[Dict[str, Any]]):
    """
    ポートフォリオデータをportfolio.jsonに保存する。
    """
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
        return False

    new_stock = {"code": code, "holdings": []}
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

def get_stock_info(code: str) -> Optional[Dict[str, Any]]:
    """
    指定された銘柄コードのポートフォリオ情報を取得する。
    見つからない場合はNoneを返す。
    """
    portfolio = load_portfolio()
    for stock in portfolio:
        if stock.get("code") == code:
            return stock
    return None

def add_holding(code: str, holding_data: Dict[str, Any]) -> str:
    """
    特定の銘柄に新しい保有情報を追加する。
    新しい保有情報のIDを返す。
    """
    portfolio = load_portfolio()
    new_holding_id = str(uuid.uuid4())
    holding_data['id'] = new_holding_id
    
    stock_found = False
    for stock in portfolio:
        if stock.get("code") == code:
            stock.setdefault("holdings", []).append(holding_data)
            stock_found = True
            break
    
    if not stock_found:
        # 銘柄自体が存在しない場合はエラー（通常は起こらないはず）
        raise ValueError(f"Stock with code {code} not found in portfolio.")

    save_portfolio(portfolio)
    return new_holding_id

def update_holding(holding_id: str, update_data: Dict[str, Any]) -> bool:
    """
    指定されたIDの保有情報を更新する。
    """
    portfolio = load_portfolio()
    holding_found = False
    for stock in portfolio:
        for holding in stock.get("holdings", []):
            if holding.get("id") == holding_id:
                holding.update(update_data)
                holding_found = True
                break
        if holding_found:
            break
    
    if holding_found:
        save_portfolio(portfolio)
        return True
    return False

def delete_holding(holding_id: str) -> bool:
    """
    指定されたIDの保有情報を削除する。
    """
    portfolio = load_portfolio()
    holding_found = False
    for stock in portfolio:
        original_holdings = stock.get("holdings", [])
        updated_holdings = [h for h in original_holdings if h.get("id") != holding_id]
        if len(original_holdings) != len(updated_holdings):
            stock["holdings"] = updated_holdings
            holding_found = True
            break
            
    if holding_found:
        save_portfolio(portfolio)
        return True
    return False


# --- CSV生成関数 (既存のものは維持しつつ、将来的に改修) ---

def create_csv_data(data: list[dict]) -> str:
    """
    銘柄データのリストからCSV文字列を生成する。
    """
    if not data:
        return ""
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    headers = [
        "code", "name", "industry", "score", "price", "change", "change_percent",
        "market_cap", "per", "pbr", "roe", "eps", "yield"
    ]
    display_headers = [
        "銘柄コード", "銘柄名", "業種", "スコア", "現在株価", "前日比", "前日比(%)",
        "時価総額(億円)", "PER(倍)", "PBR(倍)", "ROE(%)", "EPS(円)", "配当利回り(%)"
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
    分析ページ用の保有口座データリストからCSV文字列を生成する。
    副作用を避けるため、引数のリストをコピーしてから処理する。
    """
    if not data:
        return ""
    
    # 副作用を完全に防ぐため、リストのコピーを作成して使用する
    data_copy = list(data)

    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    headers = [
        "code", "name", "account_type", "industry", "quantity", "purchase_price", "price",
        "market_value", "profit_loss", "profit_loss_rate", "estimated_annual_dividend"
    ]
    display_headers = [
        "銘柄コード", "銘柄名", "口座種別", "業種", "数量", "取得単価", "現在株価",
        "評価額", "損益", "損益率(%)", "年間配当"
    ]
    writer.writerow(display_headers)

    # ヘッダー行の辞書を作成し、コピーしたデータの先頭に追加（バグの再現と修正）
    # この部分が意図せず副作用を起こしていたと仮定し、修正する
    # header_dict = {key: val for key, val in zip(headers, display_headers)}
    # data_copy.insert(0, header_dict) # この行がバグの原因だったと仮定して削除

    for item in data_copy:
        row = []
        for h in headers:
            value = item.get(h, "")
            row.append(value)
        writer.writerow(row)

    return output.getvalue()
