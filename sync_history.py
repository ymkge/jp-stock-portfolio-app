
import time
import random
import logging
import shutil
import os
import sys
from datetime import datetime
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
        
        try:
            # 価格の統計計算
            prices = [float(h['closePrice']) for h in histories if h.get('closePrice') and h.get('closePrice') != "N/A"]
            stats = {
                'count': len(histories),
                'start_date': min(h['date'] for h in histories),
                'end_date': max(h['date'] for h in histories),
                'min_price': min(prices) if prices else 0,
                'max_price': max(prices) if prices else 0,
                'avg_price': sum(prices) / len(prices) if prices else 0
            }

            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                for h in histories:
                    # 数値へのキャストを確実に実行
                    try:
                        c_p = float(h.get('closePrice')) if h.get('closePrice') else None
                        v_ol = int(float(h.get('volume'))) if h.get('volume') else None
                    except (ValueError, TypeError):
                        c_p = None
                        v_ol = None

                    # 純粋な株価履歴テーブルにのみ保存
                    cursor.execute("""
                        INSERT INTO stock_price_history (date, code, close_price, volume, updated_at_jst)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(date, code) DO UPDATE SET
                            close_price = COALESCE(excluded.close_price, close_price),
                            volume = COALESCE(excluded.volume, volume),
                            updated_at_jst = excluded.updated_at_jst
                    """, (
                        h['date'], h['code'], c_p, v_ol,
                        datetime.now(JST).isoformat()
                    ))
                conn.commit()
            return stats
        except Exception as e:
            logger.error(f"Failed to save to DB: {e}")
            raise e

    def sync_stock(self, code, name="Unknown"):
        """1銘柄の履歴を同期する"""
        existing_dates = self.get_existing_dates(code)
        # JSTでの今日の日付を取得 (当日分は除外するため)
        today_jst = datetime.now(JST).strftime("%Y-%m-%d")
        
        all_histories_to_save = []
        # URL正規化: すでに .T や .O があればそのまま、なければ .T を付与
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
            # 分割チェックを正確に行うため、current_priceによる厳格バリデーションは無効化して取得
            raw_histories = self.scraper._parse_histories(json_data if json_data else res.text, current_price=None)
            
            logger.info(f"Page {page}: Found {len(raw_histories) if raw_histories else 0} raw records.")

            if not raw_histories:
                logger.debug(f"No histories found on page {page} for {code}")
                break

            # ページ1において株式分割の検知と補正を行う
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
                        # 15%以上の乖離があれば分割・併合とみなす
                        if abs(median_ratio - 1.0) > 0.15:
                            logger.warning(f"!!! SPLIT DETECTED for {code} !!! Estimated Ratio: {median_ratio:.4f}")
                            self.apply_split_adjustment(code, median_ratio)
                            split_adjusted = True
                            # 補正後は、Page 1の全データを最新調整後データとして上書きするため既存チェックを無視させる
            
            new_data_found_on_page = False
            page_data_to_add = []
            for h in raw_histories:
                raw_dt = h.get('baseDatetime')
                if not raw_dt: continue
                
                try:
                    dt_obj = datetime.strptime(raw_dt.replace('-', '/'), '%Y/%m/%d')
                    iso_date = dt_obj.strftime('%Y-%m-%d')
                except ValueError:
                    continue
                
                h['date'] = iso_date
                h['code'] = code
                
                # 1. 範囲制限: 当日以降のデータは除外（前日まで）
                if h['date'] >= today_jst:
                    continue
                
                # 2. 既存データとの重複チェック (分割検知時は常に上書き)
                if not split_adjusted and h['date'] in existing_dates:
                    continue
                
                page_data_to_add.append(h)
                new_data_found_on_page = True
            
            logger.info(f"Page {page}: {len(page_data_to_add)} records are new.")
            all_histories_to_save.extend(page_data_to_add)
            
            # 最適化（早期終了判定）: 
            # 1. 株式分割が発生した場合：Page 1を保存して即時終了
            if split_adjusted:
                logger.info(f"Splits adjusted and Page 1 records prepared. Stopping early for {code}.")
                break

            # 2. 通常時：このページで新しいデータがなく、かつDBに十分な件数（250件=約1年分）があれば終了
            if not new_data_found_on_page and len(existing_dates) >= 250:
                logger.info(f"No new data on page {page} and DB has sufficient records ({len(existing_dates)}). Stopping early.")
                break
                
            # ページ間待機 (Yahoo負荷軽減)
            time.sleep(1.5 + random.uniform(0, 1.0))
            
        stats = self.save_histories(all_histories_to_save)
        return stats, stock_name

    def run(self, force_resync_code=None):
        """メイン実行ループ"""
        self.backup_db()
        self.cleanup_invalid_data("2026-04-27") # 4/27の不正データを掃除
        
        portfolio = load_portfolio()
        jp_stocks = [s for s in portfolio if s.get('asset_type') == 'jp_stock']
        
        # 市場指標のロードと追加
        try:
            with open("highlight_rules.json", "r", encoding="utf-8") as f:
                rules = json.load(f)
                market_indices = rules.get("market_indices", [])
                for idx in market_indices:
                    # 重複を避ける（ポートフォリオに指標コードを直接入れている場合を考慮）
                    if not any(s['code'] == idx['code'] for s in jp_stocks):
                        jp_stocks.append({
                            'code': idx['code'], 
                            'name': idx['name'],
                            'asset_type': 'market_index'
                        })
                logger.info(f"Loaded {len(market_indices)} market indices for sync.")
        except Exception as e:
            logger.error(f"Failed to load market indices from rules: {e}")

        # force_resyncが指定されている場合は、その銘柄のみを対象にする
        if force_resync_code:
            target_stocks = [s for s in jp_stocks if s['code'] == force_resync_code]
            if not target_stocks:
                # ポートフォリオにない場合も直接指定可能にする
                target_stocks = [{'code': force_resync_code, 'name': 'Target Stock'}]
            
            logger.info(f"FORCE RESYNC mode for {force_resync_code}")
            self.delete_stock_history(force_resync_code)
            jp_stocks = target_stocks

        total = len(jp_stocks)
        logger.info(f"Starting sync for {total} JP stocks.")
        
        for i, stock in enumerate(jp_stocks, 1):
            code = stock['code']
            name = stock.get('name', 'Unknown')
            
            try:
                stats, real_name = self.sync_stock(code, name)
                if stats:
                    self.success_count += 1
                    msg = (f"[{i}/{total}] SUCCESS: {code} ({real_name}) | "
                           f"New Records: {stats['count']} | "
                           f"Period: {stats['start_date']} to {stats['end_date']} | "
                           f"Price: Min={stats['min_price']:.1f}, Max={stats['max_price']:.1f}, Avg={stats['avg_price']:.1f}")
                    logger.info(msg)
                else:
                    logger.info(f"[{i}/{total}] SKIP: {code} ({real_name}) | No new records to sync.")
                
            except Exception as e:
                self.error_list.append((code, name, str(e)))
                logger.error(f"[{i}/{total}] FAILED: {code} ({name}) | Reason: {e}")
            
            self.processed_count += 1
            
            # クールダウン (10銘柄ごとに深呼吸、それ以外も一定間隔)
            if i % 10 == 0 and i < total:
                logger.info("Taking a deep breath (25s wait to avoid 403)...")
                time.sleep(25)
            elif i < total and not force_resync_code:
                time.sleep(2.0 + random.uniform(0, 1.5))
        
        # 最終サマリーレポート
        logger.info("-" * 60)
        logger.info(f"Sync Process Completed at {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"Total Portfolio Stocks: {total}")
        logger.info(f"Successfully Synced : {self.success_count}")
        logger.info(f"Failed/Errors       : {len(self.error_list)}")
        
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
