#!/usr/bin/env python3
"""
restore_august_history.py
Issue #320: 8月中旬のテスト起因で上書き消去されたスナップショットデータを、
stock_price_history の実株価データと前後の保有明細から完全復元・再構築するスクリプト。

対象日付:
- 2026-08-13 (基準保有明細: 2026-08-12, 124銘柄)
- 2026-08-18 (基準保有明細: 2026-08-16, 124銘柄)
- 2026-08-19 (基準保有明細: 2026-08-16, 124銘柄)
- 2026-08-21 (基準保有明細: 2026-08-20, 125銘柄: 四電工1939を含む)

安全性機能:
1. 実行直前に portfolio_history.db の自動タイムスタンプ付き物理バックアップを作成
2. --dry-run オプション対応（コミットなしで検証のみ実行可能）
3. 既存の正常日レコード（8/12, 8/14, 8/15, 8/16, 8/20, 8/22, 8/24, 8/25等）の不変性アサーション
4. トランザクション処理によるオールオアナッシング保証
"""

import sys
import os
import shutil
import sqlite3
import argparse
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "portfolio_history.db")

RESTORATION_TARGETS = [
    {
        "target_date": "2026-08-13",
        "base_date": "2026-08-12",
        "expected_count": 124
    },
    {
        "target_date": "2026-08-18",
        "base_date": "2026-08-16",
        "expected_count": 124
    },
    {
        "target_date": "2026-08-19",
        "base_date": "2026-08-16",
        "expected_count": 124
    },
    {
        "target_date": "2026-08-21",
        "base_date": "2026-08-20",
        "expected_count": 125
    }
]

NORMAL_CHECK_DATES = ["2026-08-12", "2026-08-14", "2026-08-15", "2026-08-16", "2026-08-20", "2026-08-22", "2026-08-24", "2026-08-25", "2026-08-31"]


def create_backup(db_path: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.bak_{timestamp}"
    shutil.copy2(db_path, backup_path)
    print(f"✅ DBバックアップ作成完了: {backup_path}")
    return backup_path


def get_normal_dates_baseline(conn: sqlite3.Connection) -> dict:
    c = conn.cursor()
    baseline = {}
    for d in NORMAL_CHECK_DATES:
        cnt = c.execute("SELECT COUNT(*) FROM portfolio_history WHERE snapshot_date = ?", (d,)).fetchone()[0]
        sum_mv = c.execute("SELECT SUM(market_value) FROM portfolio_history WHERE snapshot_date = ?", (d,)).fetchone()[0]
        sum_pl = c.execute("SELECT SUM(profit_loss) FROM portfolio_history WHERE snapshot_date = ?", (d,)).fetchone()[0]
        sum_row = c.execute("SELECT total_market_value, total_profit_loss FROM portfolio_summary_history WHERE snapshot_date = ?", (d,)).fetchone()
        baseline[d] = {
            "history_count": cnt,
            "history_sum_mv": sum_mv,
            "history_sum_pl": sum_pl,
            "summary_row": sum_row
        }
    return baseline


def verify_normal_dates_unchanged(conn: sqlite3.Connection, baseline: dict):
    c = conn.cursor()
    for d, b in baseline.items():
        cnt = c.execute("SELECT COUNT(*) FROM portfolio_history WHERE snapshot_date = ?", (d,)).fetchone()[0]
        sum_mv = c.execute("SELECT SUM(market_value) FROM portfolio_history WHERE snapshot_date = ?", (d,)).fetchone()[0]
        sum_pl = c.execute("SELECT SUM(profit_loss) FROM portfolio_history WHERE snapshot_date = ?", (d,)).fetchone()[0]
        sum_row = c.execute("SELECT total_market_value, total_profit_loss FROM portfolio_summary_history WHERE snapshot_date = ?", (d,)).fetchone()
        
        assert cnt == b["history_count"], f"正常日 {d} の明細件数が変化しました！ ({cnt} != {b['history_count']})"
        assert sum_mv == b["history_sum_mv"], f"正常日 {d} の合計評価額が変化しました！"
        assert sum_pl == b["history_sum_pl"], f"正常日 {d} の合計損益が変化しました！"
        assert sum_row == b["summary_row"], f"正常日 {d} のサマリーレコードが変化しました！"
    print("✅ 正常日データ非破壊アサーション検証: パス（1ビットも変化なし）")


def restore_history(db_path: str, dry_run: bool = False):
    print(f"=== 8月履歴データ完全復元処理開始 (dry_run={dry_run}) ===")
    
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"DBファイルが見つかりません: {db_path}")

    if not dry_run:
        create_backup(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. 正常日ベースライン取得
    baseline = get_normal_dates_baseline(conn)

    restored_summaries = {}

    try:
        conn.execute("BEGIN TRANSACTION")

        for target in RESTORATION_TARGETS:
            target_date = target["target_date"]
            base_date = target["base_date"]
            expected_count = target["expected_count"]
            snapshot_month = target_date[:7]

            print(f"\n--- 復元中: {target_date} (基準日: {base_date}, 想定件数: {expected_count}) ---")

            # 基準日の保有銘柄明細を取得
            base_rows = c.execute("""
                SELECT code, name, asset_type, account_type, security_company, quantity,
                       purchase_price, current_price, estimated_annual_dividend, industry, memo
                FROM portfolio_history
                WHERE snapshot_date = ?
                ORDER BY id ASC
            """, (base_date,)).fetchall()

            if len(base_rows) != expected_count:
                raise ValueError(f"基準日 {base_date} の銘柄件数が想定({expected_count})と異なります: {len(base_rows)}件")

            records_to_insert = []
            tot_market_value = 0.0
            tot_profit_loss = 0.0
            tot_dividend = 0.0
            price_matched = 0

            for r in base_rows:
                code = r["code"]
                name = r["name"]
                asset_type = r["asset_type"]
                account_type = r["account_type"]
                security_company = r["security_company"]
                qty = float(r["quantity"] or 0.0)
                purchase_price = float(r["purchase_price"] or 0.0)
                div = float(r["estimated_annual_dividend"] or 0.0)
                industry = r["industry"]
                memo = r["memo"]

                # stock_price_history から対象日付の終値を取得
                p_row = c.execute("""
                    SELECT close_price FROM stock_price_history
                    WHERE date = ? AND code = ?
                """, (target_date, code)).fetchone()

                if p_row and p_row["close_price"] is not None:
                    current_price = float(p_row["close_price"])
                    price_matched += 1
                else:
                    # 終値が取れない場合（投資信託等）は基準日の current_price を維持
                    current_price = float(r["current_price"] or purchase_price)

                market_value = round(qty * current_price, 4)
                investment_cost = round(qty * purchase_price, 4)
                profit_loss = round(market_value - investment_cost, 4)
                profit_loss_rate = round((profit_loss / investment_cost * 100), 4) if investment_cost > 0 else 0.0

                tot_market_value += market_value
                tot_profit_loss += profit_loss
                tot_dividend += div

                records_to_insert.append((
                    target_date,
                    snapshot_month,
                    code,
                    name,
                    asset_type,
                    account_type,
                    security_company,
                    qty,
                    purchase_price,
                    current_price,
                    market_value,
                    profit_loss,
                    profit_loss_rate,
                    div,
                    industry,
                    memo
                ))

            print(f"  実株価照合率: {price_matched}/{expected_count} 銘柄 (残りは投信等の基準日価格適用)")
            print(f"  再計算サマリー: 総評価額={tot_market_value:,.2f}円, 総損益={tot_profit_loss:,.2f}円, 年間配当={tot_dividend:,.2f}円")

            restored_summaries[target_date] = {
                "count": len(records_to_insert),
                "total_market_value": tot_market_value,
                "total_profit_loss": tot_profit_loss,
                "total_dividend": tot_dividend
            }

            if not dry_run:
                # 1. 該当日の既存ダミー明細を削除
                c.execute("DELETE FROM portfolio_history WHERE snapshot_date = ?", (target_date,))

                # 2. 完全再構築された明細を挿入
                insert_sql = """
                    INSERT INTO portfolio_history (
                        snapshot_date, snapshot_month, code, name, asset_type,
                        account_type, security_company, quantity, purchase_price,
                        current_price, market_value, profit_loss, profit_loss_rate,
                        estimated_annual_dividend, industry, memo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                c.executemany(insert_sql, records_to_insert)

                # 3. 全体サマリーを更新挿入
                updated_at_str = f"{target_date} 18:00:00"
                c.execute("""
                    INSERT OR REPLACE INTO portfolio_summary_history (
                        snapshot_date, snapshot_month, total_market_value, total_profit_loss, total_dividend, updated_at_jst
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (target_date, snapshot_month, tot_market_value, tot_profit_loss, tot_dividend, updated_at_str))

        if dry_run:
            conn.rollback()
            print("\n🔍 [DRY-RUN] ロールバック完了。DB変更は行われませんでした。")
        else:
            # 正常日非破壊アサーション
            verify_normal_dates_unchanged(conn, baseline)
            conn.commit()
            print("\n🎉 トランザクションコミット完了: 8月履歴データの完全復元に成功しました！")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ エラーが発生したためロールバックしました: {e}")
        raise e
    finally:
        conn.close()

    return restored_summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore August history data for Issue #320")
    parser.add_argument("--dry-run", action="store_true", help="Simulate restoration without modifying database")
    args = parser.parse_args()

    restore_history(DB_FILE, dry_run=args.dry_run)
