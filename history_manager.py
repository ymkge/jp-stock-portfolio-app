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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_code_date ON daily_stock_history (code, date)")

            # --- ポートフォリオサマリーテーブルの移行処理 (snapshot_month PK -> snapshot_date PK) ---
            cursor.execute("PRAGMA table_info(portfolio_summary_history)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if columns and "snapshot_month" in columns and "snapshot_date" not in columns:
                logger.info("Migrating portfolio_summary_history to daily schema...")
                # 1. 新しいテーブルを作成
                cursor.execute("""
                    CREATE TABLE portfolio_summary_history_new (
                        snapshot_date TEXT PRIMARY KEY,
                        snapshot_month TEXT,
                        total_market_value REAL,
                        total_profit_loss REAL,
                        total_dividend REAL,
                        updated_at_jst TEXT
                    )
                """)
                # 2. データを移行 (updated_at_jst から日付を抽出して PK にする)
                cursor.execute("""
                    INSERT INTO portfolio_summary_history_new (snapshot_date, snapshot_month, total_market_value, total_profit_loss, total_dividend, updated_at_jst)
                    SELECT 
                        COALESCE(SUBSTR(updated_at_jst, 1, 10), snapshot_month || '-01'),
                        snapshot_month,
                        total_market_value,
                        total_profit_loss,
                        total_dividend,
                        updated_at_jst
                    FROM portfolio_summary_history
                """)
                # 3. 旧テーブルを削除してリネーム
                cursor.execute("DROP TABLE portfolio_summary_history")
                cursor.execute("ALTER TABLE portfolio_summary_history_new RENAME TO portfolio_summary_history")
                logger.info("Migration of portfolio_summary_history completed.")
            else:
                # 新規作成用
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio_summary_history (
                        snapshot_date TEXT PRIMARY KEY,
                        snapshot_month TEXT,
                        total_market_value REAL,
                        total_profit_loss REAL,
                        total_dividend REAL,
                        updated_at_jst TEXT
                    )
                """)
            
            # 既存データからのマイグレーション（サマリーテーブルが空の場合のみ実行）
            cursor.execute("SELECT COUNT(*) FROM portfolio_summary_history")
            if cursor.fetchone()[0] == 0:
                logger.info("Migrating existing portfolio_history to portfolio_summary_history...")
                cursor.execute("""
                    INSERT INTO portfolio_summary_history (snapshot_date, snapshot_month, total_market_value, total_profit_loss, total_dividend, updated_at_jst)
                    SELECT 
                        snapshot_date,
                        snapshot_month,
                        SUM(market_value),
                        SUM(profit_loss),
                        SUM(estimated_annual_dividend),
                        MAX(snapshot_date) || ' 00:00:00'
                    FROM portfolio_history
                    GROUP BY snapshot_date
                """)
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
        # 修正: close_price と volume を抽出して保存 (数値変換含む)
        close_price = data.get("price")
        if isinstance(close_price, str):
            # 文字列の場合はカンマを除去して変換
            try:
                close_price = float(close_price.replace(",", "")) if close_price not in ["N/A", "--", ""] else None
            except ValueError:
                close_price = None
            
        volume = data.get("volume")
        if isinstance(volume, str):
            try:
                volume = int(float(volume.replace(",", ""))) if volume not in ["N/A", "--", ""] else None
            except ValueError:
                volume = None

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO daily_stock_history 
                (date, code, asset_type, data_json, updated_at_jst, close_price, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (date_str, code, asset_type, data_json, updated_at_str, close_price, volume))
            conn.commit()
        return True
    except (sqlite3.Error, TypeError) as e:
        logger.error(f"Failed to save daily data for {code}: {e}")
        return False

def get_historical_data_for_analysis(code: str, limit: int = 300) -> List[Dict[str, Any]]:
    """分析用にDBから過去の履歴データを取得する（最新順、最大約1年分）"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, close_price, volume 
                FROM daily_stock_history 
                WHERE code = ? AND close_price IS NOT NULL
                ORDER BY date DESC 
                LIMIT ?
            """, (code, limit))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append({
                    "date": row["date"],
                    "closePrice": row["close_price"],
                    "volume": row["volume"]
                })
            return results
    except Exception as e:
        logger.info(f"Historical data not available for {code} in DB yet: {e}")
        return []

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

def get_historical_data_before(code: str, date_str: str) -> Optional[Dict[str, Any]]:
    """
    指定された日付（date_str）以前で、最も新しいキャッシュデータをDBから取得する。
    休業日などを考慮し、指定日にデータがない場合に過去に遡って最新のものを取得する。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data_json, updated_at_jst, date FROM daily_stock_history 
                WHERE code = ? AND date <= ?
                ORDER BY date DESC
                LIMIT 1
            """, (code, date_str))
            row = cursor.fetchone()
            if row:
                data = json.loads(row["data_json"])
                data["_db_updated_at_jst"] = row["updated_at_jst"]
                data["_db_date"] = row["date"]
                return data
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.error(f"Failed to get historical data for {code} before {date_str}: {e}")
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
    銘柄詳細(portfolio_history)と全体サマリー(portfolio_summary_history)の両方を保存する。
    1日につき最新の1レコードを保持する。
    """
    if not portfolio_data:
        return

    now_jst = get_now_jst()
    snapshot_date = now_jst.strftime("%Y-%m-%d")
    snapshot_month = now_jst.strftime("%Y-%m")
    updated_at_str = now_jst.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            conn.execute("BEGIN")
            
            # 1. 銘柄詳細の保存 (その日の既存データを削除して再挿入)
            cursor.execute("DELETE FROM portfolio_history WHERE snapshot_date = ?", (snapshot_date,))
            
            insert_detail_sql = """
                INSERT INTO portfolio_history (
                    snapshot_date, snapshot_month, code, name, asset_type,
                    account_type, security_company, quantity, purchase_price,
                    current_price, market_value, profit_loss, profit_loss_rate,
                    estimated_annual_dividend, industry, memo
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            records_to_insert = []
            total_market_value = 0.0
            total_profit_loss = 0.0
            total_dividend = 0.0

            for item in portfolio_data:
                 mv = _to_float(item.get("market_value"))
                 pl = _to_float(item.get("profit_loss"))
                 div = _to_float(item.get("estimated_annual_dividend"))
                 
                 total_market_value += mv
                 total_profit_loss += pl
                 total_dividend += div

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
                     mv,
                     pl,
                     _to_float(item.get("profit_loss_rate")),
                     div,
                     item.get("industry", ""),
                     item.get("memo", "")
                 ))

            cursor.executemany(insert_detail_sql, records_to_insert)
            
            # 2. 全体サマリーの保存 (INSERT OR REPLACE by snapshot_date)
            cursor.execute("""
                INSERT OR REPLACE INTO portfolio_summary_history (
                    snapshot_date, snapshot_month, total_market_value, total_profit_loss, total_dividend, updated_at_jst
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (snapshot_date, snapshot_month, total_market_value, total_profit_loss, total_dividend, updated_at_str))
            
            conn.commit()
            logger.info(f"Snapshot and Summary for {snapshot_date} saved/updated. Details: {len(records_to_insert)} records.")
    except sqlite3.Error as e:
        logger.error(f"Failed to save snapshot: {e}")

def get_summary_before(date_str: str) -> Optional[Dict[str, Any]]:
    """
    指定された日付(date_str)以前で、最も新しいサマリーを取得する。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM portfolio_summary_history
                WHERE snapshot_date <= ?
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (date_str,))
            row = cursor.fetchone()
            if row:
                return dict(row)
    except sqlite3.Error as e:
        logger.error(f"Failed to get summary before {date_str}: {e}")
    return None

def get_previous_summary(exclude_month: str) -> Optional[Dict[str, Any]]:
    """
    [互換性維持用] 指定された月(exclude_month)の初日以前の直近サマリーを取得する。
    """
    first_day_of_month = f"{exclude_month}-01"
    # 前月末のデータを取得するために、指定月の初日より前を検索
    try:
        target_date = (datetime.strptime(first_day_of_month, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        return get_summary_before(target_date)
    except ValueError:
        return None

def get_monthly_summary():
    """月ごとのサマリーを取得する（各月の最新日のデータを集計）"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # 各月の最新の snapshot_date を特定し、その日のデータのみを集計
            cursor.execute("""
                SELECT 
                    snapshot_month,
                    SUM(market_value) as total_market_value,
                    SUM(profit_loss) as total_profit_loss,
                    SUM(estimated_annual_dividend) as total_dividend
                FROM portfolio_history
                WHERE snapshot_date IN (
                    SELECT MAX(snapshot_date)
                    FROM portfolio_history
                    GROUP BY snapshot_month
                )
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
