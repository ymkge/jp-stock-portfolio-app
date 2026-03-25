import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

DB_FILE = "portfolio_history.db"
logger = logging.getLogger(__name__)

# JST (UTC+9) の定義
JST = timezone(timedelta(hours=9))

def get_now_jst() -> datetime:
    """現在のJST時刻を取得する"""
    return datetime.now(timezone.utc).astimezone(JST)

def init_db():
    """データベースとテーブルを初期化する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # 既存の月次履歴テーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_date TEXT NOT NULL,
                    snapshot_month TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT,
                    asset_type TEXT,
                    account_type TEXT,
                    security_company TEXT,
                    quantity REAL,
                    purchase_price REAL,
                    current_price REAL,
                    market_value REAL,
                    profit_loss REAL,
                    profit_loss_rate REAL,
                    estimated_annual_dividend REAL,
                    industry TEXT,
                    memo TEXT
                )
            """)
            
            # 日次の時系列・キャッシュ用テーブル
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_stock_history (
                    date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    asset_type TEXT,
                    data_json TEXT,
                    updated_at_jst TEXT,
                    PRIMARY KEY (date, code)
                )
            """)
            
            # インデックス作成（検索高速化）
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_month ON portfolio_history (snapshot_month)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_stock_history (date)")
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")

def save_daily_data(code: str, asset_type: str, data: Dict[str, Any]) -> bool:
    """
    スクレイピング結果をDBに保存する（バリデーション付き）。
    1日1銘柄につき最新の1レコードのみ保持する (INSERT OR REPLACE)。
    """
    # 基本的なバリデーション
    if not data or "error" in data:
        return False
    
    # 必須項目のチェック (現在値と名称が取得できていること)
    price = data.get("price")
    name = data.get("name")
    if price in [None, "N/A", "--", ""] or name in [None, "N/A", "--", ""]:
        logger.warning(f"Validation failed for {code}: missing price or name. Data not persisted.")
        return False

    now_jst = get_now_jst()
    date_str = now_jst.strftime("%Y-%m-%d")
    updated_at_str = now_jst.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        data_json = json.dumps(data, ensure_ascii=False)
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_stock_history (date, code, asset_type, data_json, updated_at_jst)
                VALUES (?, ?, ?, ?, ?)
            """, (date_str, code, asset_type, data_json, updated_at_str))
            conn.commit()
        return True
    except (sqlite3.Error, TypeError) as e:
        logger.error(f"Failed to save daily data for {code}: {e}")
        return False

def get_daily_data(code: str, date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    指定された日付（デフォルトは当日JST）のキャッシュデータをDBから取得する。
    """
    if not date_str:
        date_str = get_now_jst().strftime("%Y-%m-%d")
        
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data_json, updated_at_jst FROM daily_stock_history 
                WHERE date = ? AND code = ?
            """, (date_str, code))
            row = cursor.fetchone()
            if row:
                data = json.loads(row["data_json"])
                # 取得したデータに更新日時情報を付与して返す
                data["_db_updated_at_jst"] = row["updated_at_jst"]
                return data
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.error(f"Failed to get daily data for {code}: {e}")
    return None

def get_all_daily_data_for_date(date_str: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """
    指定された日付の全データを一括取得し、銘柄コードをキーとした辞書で返す。
    """
    if not date_str:
        date_str = get_now_jst().strftime("%Y-%m-%d")
        
    results = {}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT code, data_json, updated_at_jst FROM daily_stock_history WHERE date = ?", (date_str,))
            rows = cursor.fetchall()
            for row in rows:
                try:
                    data = json.loads(row["data_json"])
                    data["_db_updated_at_jst"] = row["updated_at_jst"]
                    results[row["code"]] = data
                except json.JSONDecodeError:
                    continue
    except sqlite3.Error as e:
        logger.error(f"Failed to get all daily data for date {date_str}: {e}")
    return results

def save_snapshot(portfolio_data: List[Dict[str, Any]]):
    """
    ポートフォリオのスナップショットを保存する。
    同月(YYYY-MM)のデータが既に存在する場合は、一度削除してから保存し直す（月内上書き更新）。
    """
    if not portfolio_data:
        return

    now_jst = get_now_jst()
    snapshot_date = now_jst.strftime("%Y-%m-%d")
    snapshot_month = now_jst.strftime("%Y-%m")

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            conn.execute("BEGIN")
            cursor.execute("DELETE FROM portfolio_history WHERE snapshot_month = ?", (snapshot_month,))
            
            insert_sql = """
                INSERT INTO portfolio_history (
                    snapshot_date, snapshot_month, code, name, asset_type,
                    account_type, security_company, quantity, purchase_price,
                    current_price, market_value, profit_loss, profit_loss_rate,
                    estimated_annual_dividend, industry, memo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            records_to_insert = []
            for item in portfolio_data:
                 records_to_insert.append((
                     snapshot_date,
                     snapshot_month,
                     item.get("code", ""),
                     item.get("name", ""),
                     item.get("asset_type", ""),
                     item.get("account_type", ""),
                     item.get("security_company", ""),
                     _to_float(item.get("quantity")),
                     _to_float(item.get("purchase_price")),
                     _to_float(item.get("price")),
                     _to_float(item.get("market_value")),
                     _to_float(item.get("profit_loss")),
                     _to_float(item.get("profit_loss_rate")),
                     _to_float(item.get("estimated_annual_dividend")),
                     item.get("industry", ""),
                     item.get("memo", "")
                 ))

            cursor.executemany(insert_sql, records_to_insert)
            conn.commit()
            logger.info(f"Snapshot for {snapshot_month} saved/updated with {len(records_to_insert)} records.")
    except sqlite3.Error as e:
        logger.error(f"Failed to save snapshot: {e}")

def get_monthly_summary():
    """月ごとのサマリーを取得する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    snapshot_month,
                    SUM(market_value) as total_market_value,
                    SUM(profit_loss) as total_profit_loss,
                    SUM(estimated_annual_dividend) as total_dividend
                FROM portfolio_history
                GROUP BY snapshot_month
                ORDER BY snapshot_month ASC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        logger.error(f"Failed to get summary: {e}")
        return []

def get_latest_daily_data_all() -> Dict[str, Dict[str, Any]]:
    """
    全銘柄の最新のキャッシュデータを、日付を問わず取得する。
    銘柄コードをキーとした辞書を返す。
    """
    results = {}
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # 各銘柄(code)ごとに最大のdateを持つレコードを取得
            cursor.execute("""
                SELECT t1.code, t1.data_json, t1.updated_at_jst
                FROM daily_stock_history t1
                INNER JOIN (
                    SELECT code, MAX(date) as max_date
                    FROM daily_stock_history
                    GROUP BY code
                ) t2 ON t1.code = t2.code AND t1.date = t2.max_date
            """)
            rows = cursor.fetchall()
            for row in rows:
                try:
                    data = json.loads(row["data_json"])
                    data["_db_updated_at_jst"] = row["updated_at_jst"]
                    results[row["code"]] = data
                except json.JSONDecodeError:
                    continue
    except sqlite3.Error as e:
        logger.error(f"Failed to get latest daily data for all codes: {e}")
    return results

def _to_float(value):
    """安全にfloatに変換するヘルパー"""
    if value is None or value == "N/A" or value == "":
        return 0.0
    try:
        if isinstance(value, str):
            return float(value.replace(",", "").replace("%", ""))
        return float(value)
    except (ValueError, TypeError):
        return 0.0

# モジュール読み込み時にDB初期化を実行
init_db()
