import sqlite3
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_FILE = "portfolio_history.db"
logger = logging.getLogger(__name__)

def init_db():
    """データベースとテーブルを初期化する"""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
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
            # インデックス作成（検索高速化）
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_month ON portfolio_history (snapshot_month)")
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")

def save_snapshot(portfolio_data: List[Dict[str, Any]]):
    """
    ポートフォリオのスナップショットを保存する。
    同月(YYYY-MM)のデータが既に存在する場合は、一度削除してから保存し直す（月内上書き更新）。
    """
    if not portfolio_data:
        return

    now = datetime.now()
    snapshot_date = now.strftime("%Y-%m-%d")
    snapshot_month = now.strftime("%Y-%m")

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # トランザクション開始
            conn.execute("BEGIN")
            
            # 1. 同月の既存データを削除
            cursor.execute("DELETE FROM portfolio_history WHERE snapshot_month = ?", (snapshot_month,))
            
            # 2. 新しいデータを挿入
            for asset in portfolio_data:
                # エラーがある資産や、保有情報がない資産はスキップ
                if "error" in asset or not asset.get("holdings"):
                    continue

                for holding in asset.get("holdings", []):
                    # 必要な値を計算・抽出
                    # portfolio_manager.calculate_holding_values の結果が渡されることを想定していないため
                    # ここで簡易的な値を抽出するが、本来は計算済みの値を渡すのがベスト。
                    # 今回は app.py 側で計算済みの値（analysis API相当）を渡す設計にする。
                    
                    # analysis相当のフラットなデータ構造か、階層構造かによって処理を分ける必要があるが、
                    # 簡略化のため、app.py からは「計算済みのフラットなリスト（analysisで使用しているもの）」を渡してもらう想定で実装する。
                    # しかし、app.pyのget_stocksは階層構造を返す。
                    # そのため、ここで計算するか、app.py側で整形する必要がある。
                    # デグレ防止のため、history_manager内で計算ロジックを持たず、
                    # 呼び出し元で整形されたフラットなデータを受け取る形にするのが安全。
                    # 引数の portfolio_data は「分析ページ用データの holdings_list」を想定する。
                    
                    pass 

            # ここでロジック修正: 引数 portfolio_data は calculate_holding_values 済みのフラットな辞書のリストを受け取る仕様にする
            # 呼び出し元(app.py)で get_portfolio_analysis 相当の処理結果を渡す。
            
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
                 # データバリデーション: 必須項目がない、あるいは計算エラー(N/A)のデータは0として扱うか、スキップするか
                 # ここでは可能な限り保存する方針
                 
                 # itemは分析用のフラットな辞書を想定
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
        # ロールバックはコンテキストマネージャが例外時に自動で行うが、明示的に書いても良い

def get_monthly_summary():
    """
    月ごとのサマリー（総資産、総損益、総配当）を取得する。
    グラフ描画用。
    """
    try:
        with sqlite3.connect(DB_FILE) as conn:
            # row_factoryを設定して辞書形式で取得可能にしてもよい
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

def _to_float(value):
    """安全にfloatに変換するヘルパー。N/AやNoneは0.0にする"""
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
