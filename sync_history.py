
import time
import random
import logging
import shutil
import os
import sys
from datetime import datetime
import sqlite3
import json

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

    def get_latest_date_in_db(self, code):
        """指定銘柄のDB内最新日付を取得する"""
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT MAX(date) FROM daily_stock_history WHERE code = ?", 
                    (code,)
                )
                res = cursor.fetchone()
                return res[0] if res and res[0] else "1970-01-01"
        except Exception as e:
            logger.error(f"Error checking DB for {code}: {e}")
            return "1970-01-01"

    def save_histories(self, histories):
        """取得した時系列データをDBに保存する"""
        if not histories:
            return
        
        try:
            with sqlite3.connect(DB_FILE) as conn:
                cursor = conn.cursor()
                for h in histories:
                    # DB用の生データを準備
                    data_json = json.dumps(h)
                    cursor.execute("""
                        INSERT INTO daily_stock_history (date, code, asset_type, close_price, volume, data_json, updated_at_jst)
                        VALUES (?, ?, 'jp_stock', ?, ?, ?, ?)
                        ON CONFLICT(date, code) DO UPDATE SET
                            close_price = COALESCE(excluded.close_price, close_price),
                            volume = COALESCE(excluded.volume, volume),
                            updated_at_jst = excluded.updated_at_jst
                    """, (
                        h['date'], h['code'], h.get('closePrice'), h.get('volume'),
                        data_json, datetime.now(JST).isoformat()
                    ))
                conn.commit()
                logger.info(f"Saved {len(histories)} records for {histories[0]['code']}")
        except Exception as e:
            logger.error(f"Failed to save to DB: {e}")

    def sync_stock(self, code):
        """1銘柄の履歴を同期する"""
        latest_date = self.get_latest_date_in_db(code)
        logger.info(f"Syncing {code}: DB latest date is {latest_date}")
        
        all_histories_to_save = []
        base_url = f"https://finance.yahoo.co.jp/quote/{code}.T/history"
        
        # まず現在値を把握 (動的フィルタ用)
        current_price = 0.0
        try:
            main_url = f"https://finance.yahoo.co.jp/quote/{code}.T"
            res_m = self.scraper._make_request(main_url)
            if res_m:
                json_m = self.scraper._extract_next_data(res_m.text)
                m_data = self.scraper._scavenge_common_data(res_m.text, json_m)
                p_val = m_data.get('price')
                if isinstance(p_val, str): p_val = p_val.replace(',', '')
                current_price = float(p_val) if p_val not in [None, "N/A", "--", "---", ""] else 0.0
        except: pass

        for page in range(1, self.max_pages + 1):
            logger.info(f"  Fetching page {page} for {code}...")
            
            # Next.js のデータエンドポイント用パラメータを付与 (2ページ目以降で必須)
            if page == 1:
                url = base_url
            else:
                params = f"page={page}&_data=app%2Fpc%2F%5Btype%5D%2Fquote%2F%5Bcode%5D%2Fhistory%2Fpage"
                url = f"{base_url}?{params}"
            
            res = self.scraper._make_request(url)
            if not res:
                logger.error(f"  Failed to fetch page {page}")
                break
                
            if res.status_code == 403:
                logger.critical("!!! 403 Forbidden detected. Circuit breaker activated !!!")
                sys.exit(1)
            # JSONデータの抽出
            json_data = self.scraper._extract_next_data(res.text)
            # scraper._parse_histories は 現在値を基準にフィルタリングを行う
            raw_histories = self.scraper._parse_histories(json_data if json_data else res.text, current_price=current_price)

            
            if not raw_histories:
                logger.info("  No more history data found.")
                break
            
            new_data_found = False
            page_data_to_add = []
            for h in raw_histories:
                # 日付の正規化 (YYYY/M/D -> YYYY-MM-DD)
                raw_dt = h.get('baseDatetime')
                if not raw_dt: continue
                
                try:
                    dt_obj = datetime.strptime(raw_dt.replace('-', '/'), '%Y/%m/%d')
                    iso_date = dt_obj.strftime('%Y-%m-%d')
                except ValueError:
                    logger.warning(f"  Invalid date format: {raw_dt}")
                    continue
                
                h['date'] = iso_date
                h['code'] = code
                
                if h['date'] <= latest_date:
                    continue
                
                page_data_to_add.append(h)
                new_data_found = True
            
            all_histories_to_save.extend(page_data_to_add)
            
            if not new_data_found and page > 1:
                logger.info(f"  Reached already synced data for {code}. Stopping.")
                break
                
            # ページ間待機
            time.sleep(2.0 + random.uniform(0, 1.5))
            
        self.save_histories(all_histories_to_save)

    def run(self):
        """メイン実行ループ"""
        self.backup_db()
        
        portfolio = load_portfolio()
        # テスト用に1銘柄のみ
        jp_stocks = [s for s in portfolio if s.get('asset_type') == 'jp_stock']
        
        total = len(jp_stocks)
        logger.info(f"Starting sync for {total} JP stocks.")
        
        for i, stock in enumerate(jp_stocks, 1):
            code = stock['code']
            logger.info(f"[{i}/{total}] Processing {code} ({stock.get('name', 'Unknown')})")
            
            try:
                self.sync_stock(code)
                self.processed_count += 1
            except Exception as e:
                logger.error(f"Unexpected error syncing {code}: {e}", exc_info=True)
            
            if i % 10 == 0 and i < total:
                logger.info("Taking a deep breath (60s wait)...")
                time.sleep(60)
            elif i < total:
                time.sleep(5.0 + random.uniform(0, 3.0))
        
        logger.info(f"Sync completed. Processed {self.processed_count} stocks.")

if __name__ == "__main__":
    tool = HistorySyncTool()
    tool.run()
