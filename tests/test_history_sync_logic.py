
import unittest
import sys
import os

# テスト対象となる判定ロジック（設計案を関数化したもの）
# 実際の実装時には scraper.py や sync_history.py に組み込まれます
def is_valid_price_row(vals, current_price, target_date, today_jst):
    """
    株価履歴の1行が妥当かどうかを判定する
    """
    # 1. 取得範囲の制限（前日まで）
    if target_date >= today_jst:
        return False, "Today's data skipped"

    # 2. 構造チェック（日本株の履歴行は通常7要素）
    # 始値, 高値, 安値, 終値, 出来高, 調整後終値, その他
    if len(vals) < 7:
        return False, f"Insufficient columns: {len(vals)}"

    try:
        # Index 3: 終値, Index 4: 出来高
        close_p_raw = vals[3].replace(',', '')
        volume_raw = vals[4].replace(',', '')
        
        close_p = float(close_p_raw)
        
        # 3. 出来高の整数性チェック（配当等は19.08のように小数になる）
        if '.' in volume_raw and not volume_raw.endswith('.0'):
            return False, f"Volume is not integer: {volume_raw}"
            
        # 4. 乖離率チェック（現在値がある場合）
        if current_price > 0:
            diff_ratio = abs(close_p - current_price) / current_price
            if diff_ratio > 0.5:
                return False, f"Price deviation too high: {close_p} (vs {current_price})"
                
        return True, "Valid"
    except (ValueError, IndexError) as e:
        return False, f"Parse error: {e}"

def calculate_stats(prices, dates):
    """
    統計情報を計算する
    """
    if not prices or not dates:
        return None
    
    return {
        'count': len(prices),
        'min_price': min(prices),
        'max_price': max(prices),
        'avg_price': sum(prices) / len(prices),
        'start_date': min(dates),
        'end_date': max(dates)
    }

class TestHistorySyncLogic(unittest.TestCase):
    def setUp(self):
        self.today = "2026-04-28"
        self.current_price = 4767.0 # 味の素(2802)の例

    def test_normal_row(self):
        # 正常な行（要素数7）
        vals = ["4,794", "4,813", "4,750", "4,767", "2,409,700", "4,767", "0"]
        is_valid, msg = is_valid_price_row(vals, self.current_price, "2026-04-25", self.today)
        self.assertTrue(is_valid, msg)

    def test_dividend_row(self):
        # 調査で見つかった配当行（要素数5、出来高が19.08）
        vals = ["132,100", "2,520,400", "-29,900", "15,300", "19.08"]
        is_valid, msg = is_valid_price_row(vals, self.current_price, "2025-12-19", self.today)
        self.assertFalse(is_valid)
        self.assertIn("Insufficient columns", msg)

    def test_today_data_exclusion(self):
        # 当日のデータは除外
        vals = ["4,794", "4,813", "4,750", "4,767", "2,409,700", "4,767", "0"]
        is_valid, msg = is_valid_price_row(vals, self.current_price, self.today, self.today)
        self.assertFalse(is_valid)
        self.assertEqual(msg, "Today's data skipped")

    def test_extreme_deviation(self):
        # 構造は正しくても価格が異常（出来高が価格位置に紛れ込んだ場合など）
        vals = ["4,794", "4,813", "4,750", "2409700", "100", "4,767", "0"]
        is_valid, msg = is_valid_price_row(vals, self.current_price, "2026-04-25", self.today)
        self.assertFalse(is_valid)
        self.assertIn("Price deviation too high", msg)

    def test_stats_calculation(self):
        # 統計計算の正確性
        prices = [100.0, 200.0, 300.0]
        dates = ["2026-04-01", "2026-04-02", "2026-04-03"]
        stats = calculate_stats(prices, dates)
        self.assertEqual(stats['count'], 3)
        self.assertEqual(stats['min_price'], 100.0)
        self.assertEqual(stats['max_price'], 300.0)
        self.assertEqual(stats['avg_price'], 200.0)
        self.assertEqual(stats['start_date'], "2026-04-01")
        self.assertEqual(stats['end_date'], "2026-04-03")

if __name__ == '__main__':
    unittest.main()
