import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

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
            
            # --- 新規テーブル：分析スナップショット ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_analysis (
                    date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    asset_type TEXT,
                    data_json TEXT,
                    updated_at_jst TEXT,
                    PRIMARY KEY (date, code)
                )
            """)

            # --- 新規テーブル：株価時系列データ ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_price_history (
                    date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    close_price REAL,
                    volume REAL,
                    updated_at_jst TEXT,
                    is_reliable INTEGER DEFAULT 1,
                    PRIMARY KEY (date, code)
                )
            """)

            # --- 新規テーブル：株式分割アラート ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS split_alerts (
                    code TEXT PRIMARY KEY,
                    ratio REAL NOT NULL,
                    detected_date TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    updated_at_jst TEXT NOT NULL
                )
            """)

            # --- 新規テーブル：株式売却履歴・確定損益 (#332) ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS realized_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    account_type TEXT NOT NULL,
                    security_company TEXT,
                    quantity REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    purchase_price REAL NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'JPY',
                    exchange_rate REAL DEFAULT 1.0,
                    sell_amount_jpy REAL NOT NULL,
                    purchase_amount_jpy REAL NOT NULL,
                    realized_pl_jpy REAL NOT NULL,
                    realized_pl_rate REAL NOT NULL,
                    sold_date TEXT NOT NULL,
                    created_at_jst TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_realized_trades_date ON realized_trades (sold_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_realized_trades_code ON realized_trades (code)")

            # --- 新規テーブル：再投資待機資金プール (#332) ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reinvestment_pool (
                    currency TEXT PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 0.0,
                    updated_at_jst TEXT NOT NULL
                )
            """)
            cursor.execute("""
                INSERT OR IGNORE INTO reinvestment_pool (currency, balance, updated_at_jst)
                VALUES ('JPY', 0.0, datetime('now', '+9 hours'))
            """)

            # カラム追加の移行処理 (is_reliable)
            cursor.execute("PRAGMA table_info(stock_price_history)")
            columns = [col[1] for col in cursor.fetchall()]
            if "is_reliable" not in columns:
                logger.info("Adding is_reliable column to stock_price_history...")
                cursor.execute("ALTER TABLE stock_price_history ADD COLUMN is_reliable INTEGER DEFAULT 1")
            
            # インデックス作成（検索高速化）
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_month ON portfolio_history (snapshot_month)")
            
            # 新規テーブル用インデックス
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_date ON daily_analysis (date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_analysis_code_date ON daily_analysis (code, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_date ON stock_price_history (date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_code_date ON stock_price_history (code, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_reliable ON stock_price_history (is_reliable)")

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

def validate_price_data(code: str, price: float, volume: Optional[float], current_price: Optional[float] = None) -> Tuple[bool, str]:
    """
    株価データの妥当性を検証する (Issue #4)
    """
    if price <= 0:
        return False, "Price must be positive"
    
    # 乖離率チェック (前日比または現在値との比較)
    if current_price and current_price > 0:
        diff_ratio = abs(price - current_price) / current_price
        # 50%以上の乖離は異常値（または未検知の分割）として警告
        if diff_ratio > 0.5:
            return False, f"Price deviation too high: {price} vs {current_price} ({diff_ratio*100:.1f}%)"
            
    # 出来高の整数性チェック (配当行等の混入検知)
    if volume is not None:
        if volume < 0:
            return False, "Volume must be non-negative"
        # Yahooの配当行などは volume の位置に 19.08 などの利回りが入ることがある
        if isinstance(volume, float) and not volume.is_integer():
             return False, f"Volume is not integer: {volume}"

    return True, "Valid"

def save_daily_data(code: str, asset_type: str, data: Dict[str, Any]) -> bool:
    """
    スクレイピング結果をDBに保存する（バリデーション付き）。
    1日1銘柄につき最新の1レコードのみ保持する (INSERT OR REPLACE)。
    分析データは daily_analysis、株価・出来高は stock_price_history に保存する。
    """
    # 基本的なバリデーション
    if not data or "error" in data:
        return False
    
    # 必須項目のチェック (現在値と名称が取得できていること)
    price_val = data.get("price")
    name = data.get("name")
    if price_val in [None, "N/A", "--", ""] or name in [None, "N/A", "--", ""]:
        logger.warning(f"Validation failed for {code}: missing price or name. Data not persisted.")
        return False

    now_jst = get_now_jst()
    date_str = now_jst.strftime("%Y-%m-%d")
    updated_at_str = now_jst.strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        data_json = json.dumps(data, ensure_ascii=False)
        
        # 数値変換
        close_price = None
        if isinstance(price_val, str):
            try:
                close_price = float(price_val.replace(",", "")) if price_val not in ["N/A", "--", ""] else None
            except ValueError: pass
        elif isinstance(price_val, (int, float)):
            close_price = float(price_val)
            
        volume = data.get("volume")
        if isinstance(volume, str):
            try:
                volume = float(volume.replace(",", "")) if volume not in ["N/A", "--", ""] else None
            except ValueError:
                volume = None
        elif isinstance(volume, (int, float)):
            volume = float(volume)

        # 詳細バリデーション (Issue #4)
        is_reliable = 1
        if close_price is not None:
            # 取得済みのDB最新値（昨日分など）があれば比較対象にする
            latest_db = get_historical_data_before(code, (now_jst - timedelta(days=1)).strftime("%Y-%m-%d"))
            compare_price = None
            if latest_db:
                try:
                    compare_price = float(str(latest_db.get("price")).replace(",", ""))
                except: pass
            
            is_valid, reason = validate_price_data(code, close_price, volume, compare_price)
            if not is_valid:
                logger.warning(f"Data for {code} marked as unreliable: {reason}")
                is_reliable = 0
                # 極端な異常値（価格0や空データ）は保存を拒否
                if "must be positive" in reason:
                    return False

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # 1. 分析データの保存
            cursor.execute("""
                INSERT OR REPLACE INTO daily_analysis 
                (date, code, asset_type, data_json, updated_at_jst)
                VALUES (?, ?, ?, ?, ?)
            """, (date_str, code, asset_type, data_json, updated_at_str))
            
            # 2. 株価履歴の保存
            cursor.execute("""
                INSERT OR REPLACE INTO stock_price_history 
                (date, code, close_price, volume, updated_at_jst, is_reliable)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (date_str, code, close_price, volume, updated_at_str, is_reliable))
            
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
                FROM stock_price_history 
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

def get_latest_metadata(code: str) -> Optional[Dict[str, Any]]:
    """DB内の全履歴から、名称などの属性が含まれている最新のレコードを取得する（自己修復用）"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # daily_analysis から最新の1件を取得
            cursor.execute("""
                SELECT data_json FROM daily_analysis 
                WHERE code = ?
                ORDER BY date DESC
                LIMIT 1
            """, (code,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["data_json"])
    except Exception as e:
        logger.error(f"Failed to get latest metadata for {code}: {e}")
    return None

def get_latest_daily_data(code: str) -> Optional[Dict[str, Any]]:
    """
    指定された銘柄の最新のキャッシュデータをDB（daily_analysis）から取得する (#323)。
    日付は不問で、最も新しい日付のレコードを1件取得する。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data_json, updated_at_jst FROM daily_analysis 
                WHERE code = ?
                ORDER BY date DESC
                LIMIT 1
            """, (code,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row["data_json"])
                data["_db_updated_at_jst"] = row["updated_at_jst"]
                return data
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.error(f"Failed to get latest daily data for {code}: {e}")
    return None

def get_daily_data(code: str, date_str: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    指定された日付のキャッシュデータをDBから取得する。
    date_str が未指定（デフォルト当日）の場合、当日データがDBに無ければ
    最新の確定データ（get_latest_daily_data）へ安全にフォールバックする (#323)。
    """
    is_default_today = (date_str is None)
    if not date_str:
        date_str = get_now_jst().strftime("%Y-%m-%d")
        
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data_json, updated_at_jst FROM daily_analysis 
                WHERE date = ? AND code = ?
            """, (date_str, code))
            row = cursor.fetchone()
            if row:
                data = json.loads(row["data_json"])
                data["_db_updated_at_jst"] = row["updated_at_jst"]
                return data
    except (sqlite3.Error, json.JSONDecodeError) as e:
        logger.error(f"Failed to get daily data for {code}: {e}")
        return None

    # 当日指定でデータが無かった場合（祝日・休場日など）、直近最新データへフォールバック
    if is_default_today:
        return get_latest_daily_data(code)

    return None

def get_historical_data_before(code: str, date_str: str) -> Optional[Dict[str, Any]]:
    """
    指定された日付（date_str）以前で、最も新しいキャッシュデータをDBから取得する。
    daily_analysis にない場合は stock_price_history から補完する。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # 1. まずは詳細データがある daily_analysis を探す
            cursor.execute("""
                SELECT data_json, updated_at_jst, date FROM daily_analysis 
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
            
            # 2. なければ価格履歴のみの stock_price_history を探す（市場指標の同期データ対策）
            cursor.execute("""
                SELECT close_price, updated_at_jst, date FROM stock_price_history
                WHERE code = ? AND date <= ? AND close_price IS NOT NULL
                ORDER BY date DESC
                LIMIT 1
            """, (code, date_str))
            row = cursor.fetchone()
            if row:
                # app.pyの算出ロジックが文字列を想定している場合があるためキャスト
                return {
                    "price": str(row["close_price"]),
                    "_db_updated_at_jst": row["updated_at_jst"],
                    "_db_date": row["date"]
                }
                
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
            cursor.execute("SELECT code, data_json, updated_at_jst FROM daily_analysis WHERE date = ?", (date_str,))
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
            
            # 2. 再投資待機資金プール残高を取得して総資産に合算 (#332)
            pool_balance = 0.0
            try:
                cursor.execute("SELECT balance FROM reinvestment_pool WHERE currency = 'JPY'")
                p_row = cursor.fetchone()
                if p_row and p_row[0]:
                    pool_balance = float(p_row[0])
            except Exception as pe:
                logger.warning(f"Failed to fetch reinvestment_pool balance during save_snapshot: {pe}")

            summary_market_value = total_market_value + pool_balance

            # 3. 全体サマリーの保存 (INSERT OR REPLACE by snapshot_date)
            cursor.execute("""
                INSERT OR REPLACE INTO portfolio_summary_history (
                    snapshot_date, snapshot_month, total_market_value, total_profit_loss, total_dividend, updated_at_jst
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (snapshot_date, snapshot_month, summary_market_value, total_profit_loss, total_dividend, updated_at_str))
            
            conn.commit()
            logger.info(f"Snapshot and Summary for {snapshot_date} saved/updated. Details: {len(records_to_insert)} records.")
    except sqlite3.Error as e:
        logger.error(f"Failed to save snapshot: {e}")

def get_summary_before(date_str: str, min_market_value: float = 1000000.0) -> Optional[Dict[str, Any]]:
    """
    指定された日付(date_str)以前で、最も新しい有効なサマリーを取得する。
    極端な外れ値（min_market_value未満）やテスト起因の異常データは自動的にスキップし、健全な過去データを探索する (#320)。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM portfolio_summary_history
                WHERE snapshot_date <= ? AND total_market_value >= ?
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (date_str, min_market_value))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # min_market_value を満たすものがない場合は通常の最新1件へフォールバック
            cursor.execute("""
                SELECT * FROM portfolio_summary_history
                WHERE snapshot_date <= ? AND total_market_value > 0
                ORDER BY snapshot_date DESC
                LIMIT 1
            """, (date_str,))
            fallback_row = cursor.fetchone()
            if fallback_row:
                return dict(fallback_row)
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

def get_last_month_end_holdings_snapshot() -> Tuple[Optional[str], Dict[str, Dict[str, Any]]]:
    """
    先月末の最大 snapshot_date における銘柄ごとの合計評価額および情報を取得する。
    
    Returns:
        Tuple[last_month_str, holdings_map]:
            last_month_str: "YYYY-MM" (データがない場合は None)
            holdings_map: { code: {"code": str, "name": str, "market_value": float, "quantity": float, "asset_type": str} }
    """
    now_jst = get_now_jst()
    first_day_of_this_month = now_jst.replace(day=1)
    last_month_date = first_day_of_this_month - timedelta(days=1)
    last_month_str = last_month_date.strftime("%Y-%m")

    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT MAX(snapshot_date) as max_date 
                FROM portfolio_history 
                WHERE snapshot_month = ?
            """, (last_month_str,))
            row = cursor.fetchone()
            if not row or not row["max_date"]:
                return None, {}
            
            max_date = row["max_date"]
            
            cursor.execute("""
                SELECT 
                    code,
                    MAX(name) as name,
                    MAX(asset_type) as asset_type,
                    SUM(market_value) as total_market_value,
                    SUM(quantity) as total_quantity
                FROM portfolio_history
                WHERE snapshot_month = ? AND snapshot_date = ?
                GROUP BY code
            """, (last_month_str, max_date))
            
            rows = cursor.fetchall()
            snapshot_map = {}
            for r in rows:
                code = r["code"]
                snapshot_map[code] = {
                    "code": code,
                    "name": r["name"] or code,
                    "asset_type": r["asset_type"] or "jp_stock",
                    "market_value": float(r["total_market_value"] or 0),
                    "quantity": float(r["total_quantity"] or 0),
                }
            return last_month_str, snapshot_map
    except Exception as e:
        logger.error(f"Error fetching last month end holdings snapshot: {e}")
        return None, {}

def get_monthly_summary():
    """月ごとのサマリーを取得する（各月の最新日のデータを集計）(#332)"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # 1. まずはプール合算済みの全体サマリー (portfolio_summary_history) から各月最新のレコードを取得
            cursor.execute("""
                SELECT 
                    snapshot_month,
                    total_market_value,
                    total_profit_loss,
                    total_dividend
                FROM portfolio_summary_history
                WHERE snapshot_date IN (
                    SELECT MAX(snapshot_date)
                    FROM portfolio_summary_history
                    GROUP BY snapshot_month
                )
                ORDER BY snapshot_month ASC
            """)
            rows = cursor.fetchall()
            if rows:
                return [dict(row) for row in rows]

            # フォールバック (サマリーテーブルが空の場合のみ portfolio_history から集計)
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
                FROM daily_analysis t1
                INNER JOIN (
                    SELECT code, MAX(date) as max_date
                    FROM daily_analysis
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

def round_split_ratio(ratio: float) -> float:
    """検知された分割比率を、代表的な株式分割・併合比率に丸める"""
    common_ratios = [
        0.01, 0.02, 0.04, 0.05, 0.1, 0.2, 0.5,           # 併合 (100:1, 50:1, 25:1, 20:1, 10:1, 5:1, 2:1)
        1.1, 1.15, 1.2, 1.25, 1.3, 1.5,                  # 特殊な小規模分割
        2.0, 2.5, 3.0, 4.0, 5.0, 10.0,                   # 一般的な分割
        15.0, 20.0, 25.0, 50.0, 100.0                    # 大口分割 (NTT 1:25分割等に対応)
    ]
    for r in common_ratios:
        if abs(ratio - r) / r <= 0.05 or abs(ratio - r) <= 0.1:
            return r
    return round(ratio, 4)

def add_split_alert(code: str, ratio: float) -> bool:
    """株式分割アラートを追加・更新する"""
    try:
        now_str = get_now_jst().isoformat()
        today_str = get_now_jst().strftime("%Y-%m-%d")
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO split_alerts (code, ratio, detected_date, status, updated_at_jst)
                VALUES (?, ?, ?, 'pending', ?)
            """, (code, ratio, today_str, now_str))
            conn.commit()
            logger.info(f"Added/Updated split alert for {code} with ratio {ratio}")
            return True
    except Exception as e:
        logger.error(f"Error adding split alert for {code}: {e}")
        return False

def get_pending_split_alerts() -> List[Dict[str, Any]]:
    """保留中の株式分割アラート一覧を取得する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT code, ratio, detected_date, status, updated_at_jst 
                FROM split_alerts 
                WHERE status = 'pending'
            """)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching pending split alerts: {e}")
        return []

def get_all_split_alerts() -> List[Dict[str, Any]]:
    """すべての株式分割アラート履歴（pending, applied, dismissed含む）を取得する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT code, ratio, detected_date, status, updated_at_jst 
                FROM split_alerts 
                ORDER BY updated_at_jst DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching all split alerts: {e}")
        return []

def get_applied_split_alerts() -> List[Dict[str, Any]]:
    """適用済みの株式分割アラート一覧 (status='applied') を取得する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT code, ratio, detected_date, status, updated_at_jst 
                FROM split_alerts 
                WHERE status = 'applied'
                ORDER BY updated_at_jst DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching applied split alerts: {e}")
        return []


def has_pending_split_alert(code: str) -> bool:
    """指定銘柄に保留中の分割アラートがあるか確認する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM split_alerts WHERE code = ? AND status = 'pending'", (code,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking pending split alert for {code}: {e}")
        return False

def update_split_alert_status(code: str, status: str) -> bool:
    """分割アラートのステータスを更新する"""
    if status not in ('pending', 'applied', 'dismissed'):
        return False
    try:
        now_str = get_now_jst().isoformat()
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE split_alerts 
                SET status = ?, updated_at_jst = ? 
                WHERE code = ?
            """, (status, now_str, code))
            conn.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Error updating split alert status for {code}: {e}")
        return False

def get_latest_price_from_db(code: str) -> Optional[float]:
    """DBの時系列データから最新の終値（当日を除く直近）を取得する"""
    try:
        today_str = get_now_jst().strftime("%Y-%m-%d")
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT close_price FROM stock_price_history 
                WHERE code = ? AND date < ? AND close_price IS NOT NULL 
                ORDER BY date DESC LIMIT 1
            """, (code, today_str))
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Error fetching latest price from DB for {code}: {e}")
        return None

# ==========================================
# 株式売却履歴・確定損益 ＆ 再投資待機資金プール (#332)
# ==========================================

def add_realized_trade(
    code: str,
    name: str,
    asset_type: str,
    account_type: str,
    quantity: float,
    sell_price: float,
    purchase_price: float,
    sold_date: str,
    security_company: str = "",
    currency: str = "JPY",
    exchange_rate: float = 1.0
) -> int:
    """株式売却履歴を保存し、確定損益を記録する"""
    try:
        now_str = get_now_jst().strftime("%Y-%m-%d %H:%M:%S")
        sell_amount_jpy = sell_price * quantity * exchange_rate
        purchase_amount_jpy = purchase_price * quantity * exchange_rate
        realized_pl_jpy = sell_amount_jpy - purchase_amount_jpy
        realized_pl_rate = (realized_pl_jpy / purchase_amount_jpy * 100.0) if purchase_amount_jpy > 0 else 0.0

        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO realized_trades (
                    code, name, asset_type, account_type, security_company,
                    quantity, sell_price, purchase_price, currency, exchange_rate,
                    sell_amount_jpy, purchase_amount_jpy, realized_pl_jpy, realized_pl_rate,
                    sold_date, created_at_jst
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, name, asset_type, account_type, security_company,
                quantity, sell_price, purchase_price, currency, exchange_rate,
                sell_amount_jpy, purchase_amount_jpy, realized_pl_jpy, realized_pl_rate,
                sold_date, now_str
            ))
            conn.commit()
            trade_id = cursor.lastrowid
            logger.info(f"Recorded realized trade #{trade_id} for {code}: PL={realized_pl_jpy:+.1f} JPY ({realized_pl_rate:+.2f}%)")
            return trade_id
    except Exception as e:
        logger.error(f"Failed to add realized trade for {code}: {e}")
        raise

def get_realized_trades(year: Optional[int] = None) -> List[Dict[str, Any]]:
    """売却履歴を取得する（年指定可能）"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if year:
                cursor.execute("""
                    SELECT * FROM realized_trades 
                    WHERE strftime('%Y', sold_date) = ?
                    ORDER BY sold_date DESC, id DESC
                """, (str(year),))
            else:
                cursor.execute("""
                    SELECT * FROM realized_trades 
                    ORDER BY sold_date DESC, id DESC
                """)
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get realized trades: {e}")
        return []

def get_realized_summary(year: Optional[int] = None) -> Dict[str, Any]:
    """確定損益のサマリー（合計損益、取引回数、勝率など）を取得する"""
    trades = get_realized_trades(year)
    total_pl = sum(t["realized_pl_jpy"] for t in trades)
    total_sell_amount = sum(t["sell_amount_jpy"] for t in trades)
    wins = [t for t in trades if t["realized_pl_jpy"] > 0]
    losses = [t for t in trades if t["realized_pl_jpy"] < 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0

    return {
        "year": year or datetime.now().year,
        "total_pl_jpy": round(total_pl, 1),
        "total_sell_amount_jpy": round(total_sell_amount, 1),
        "trade_count": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(win_rate, 1)
    }

def get_reinvestment_pool_balance(currency: str = "JPY") -> float:
    """再投資待機資金プールの残高を取得する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM reinvestment_pool WHERE currency = ?", (currency,))
            row = cursor.fetchone()
            return float(row[0]) if row and row[0] is not None else 0.0
    except Exception as e:
        logger.error(f"Failed to get reinvestment pool balance for {currency}: {e}")
        return 0.0

def update_reinvestment_pool_balance(delta: float, currency: str = "JPY") -> float:
    """再投資待機資金プールの残高を増減させる（0円未満にはならないようガード）"""
    try:
        now_str = get_now_jst().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM reinvestment_pool WHERE currency = ?", (currency,))
            row = cursor.fetchone()
            current_balance = float(row[0]) if row and row[0] is not None else 0.0
            
            # 0円未満にならないようクランプ
            new_balance = max(0.0, current_balance + delta)
            
            cursor.execute("""
                INSERT INTO reinvestment_pool (currency, balance, updated_at_jst)
                VALUES (?, ?, ?)
                ON CONFLICT(currency) DO UPDATE SET balance = excluded.balance, updated_at_jst = excluded.updated_at_jst
            """, (currency, new_balance, now_str))
            conn.commit()
            logger.info(f"Updated reinvestment pool ({currency}): {current_balance} -> {new_balance} (delta={delta:+.1f})")
            return new_balance
    except Exception as e:
        logger.error(f"Failed to update reinvestment pool balance: {e}")
        return 0.0

def set_reinvestment_pool_balance(balance: float, currency: str = "JPY") -> float:
    """再投資待機資金プールの残高を直接設定・リセットする"""
    try:
        safe_balance = max(0.0, float(balance))
        now_str = get_now_jst().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reinvestment_pool (currency, balance, updated_at_jst)
                VALUES (?, ?, ?)
                ON CONFLICT(currency) DO UPDATE SET balance = excluded.balance, updated_at_jst = excluded.updated_at_jst
            """, (currency, safe_balance, now_str))
            conn.commit()
            logger.info(f"Directly set reinvestment pool ({currency}) balance to {safe_balance}")
            return safe_balance
    except Exception as e:
        logger.error(f"Failed to set reinvestment pool balance: {e}")
        return 0.0

# モジュール読み込み時にDB初期化を実行
init_db()
