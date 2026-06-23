
import time
import random
import logging
import shutil
import os
import sys
from datetime import datetime, timedelta
import sqlite3
import json

import argparse

import statistics

# 既存のモジュールをインポート
try:
    from scraper import JPStockScraper
    from portfolio_manager import load_portfolio
    from history_manager import init_db, JST
except ImportError as e:
    print(f"Error: 必要なモジュールが見つかりません: {e}")
    sys.exit(1)

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("sync_history.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DB_FILE = "portfolio_history.db"

class HistorySyncTool:
    def __init__(self):
        self.scraper = JPStockScraper()
        self.max_pages = 13
        self.processed_count = 0
        self.success_count = 0
        self.error_list = []
        
    def backup_db(self):
        """実行前にDBの物理バックアップを作成する"""
        if os.path.exists(DB_FILE):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{DB_FILE}.sync_bak_{timestamp}"
            shutil.copy2(DB_FILE, backup_name)
            logger.info(f"Database backup created: {backup_name}")
        else:
            logger.warning("DB_FILE not found. Initializing new DB.")
            init_db()

    def cleanup_invalid_data(self, date_str="2026-04-27"):
        """指定日以降のデータを削除して再同期を可能にする"""
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                # 新テーブル両方を掃除
                cursor.execute("DELETE FROM daily_analysis WHERE date >= ?", (date_str,))
                cursor.execute("DELETE FROM stock_price_history WHERE date >= ?", (date_str,))
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    logger.info(f"Cleaned up records from {date_str} onwards for re-sync")
        except Exception as e:
            logger.error(f"Failed to cleanup data: {e}")

    def delete_stock_history(self, code):
        """指定銘柄の履歴データをDBから完全に削除する"""
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM daily_analysis WHERE code = ?", (code,))
                cursor.execute("DELETE FROM stock_price_history WHERE code = ?", (code,))
                logger.info(f"Deleted existing history for {code} from DB.")
        except Exception as e:
            logger.error(f"Failed to delete history for {code}: {e}")

    def get_existing_dates(self, code):
        """指定銘柄のDB内にある日付セットを取得する"""
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT date FROM stock_price_history WHERE code = ? AND close_price IS NOT NULL", 
                    (code,)
                )
                return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error checking DB for {code}: {e}")
            return set()

    def get_db_prices_for_dates(self, code, dates):
        """指定された日付リストに対応するDB内の終値を取得する"""
        if not dates: return {}
        try:
            placeholders = ','.join(['?'] * len(dates))
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                query = f"SELECT date, close_price FROM stock_price_history WHERE code = ? AND date IN ({placeholders})"
                cursor.execute(query, [code] + list(dates))
                return {row[0]: row[1] for row in cursor.fetchall() if row[1] is not None}
        except Exception as e:
            logger.error(f"Error fetching DB prices for {code}: {e}")
            return {}

    def apply_split_adjustment(self, code, ratio):
        """DB内の価格と出来高を一括補正する"""
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                # 価格を割り、出来高を掛ける (整数化)
                cursor.execute("""
                    UPDATE stock_price_history 
                    SET close_price = close_price / ?, 
                        volume = CAST(volume * ? AS INTEGER),
                        updated_at_jst = ?
                    WHERE code = ?
                """, (ratio, ratio, datetime.now(JST).isoformat(), code))
                
                updated_rows = cursor.rowcount
                conn.commit()
                logger.info(f"Successfully applied split adjustment (Ratio: {ratio:.4f}) to {updated_rows} records for {code}")
                return updated_rows
        except Exception as e:
            logger.error(f"Failed to apply split adjustment for {code}: {e}")
            return 0

    def save_histories(self, histories):
        """取得した時系列データをDBに保存し、統計情報を返す"""
        if not histories:
            return None
        
        from history_manager import validate_price_data
        
        success_count = 0
        valid_prices = []
        valid_dates = []
        
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                updated_at_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
                
                for h in histories:
                    code = h.get('code')
                    date = h.get('date')
                    price = float(h.get('closePrice', 0))
                    volume = h.get('volume')
                    if isinstance(volume, str):
                        try: volume = float(volume.replace(',', ''))
                        except: volume = None
                    
                    # バリデーション (Issue #4)
                    is_valid, reason = validate_price_data(code, price, volume, current_price=None)
                    is_reliable = 1
                    if not is_valid:
                        logger.warning(f"Row for {code} on {date} marked as unreliable: {reason}")
                        is_reliable = 0
                        # 致命的なエラーはスキップ
                        if "must be positive" in reason: continue

                    cursor.execute("""
                        INSERT OR REPLACE INTO stock_price_history 
                        (date, code, close_price, volume, updated_at_jst, is_reliable)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (date, code, price, volume, updated_at_str, is_reliable))
                    
                    if is_reliable:
                        success_count += 1
                        valid_prices.append(price)
                        valid_dates.append(date)
                
                conn.commit()
                
            if not valid_prices: return None
            
            return {
                'count': success_count,
                'start_date': min(valid_dates),
                'end_date': max(valid_dates),
                'avg_price': sum(valid_prices) / len(valid_prices)
            }
        except Exception as e:
            logger.error(f"Failed to save histories: {e}")
            return None

    def get_target_date(self):
        """JSTに基づき、あるべき最新の営業日（ターゲット日）を算出する"""
        now_jst = datetime.now(JST)
        
        # 市場確定時刻 (16:30) を過ぎているか判定
        is_after_market = now_jst.hour > 16 or (now_jst.hour == 16 and now_jst.minute >= 30)
        
        target_dt = now_jst
        if not is_after_market:
            # 16:30前なら前日をターゲットにする
            target_dt -= timedelta(days=1)
            
        # 週末（土日）の調整
        while target_dt.weekday() >= 5: # 5=Sat, 6=Sun
            target_dt -= timedelta(days=1)
            
        return target_dt.strftime("%Y-%m-%d")

    def get_db_health(self, code):
        """指定銘柄のDB内最新日と有効レコード数を取得する"""
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT MAX(date), COUNT(*) FROM stock_price_history WHERE code = ? AND close_price IS NOT NULL", 
                    (code,)
                )
                row = cursor.fetchone()
                return row[0] if row else None, row[1] if row else 0
        except Exception as e:
            logger.error(f"Error checking health for {code}: {e}")
            return None, 0

    def sync_stock(self, code, name="Unknown"):
        """1銘柄の履歴を同期する"""
        # ... (既存のロジックを維持しつつ、早期終了条件を強化) ...
        existing_dates = self.get_existing_dates(code)
        # JSTでの今日の日付を取得 (当日分は除外するため)
        today_jst = datetime.now(JST).strftime("%Y-%m-%d")
        
        all_histories_to_save = []
        # URL正規化
        full_code = code if (code.endswith('.T') or code.endswith('.O')) else f"{code}.T"
        base_url = f"https://finance.yahoo.co.jp/quote/{full_code}/history"
        
        # まず現在値を把握 (銘柄名の取得のみに使用)
        stock_name = name
        try:
            main_url = f"https://finance.yahoo.co.jp/quote/{full_code}"
            res_m = self.scraper._make_request(main_url)
            if res_m:
                json_m = self.scraper._extract_next_data(res_m.text)
                m_data = self.scraper._scavenge_common_data(res_m.text, json_m)
                scraped_name = m_data.get('name')
                if scraped_name: stock_name = scraped_name
        except: pass

        split_adjusted = False

        for page in range(1, self.max_pages + 1):
            if page == 1:
                url = base_url
            else:
                url = f"{base_url}?page={page}"
            
            res = self.scraper._make_request(url)
            if not res:
                raise Exception(f"HTTP Error or connection failed at page {page}")
                
            if res.status_code == 403:
                logger.critical("!!! 403 Forbidden detected. Circuit breaker activated !!!")
                sys.exit(1)

            json_data = self.scraper._extract_next_data(res.text)
            raw_histories = self.scraper._parse_histories(json_data if json_data else res.text, current_price=None)
            
            if not raw_histories:
                break

            if page == 1 and raw_histories and not split_adjusted:
                yahoo_dates = [h['date'] for h in raw_histories if 'date' in h]
                db_prices = self.get_db_prices_for_dates(code, yahoo_dates)
                
                if db_prices:
                    ratios = []
                    for h in raw_histories:
                        d = h.get('date')
                        y_p = float(h.get('closePrice', 0))
                        if d in db_prices and y_p > 0:
                            ratios.append(db_prices[d] / y_p)
                    
                    if ratios:
                        median_ratio = statistics.median(ratios)
                        if abs(median_ratio - 1.0) > 0.15:
                            logger.warning(f"!!! SPLIT DETECTED for {code} !!! Estimated Ratio: {median_ratio:.4f}")
                            self.apply_split_adjustment(code, median_ratio)
                            split_adjusted = True
            
            new_data_found_on_page = False
            page_data_to_add = []
            for h in raw_histories:
                raw_dt = h.get('baseDatetime')
                if not raw_dt: continue
                
                try:
                    dt_obj = datetime.strptime(raw_dt.replace('-', '/'), '%Y/%m/%d')
                    iso_date = dt_obj.strftime('%Y-%m-%d')
                except ValueError: continue
                
                h['date'] = iso_date
                h['code'] = code
                if h['date'] >= today_jst: continue
                
                if not split_adjusted and h['date'] in existing_dates:
                    continue
                
                page_data_to_add.append(h)
                new_data_found_on_page = True
            
            all_histories_to_save.extend(page_data_to_add)
            
            if split_adjusted:
                logger.info(f"Splits adjusted and Page 1 records prepared. Stopping early for {code}.")
                break

            if not new_data_found_on_page and len(existing_dates) >= 250:
                logger.info(f"No new data on page {page} and DB has sufficient records. Stopping early.")
                break
                
            time.sleep(1.2 + random.uniform(0, 0.8))
            
        stats = self.save_histories(all_histories_to_save)
        return stats, stock_name

    def run(self, force_resync_code=None):
        """メイン実行ループ (スマートスキップ対応)"""
        start_time = time.time()
        self.backup_db()
        
        portfolio = load_portfolio()
        jp_stocks = [s for s in portfolio if s.get('asset_type') == 'jp_stock']
        
        # 市場指標のロード
        try:
            with open("highlight_rules.json", "r", encoding="utf-8") as f:
                rules = json.load(f)
                market_indices = rules.get("market_indices", [])
                loaded_indices_count = 0
                for idx in market_indices:
                    # 日経平均先物 (5040469.O) は過去データがないため同期対象外とする
                    if idx['code'] == '5040469.O':
                        logger.info(f"Skipping market index {idx['name']} ({idx['code']}) from sync (no historical data on Yahoo Finance).")
                        continue
                    if not any(s['code'] == idx['code'] for s in jp_stocks):
                        jp_stocks.append({
                            'code': idx['code'], 
                            'name': idx['name'],
                            'asset_type': 'market_index'
                        })
                    loaded_indices_count += 1
                logger.info(f"Loaded {loaded_indices_count} market indices for sync.")
        except Exception as e:
            logger.error(f"Failed to load market indices: {e}")

        if force_resync_code:
            target_stocks = [s for s in jp_stocks if s['code'] == force_resync_code]
            if not target_stocks:
                target_stocks = [{'code': force_resync_code, 'name': 'Target Stock'}]
            logger.info(f"FORCE RESYNC mode for {force_resync_code}")
            self.delete_stock_history(force_resync_code)
            jp_stocks = target_stocks

        target_date = self.get_target_date()
        total = len(jp_stocks)
        logger.info(f"Starting sync for {total} items. Target Date: {target_date}")
        
        request_count = 0
        skip_count = 0
        
        for i, stock in enumerate(jp_stocks, 1):
            code = stock['code']
            name = stock.get('name', 'Unknown')
            
            # 事前診断 (スマートスキップ)
            if not force_resync_code:
                latest_date, record_count = self.get_db_health(code)
                if latest_date and latest_date >= target_date and record_count >= 250:
                    logger.info(f"[{i}/{total}] SKIP: {code} ({name}) | Already up-to-date (Latest: {latest_date}, Records: {record_count})")
                    skip_count += 1
                    continue

            try:
                request_count += 1
                stats, real_name = self.sync_stock(code, name)
                if stats:
                    self.success_count += 1
                    msg = (f"[{i}/{total}] SUCCESS: {code} ({real_name}) | "
                           f"New Records: {stats['count']} | "
                           f"Period: {stats['start_date']} to {stats['end_date']}")
                    logger.info(msg)
                else:
                    logger.info(f"[{i}/{total}] OK: {code} ({real_name}) | No gaps found.")
                
            except Exception as e:
                self.error_list.append((code, name, str(e)))
                logger.error(f"[{i}/{total}] FAILED: {code} ({name}) | Reason: {e}")
            
            self.processed_count += 1
            
            # クールダウン (実際にリクエストを行った場合のみカウント)
            if request_count > 0 and request_count % 10 == 0 and i < total:
                logger.info("Taking a deep breath (25s wait)...")
                time.sleep(25)
            elif i < total and not force_resync_code:
                time.sleep(1.5 + random.uniform(0, 1.0))
        
        # 最終サマリーレポート
        elapsed_time = time.time() - start_time
        elapsed_hours = int(elapsed_time // 3600)
        elapsed_minutes = int((elapsed_time % 3600) // 60)
        elapsed_seconds = int(elapsed_time % 60)
        
        if elapsed_hours > 0:
            time_str = f"{elapsed_hours}h {elapsed_minutes}m {elapsed_seconds}s"
        elif elapsed_minutes > 0:
            time_str = f"{elapsed_minutes}m {elapsed_seconds}s"
        else:
            time_str = f"{elapsed_time:.2f}s"

        logger.info("-" * 60)
        logger.info(f"Sync Process Completed at {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Total Time Elapsed   : {time_str}")
        logger.info(f"Total Portfolio Items: {total}")
        logger.info(f"Successfully Synced  : {self.success_count}")
        logger.info(f"Skipped (Up-to-date) : {skip_count}")
        logger.info(f"Failed/Errors        : {len(self.error_list)}")
        
        if self.error_list:
            logger.info("Detailed Error List:")
            for code, name, reason in self.error_list:
                logger.info(f"  - {code} ({name}): {reason}")
        logger.info("-" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Yahoo Finance JP Stock History Sync Tool')
    parser.add_argument('--force-resync', type=str, help='銘柄コードを指定して、DB内の履歴を削除し1年分を再同期する')
    args = parser.parse_args()

    tool = HistorySyncTool()
    tool.run(force_resync_code=args.force_resync)
