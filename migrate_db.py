
import sqlite3
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DB_FILE = "portfolio_history.db"

def migrate():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # 1. カラムの追加 (存在しない場合のみ)
        # SQLite 3.32.0未満では1回のALTERで1カラムなので個別に実行
        try:
            cursor.execute("ALTER TABLE daily_stock_history ADD COLUMN close_price REAL")
            logger.info("Added column 'close_price'")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                logger.info("Column 'close_price' already exists")
            else:
                raise

        try:
            cursor.execute("ALTER TABLE daily_stock_history ADD COLUMN volume INTEGER")
            logger.info("Added column 'volume'")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                logger.info("Column 'volume' already exists")
            else:
                raise

        # 2. データのバックフィル (更新が必要な行のみ)
        cursor.execute("SELECT date, code, data_json FROM daily_stock_history WHERE close_price IS NULL")
        rows = cursor.fetchall()
        
        if not rows:
            logger.info("No rows need backfilling.")
            return

        logger.info(f"Starting backfill for {len(rows)} rows...")
        
        update_data = []
        for date, code, data_json_str in rows:
            try:
                data = json.loads(data_json_str)
                # price, close_price のいずれかから取得
                price = data.get('price') or data.get('close_price')
                # 文字列の場合は数値に変換
                if isinstance(price, str):
                    price = price.replace(',', '').replace('N/A', '')
                    price = float(price) if price else None
                
                volume = data.get('volume')
                if isinstance(volume, str):
                    volume = volume.replace(',', '').replace('N/A', '')
                    volume = int(float(volume)) if volume else None
                
                update_data.append((price, volume, date, code))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse data for {code} on {date}: {e}")
                continue

        # 一括更新
        cursor.executemany(
            "UPDATE daily_stock_history SET close_price = ?, volume = ? WHERE date = ? AND code = ?",
            update_data
        )
        
        conn.commit()
        logger.info(f"Migration completed. {len(update_data)} rows updated.")

    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        logger.error(f"Migration failed: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    migrate()
