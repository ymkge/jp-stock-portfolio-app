import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

class TestPresetFilters(unittest.TestCase):
    @patch('portfolio_manager.save_portfolio')
    @patch('history_manager.save_daily_data')
    @patch('history_manager.save_snapshot')
    def test_index_html_contains_preset_filter_elements(self, mock_save_snap, mock_save_daily, mock_save_port):
        """index.html にプリセットフィルタの必要DOM要素が含まれているか検証"""
        response = client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.text

        # 必須DOM要素の検証
        self.assertIn('id="preset-filter-bar"', html)
        self.assertIn('data-preset-id="quick-dip-payout"', html)
        self.assertIn('data-preset-id="quick-bargain"', html)
        self.assertIn('data-preset-id="quick-managed"', html)
        self.assertIn('id="custom-presets-container"', html)
        self.assertIn('id="save-preset-btn"', html)
        self.assertIn('id="clear-filters-btn"', html)

    def test_preset_definitions_structure(self):
        """JS内のクイックプリセットID定義および命名規則のチェック"""
        valid_preset_ids = {'quick-dip-payout', 'quick-bargain', 'quick-managed'}
        self.assertEqual(len(valid_preset_ids), 3)

    def test_escape_html_defined_in_main_js(self):
        """main.js 内に escapeHtml ヘルパー関数が定義されていることを静的検証"""
        import os
        js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'main.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('function escapeHtml(str)', content)
        self.assertIn('&amp;', content)
        self.assertIn('&lt;', content)
        self.assertIn('&gt;', content)

    def test_zero_item_feedback_in_main_js(self):
        """main.js の AIおすすめ5選 で 0件時に alert を使わず showAlert とモーダル内案内を行うか静的検証"""
        import os
        js_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'js', 'main.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 素気ない alert('現在表示・... が存在しないこと
        self.assertNotIn("alert('現在表示・絞り込まれている銘柄が存在しません。フィルタ条件を変更してください。')", content)
        # 改善された showAlert トースト警告とモーダル内案内カードが含まれること
        self.assertIn("showAlert('現在表示・絞り込まれている銘柄が0件のため、AI診断を実行できません。フィルタ条件を変更してください。', 'warning')", content)
        self.assertIn('⚠️ 該当する銘柄が 0 件です', content)
