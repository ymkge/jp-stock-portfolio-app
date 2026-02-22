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

def _migrate_asset_properties(portfolio: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    各資産に asset_type と currency がない場合にデフォルト値を設定する移行処理。
    """
    if not portfolio:
        return portfolio

    # 1つでも asset_type または currency がない要素があるかチェック
    needs_migration = any("asset_type" not in asset or "currency" not in asset for asset in portfolio)

    if not needs_migration:
        return portfolio

    print("Asset properties not found in some assets. Migrating to new format.")
    
    # 全要素をループして、必要ならプロパティを設定
    for asset in portfolio:
        if "asset_type" not in asset:
            asset["asset_type"] = "jp_stock"
        
        if "currency" not in asset:
            if asset["asset_type"] in ["jp_stock", "investment_trust"]:
                asset["currency"] = "JPY"
            elif asset["asset_type"] == "us_stock":
                asset["currency"] = "USD"
            else:
                asset["currency"] = "JPY"  # 不明な場合はJPYにフォールバック

    save_portfolio(portfolio) # 更新された portfolio を保存
    print("Asset properties migration complete.")
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
            migrated_data = _migrate_to_multi_account(data)
            return _migrate_asset_properties(migrated_data)
        # 初代の{"codes": []}形式からの移行
        elif isinstance(data, dict) and "codes" in data:
             print("Legacy format detected. Migrating...")
             new_portfolio = [{"code": code, "asset_type": "jp_stock", "currency": "JPY", "holdings": []} for code in data["codes"]]
             save_portfolio(new_portfolio)
             return new_portfolio

    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        print(f"Error decoding portfolio file: {e}")
        raise e
    except IOError as e:
        print(f"Error loading portfolio file: {e}")
        return []

def save_portfolio(portfolio: List[Dict[str, Any]]):
    """
    ポートフォリオデータをportfolio.jsonに保存する。
    """
    sorted_portfolio = sorted(portfolio, key=lambda x: x.get("code", ""))
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_portfolio, f, indent=4, ensure_ascii=False)

def add_asset(code: str, asset_type: str) -> bool:
    """
    新しい資産をポートフォリオに追加する。
    成功すればTrue、既に存在する場合はFalseを返す。
    """
    portfolio = load_portfolio()
    if any(asset['code'] == code for asset in portfolio):
        return False

    # asset_type に応じて currency を決定
    currency = "JPY"
    if asset_type == "us_stock":
        currency = "USD"

    new_asset = {"code": code, "asset_type": asset_type, "currency": currency, "holdings": []}
    portfolio.append(new_asset)
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

def calculate_holding_values(
    asset_data: Dict[str, Any],
    holding: Dict[str, Any],
    exchange_rates: Dict[str, float],
    tax_config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    個別の保有情報に対して、評価額、損益、年間配当などを計算し、円換算する。
    データが取得できない場合はエラーを出さずに 'None' を返すように堅牢化。
    """
    market_value, profit_loss, profit_loss_rate, price_in_jpy = None, None, None, None
    total_annual_dividend = None
    total_annual_dividend_after_tax = None
    
    try:
        purchase_price = float(holding.get("purchase_price", 0))
        quantity = float(holding.get("quantity", 0))
        price_str = str(asset_data.get("price", "")).replace(',', '')
        
        if price_str and price_str not in ['N/A', '---', '']:
            current_price_foreign = float(price_str)
            currency = asset_data.get("currency", "JPY")
            exchange_rate = exchange_rates.get(currency, 1.0)

            price_in_jpy = current_price_foreign * exchange_rate
            market_value = price_in_jpy * quantity
            # 投資額は購入時の為替レートを考慮すべきだが、簡単のため現在のレートで円換算
            investment_value = purchase_price * quantity * exchange_rate
            profit_loss = market_value - investment_value
            profit_loss_rate = (profit_loss / investment_value) * 100 if investment_value != 0 else 0

        annual_dividend_str = str(asset_data.get("annual_dividend", "0")).replace(',', '')
        if annual_dividend_str and annual_dividend_str not in ['N/A', '---', '']:
            annual_dividend_foreign = float(annual_dividend_str)
            currency = asset_data.get("currency", "JPY")
            exchange_rate = exchange_rates.get(currency, 1.0)
            total_annual_dividend = annual_dividend_foreign * quantity * exchange_rate

            # --- 税金計算ロジック ---
            total_annual_dividend_after_tax = total_annual_dividend
            account_type = holding.get("account_type")
            asset_type = asset_data.get("asset_type")
            
            # tax_config と、その中のキーの存在をチェック
            if tax_config and 'non_taxable_accounts' in tax_config and 'tax_info' in tax_config:
                is_taxable = account_type not in tax_config.get("non_taxable_accounts", [])
                
                if is_taxable and asset_type in tax_config["tax_info"]:
                    tax_rate = tax_config["tax_info"][asset_type].get("tax_rate", 0)
                    total_annual_dividend_after_tax = total_annual_dividend * (1 - tax_rate)
            # -------------------------
    
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        pass

    return {
        "holding_id": holding.get("id"),
        "account_type": holding.get("account_type"),
        "security_company": holding.get("security_company"),
        "memo": holding.get("memo"),
        "purchase_price": holding.get("purchase_price"),
        "quantity": holding.get("quantity"),
        "price": price_in_jpy, # 円換算後の現在値を返す
        "market_value": market_value,
        "profit_loss": profit_loss,
        "profit_loss_rate": profit_loss_rate,
        "estimated_annual_dividend": total_annual_dividend,
        "estimated_annual_dividend_after_tax": total_annual_dividend_after_tax,
    }

def calculate_portfolio_stats(holdings_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    保有資産リストからポートフォリオ全体の統計情報を計算する。
    加重平均PER, PBR, ROE, 利回り、および分散度(HHI, Top5)を算出。
    """
    total_market_value = sum(item.get("market_value") for item in holdings_list if isinstance(item.get("market_value"), (int, float)))
    
    if total_market_value == 0:
        return {}

    metrics = ["per", "pbr", "roe", "yield"]
    # 加重合計用の変数。キーごとに (値 * 時価評価額) の合計を保持
    weighted_sums = {m: 0.0 for m in metrics}
    # 加重平均を計算する際の分母（その指標が有効な銘柄の時価評価額合計）
    weights_total = {m: 0.0 for m in metrics}

    # 銘柄ごとの時価評価額を集計（Top5, HHI用）
    # 同じ銘柄(code)が複数口座にある場合を考慮して合算
    asset_market_values = {}
    for item in holdings_list:
        code = item.get("code")
        mv = item.get("market_value")
        if code and isinstance(mv, (int, float)):
            asset_market_values[code] = asset_market_values.get(code, 0) + mv

    # HHI指数の計算
    hhi = 0
    for mv in asset_market_values.values():
        weight_pct = (mv / total_market_value) * 100
        hhi += weight_pct ** 2

    # Top5 占有率
    sorted_values = sorted(asset_market_values.values(), reverse=True)
    top5_value = sum(sorted_values[:5])
    top5_ratio = (top5_value / total_market_value) * 100 if total_market_value > 0 else 0

    # 加重平均の計算
    for item in holdings_list:
        mv = item.get("market_value")
        if not isinstance(mv, (int, float)) or mv <= 0:
            continue
            
        for m in metrics:
            val = item.get(m)
            # 文字列の場合は数値に変換を試みる
            if isinstance(val, str):
                try:
                    # '倍' や '%' などの単位、カンマを除去
                    clean_val = val.replace(',', '').replace('倍', '').replace('%', '').strip()
                    if clean_val and clean_val not in ['N/A', '---']:
                        val = float(clean_val)
                    else:
                        val = None
                except ValueError:
                    val = None
            
            if isinstance(val, (int, float)):
                weighted_sums[m] += val * mv
                weights_total[m] += mv

    summary_stats = {
        "weighted_per": weighted_sums["per"] / weights_total["per"] if weights_total["per"] > 0 else None,
        "weighted_pbr": weighted_sums["pbr"] / weights_total["pbr"] if weights_total["pbr"] > 0 else None,
        "weighted_roe": weighted_sums["roe"] / weights_total["roe"] if weights_total["roe"] > 0 else None,
        "weighted_yield": weighted_sums["yield"] / weights_total["yield"] if weights_total["yield"] > 0 else None,
        "hhi": hhi,
        "top5_ratio": top5_ratio,
        "total_market_value": total_market_value,
        "style_breakdown": calculate_style_breakdown(holdings_list, total_market_value)
    }

    return summary_stats

def calculate_style_breakdown(holdings: List[Dict[str, Any]], total_mv: float) -> Dict[str, Any]:
    """
    保有資産のスタイル内訳（景気特性、バリュー/グロース、大型/中小型）を計算する。
    """
    if total_mv <= 0:
        return {}

    # 業種分類の定義 (本来は highlight_rules.json から取得すべきだが、まずはコード内に定義)
    defensive_industries = ["食料品", "医薬品", "電気・ガス業", "陸運業", "情報・通信業"]
    cyclical_industries = ["輸送用機器", "鉄鋼", "海運業", "卸売業", "鉱業", "機械", "化学", "非鉄金属", "ガラス・土石製品"]

    breakdown = {
        "cyclicality": {"defensive": 0, "cyclical": 0, "other": 0},
        "style": {"value": 0, "growth": 0, "blend": 0},
        "market_cap": {"large": 0, "mid_small": 0}
    }

    for item in holdings:
        mv = item.get("market_value")
        if not isinstance(mv, (int, float)) or mv <= 0:
            continue
        
        # 1. 景気特性
        industry = item.get("industry", "その他")
        if industry in defensive_industries:
            breakdown["cyclicality"]["defensive"] += mv
        elif industry in cyclical_industries:
            breakdown["cyclicality"]["cyclical"] += mv
        else:
            breakdown["cyclicality"]["other"] += mv

        # 2. バリュー/グロース
        per = None
        pbr = None
        try:
            p_val = item.get("per")
            if isinstance(p_val, str):
                p_val = p_val.replace(',', '').replace('倍', '').replace('%', '').strip()
                if p_val and p_val not in ['N/A', '---']: per = float(p_val)
            elif isinstance(p_val, (int, float)): per = p_val

            pb_val = item.get("pbr")
            if isinstance(pb_val, str):
                pb_val = pb_val.replace(',', '').replace('倍', '').replace('%', '').strip()
                if pb_val and pb_val not in ['N/A', '---']: pbr = float(pb_val)
            elif isinstance(pb_val, (int, float)): pbr = pb_val
        except (ValueError, TypeError): pass

        if per is not None and pbr is not None:
            if per < 15.0 and pbr < 1.0:
                breakdown["style"]["value"] += mv
            elif per > 25.0 or pbr > 2.5:
                breakdown["style"]["growth"] += mv
            else:
                breakdown["style"]["blend"] += mv
        else:
            breakdown["style"]["blend"] += mv

        # 3. 時価総額区分 (大型: 1兆円以上)
        mcap_val = item.get("market_cap")
        mcap = 0
        if isinstance(mcap_val, str):
            try:
                mcap_str = mcap_val.replace(',', '')
                if '兆' in mcap_str:
                    mcap = float(mcap_str.split('兆')[0]) * 1_000_000_000_000
                elif '億' in mcap_str:
                    mcap = float(mcap_str.split('億')[0]) * 100_000_000
                else:
                    # 数値のみの場合
                    mcap = float(mcap_str)
            except (ValueError, IndexError, TypeError): pass
        elif isinstance(mcap_val, (int, float)):
            mcap = mcap_val

        if mcap >= 1_000_000_000_000:
            breakdown["market_cap"]["large"] += mv
        else:
            breakdown["market_cap"]["mid_small"] += mv

    # 比率(%)に変換
    result = {
        "cyclicality": {k: (v / total_mv) * 100 for k, v in breakdown["cyclicality"].items()},
        "style": {k: (v / total_mv) * 100 for k, v in breakdown["style"].items()},
        "market_cap": {k: (v / total_mv) * 100 for k, v in breakdown["market_cap"].items()}
    }
    return result

def create_csv_data(data: list[dict]) -> str:
    """
    ポートフォリオデータのリストからCSV文字列を生成する。
    国内株式、投資信託、米国株式に対応する。
    """
    if not data:
        return ""
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    # ヘッダー定義
    headers = [
        "code", "name", "asset_type", "market", "currency", "industry", "score", "price", "change", "change_percent",
        "market_cap", "per", "pbr", "roe", "eps", "yield", "fibonacci", "rci_26", "annual_dividend", "consecutive_increase_years",
        "settlement_month", "net_assets", "trust_fee"
    ]
    display_headers = [
        "コード", "名称", "資産タイプ", "市場", "通貨", "業種", "スコア", "現在値", "前日比", "前日比(%)",
        "時価総額", "PER(倍)", "PBR(倍)", "ROE(%)", "EPS(円)", "配当利回り(%)", "フィボナッチ(%)", "RCI(26)", "年間配当(円)", "連続増配年数",
        "決算月", "純資産総額", "信託報酬"
    ]
    writer.writerow(display_headers)

    for item in data:
        row = []
        asset_type_display = ""
        if item.get("asset_type") == "jp_stock":
            asset_type_display = "国内株式"
        elif item.get("asset_type") == "investment_trust":
            asset_type_display = "投資信託"
        elif item.get("asset_type") == "us_stock":
            asset_type_display = "米国株式"

        for h in headers:
            value = ""
            if h == "asset_type":
                value = asset_type_display
            elif h == "market":
                value = item.get("market", "")
            elif h == "currency":
                value = item.get("currency", "")
            elif h == 'market_cap':
                # market_capは円換算後の値が来ることを想定
                if item.get(h) not in ["N/A", "", None]:
                    try:
                        # 数値としてフォーマットされている可能性があるので、文字列として処理
                        str_value = str(item.get(h)).replace(',', '')
                        if str_value.endswith('兆円'):
                            value = float(str_value.replace('兆円', '')) * 1_000_000_000_000
                        elif str_value.endswith('億円'):
                            value = float(str_value.replace('億円', '')) * 100_000_000
                        else:
                            value = float(str_value)
                        value = f"{value:,.0f}円" # 円換算後の値として表示
                    except (ValueError, TypeError):
                        value = "N/A"
                else:
                    value = "N/A"
            elif h == 'score' and item.get("asset_type") == "jp_stock":
                value = item.get(h, "")
            elif h == 'fibonacci' and item.get("asset_type") == "jp_stock":
                fib = item.get("fibonacci")
                if fib and isinstance(fib, dict) and fib.get("retracement") is not None:
                    value = f"{fib['retracement']:.1f}"
                else:
                    value = "-"
            elif h == 'rci_26' and item.get("asset_type") == "jp_stock":
                rci = item.get("rci_26")
                if rci is not None:
                    value = f"{rci:.1f}"
                else:
                    value = "-"
            elif h == 'consecutive_increase_years' and item.get("asset_type") == "jp_stock":
                value = item.get(h, "")
            elif h == 'settlement_month' and item.get("asset_type") in ["jp_stock", "us_stock"]:
                value = item.get(h, "")
            elif h == 'net_assets' and item.get("asset_type") == "investment_trust":
                value = item.get(h, "")
            elif h == 'trust_fee' and item.get("asset_type") == "investment_trust":
                value = item.get(h, "")
            elif h in ["code", "name", "price", "change", "change_percent"]:
                value = item.get(h, "")
            elif item.get("asset_type") == "jp_stock" and h in ["industry", "per", "pbr", "roe", "eps", "yield", "annual_dividend"]:
                value = item.get(h, "")
            elif item.get("asset_type") == "us_stock" and h in ["per", "yield"]: # 米国株で取得できる項目
                value = item.get(h, "")
            # その他の項目は空欄のまま

            row.append(value)
        writer.writerow(row)
    return output.getvalue()

def create_analysis_csv_data(data: list[dict]) -> str:
    """
    分析ページ用の保有口座データリストからCSV文字列を生成する。
    国内株式、投資信託、米国株式に対応する。
    """
    if not data:
        return ""
    
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    headers = [
        "code", "name", "asset_type", "market", "currency", "security_company", "account_type", "industry", "quantity", "purchase_price", "price",
        "fibonacci", "rci_26", "market_value", "profit_loss", "profit_loss_rate", "estimated_annual_dividend", "estimated_annual_dividend_after_tax", "dividend_contribution", "memo"
    ]
    display_headers = [
        "コード", "名称", "資産タイプ", "市場", "通貨", "証券会社", "口座種別", "業種", "数量", "取得単価", "現在値",
        "フィボナッチ(%)", "RCI(26)", "評価額", "損益", "損益率(%)", "年間配当", "年間配当(税引後)", "配当構成比 (%)", "備考"
    ]
    writer.writerow(display_headers)

    for item in data:
        row = []
        asset_type_display = ""
        if item.get("asset_type") == "jp_stock":
            asset_type_display = "国内株式"
        elif item.get("asset_type") == "investment_trust":
            asset_type_display = "投資信託"
        elif item.get("asset_type") == "us_stock":
            asset_type_display = "米国株式"

        for h in headers:
            value = ""
            if h == "asset_type":
                value = asset_type_display
            elif h == "market":
                value = item.get("market", "")
            elif h == "currency":
                value = item.get("currency", "")
            elif h == "industry" and item.get("asset_type") == "investment_trust":
                value = "投資信託" # 投資信託の業種は「投資信託」とする
            elif h == 'fibonacci' and item.get("asset_type") == "jp_stock":
                fib = item.get("fibonacci")
                if fib and isinstance(fib, dict) and fib.get("retracement") is not None:
                    value = f"{fib['retracement']:.1f}"
                else:
                    value = "-"
            elif h == 'rci_26' and item.get("asset_type") == "jp_stock":
                rci = item.get("rci_26")
                if rci is not None:
                    value = f"{rci:.1f}"
                else:
                    value = "-"
            elif h in ["estimated_annual_dividend", "estimated_annual_dividend_after_tax"] and item.get("asset_type") == "investment_trust":
                value = "" # 投資信託には年間配当は表示しない
            else:
                value = item.get(h, "")
            row.append(value)
        writer.writerow(row)

    return output.getvalue()
