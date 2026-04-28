
import sys
from sync_history import HistorySyncTool
from portfolio_manager import load_portfolio

def run_test_sync():
    tool = HistorySyncTool()
    # テスト用に2銘柄程度に絞る
    portfolio = load_portfolio()
    jp_stocks = [s for s in portfolio if s.get('asset_type') == 'jp_stock']
    
    if not jp_stocks:
        print("No JP stocks found in portfolio.")
        return

    test_stocks = jp_stocks[:2]
    print(f"Starting test sync for: {[s['code'] for s in test_stocks]}")
    
    # テスト用に run() の中身を模倣
    tool.backup_db()
    tool.cleanup_invalid_data("2026-04-27")
    
    total = len(test_stocks)
    for i, stock in enumerate(test_stocks, 1):
        code = stock['code']
        name = stock.get('name', 'Unknown')
        try:
            stats = tool.sync_stock(code)
            if stats:
                print(f"SUCCESS: {code} | Count: {stats['count']} | {stats['start_date']} to {stats['end_date']}")
            else:
                print(f"SKIP: {code} | No new records.")
        except Exception as e:
            print(f"FAILED: {code} | {e}")

if __name__ == "__main__":
    run_test_sync()
