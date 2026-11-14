"""
AIおすすめ5選（絞り込み銘柄購入推奨Top5）銘柄のメイン一覧テーブルフィルタ機能の自動テスト (#387)

AGENTS.md 規約 0.2 に従い、本番DB (portfolio_history.db) への書き込みを行わず、
完全隔離状態でテストを実施。
"""

import os
import pytest


def test_html_recommended_stocks_filter_buttons():
    """index.html におすすめ銘柄メイン一覧フィルタ用の各ボタン要素が存在すること (#387)"""
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")
    assert os.path.exists(html_path), "index.html が存在すること"

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. モーダルフッターの一括フィルタボタン
    assert 'id="btn-filter-recommended-stocks"' in html
    assert "メイン画面でこの5銘柄をフィルタ" in html

    # 2. メイン画面操作バーの直前おすすめ絞込ボタン
    assert 'id="btn-apply-last-recommendations"' in html
    assert "AIおすすめ銘柄で絞込" in html


def test_js_recommended_stocks_filter_logic():
    """main.js におすすめ銘柄によるメイン一覧絞り込みロジックおよびボタン連携が存在すること (#387)"""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "main.js")
    assert os.path.exists(js_path), "main.js が存在すること"

    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # 1. 絞り込み実行ヘルパー applyRecommendedStocksFilter
    assert "function applyRecommendedStocksFilter(codes, targetAssetType)" in js
    assert "window.applyRecommendedStocksFilter = applyRecommendedStocksFilter;" in js

    # 2. 競合フィルタの安全な解除シーケンス
    assert "if (industryFilter) industryFilter.value = '';" in js
    assert "if (signalFilter) signalFilter.value = '';" in js
    assert "if (payoutRatioFilter) payoutRatioFilter.value = '';" in js
    assert "if (showOnlyManagedAssetsCheckbox) showOnlyManagedAssetsCheckbox.checked = false;" in js
    assert "filterInput.value = codes.join(' ');" in js
    assert "updatePresetActiveStates(null);" in js

    # 3. アセット種別タブの自動同期
    assert 'document.querySelector(`.tab-link[data-tab="${desiredTab}"]`)' in js

    # 4. 各カード内個別フィルタボタン
    assert "btn-filter-single-rec" in js
    assert "🔍 一覧で確認" in js

    # 5. イベントリスナー登録
    assert "filteredRecFilterBtn.addEventListener('click'" in js
    assert "applyLastRecBtn.addEventListener('click'" in js
    assert "closest('.btn-filter-single-rec')" in js


def test_css_filter_buttons_styles():
    """style.css に個別銘柄フィルタボタンおよびレスポンシブスタイルが定義されていること (#387)"""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    assert os.path.exists(css_path), "style.css が存在すること"

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # 1. アクションボタンのレスポンシブ折返し
    assert ".action-buttons" in css
    assert "flex-wrap: wrap;" in css

    # 2. 個別銘柄フィルタボタンスタイル
    assert ".btn-filter-single-rec" in css
    assert ".btn-filter-single-rec:hover" in css
    assert '[data-theme="dark"] .btn-filter-single-rec' in css
