"""tests/test_monthly_dividend_filter.py
月別配当分布 (予測) クリックによる銘柄一覧フィルタ連動機能 (#333) の単体テスト・静的検証
"""

import os
import re
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_dividend_month_calculation_logic():
    """配当月算出ロジック（getDividendMonthsForItemと同等仕様）の計算検証"""
    def calc_dividend_months(asset_type, settlement_month_str, annual_div):
        if not annual_div or annual_div <= 0:
            return []
        if not settlement_month_str or not isinstance(settlement_month_str, str):
            return []
        m = re.search(r"(\d+)", settlement_month_str)
        if not m:
            return []
        base = int(m.group(1))
        if base < 1 or base > 12:
            return []

        get_month = lambda b, offset: ((b + offset - 1) % 12) + 1

        if asset_type == "jp_stock":
            return [get_month(base, 3), get_month(base, 9)]
        elif asset_type == "us_stock":
            return [get_month(base, 3), get_month(base, 6), get_month(base, 9), get_month(base, 12)]
        else:
            return [get_month(base, 3)]

    # 1. 日本株 3月決算 -> 6月と12月
    assert calc_dividend_months("jp_stock", "3月", 5000) == [6, 12]
    assert calc_dividend_months("jp_stock", "03", 5000) == [6, 12]

    # 2. 日本株 12月決算 -> 3月と9月
    assert calc_dividend_months("jp_stock", "12月", 3000) == [3, 9]

    # 3. 日本株 9月決算 -> 12月と6月
    assert calc_dividend_months("jp_stock", "9月", 2000) == [12, 6]

    # 4. 米国株 12月決算 -> 3月, 6月, 9月, 12月
    assert calc_dividend_months("us_stock", "12月", 1000) == [3, 6, 9, 12]

    # 5. 投信 3月決算 -> 6月
    assert calc_dividend_months("investment_trust", "3月", 500) == [6]

    # 6. 無配銘柄（配当0円） -> 空リスト
    assert calc_dividend_months("jp_stock", "3月", 0) == []
    assert calc_dividend_months("jp_stock", "3月", -100) == []

    # 7. 決算月なし / 不正値 -> 空リスト
    assert calc_dividend_months("jp_stock", "N/A", 5000) == []
    assert calc_dividend_months("jp_stock", "--", 5000) == []
    assert calc_dividend_months("jp_stock", None, 5000) == []


def test_analysis_html_elements_and_cachebusters():
    """templates/analysis.html に新設された要素とキャッシュバスターの存在確認"""
    html_path = os.path.join(BASE_DIR, "templates", "analysis.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # ガイドテキストの存在
    assert 'class="chart-click-hint"' in html
    assert "バーをクリックで銘柄を絞り込み" in html

    # バッジコンテナおよび内部要素の存在
    assert 'id="active-dividend-month-badge-container"' in html
    assert 'id="active-dividend-month-text"' in html
    assert 'id="btn-clear-dividend-month"' in html

    # キャッシュバスターの確認 (style.css?v=4.6, analysis.js?v=3.7)
    assert 'style.css?v=4.6' in html
    assert 'analysis.js?v=3.7' in html


def test_style_css_monthly_dividend_classes():
    """static/css/style.css に必要なクラスとダークモード定義が存在することを確認"""
    css_path = os.path.join(BASE_DIR, "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".chart-click-hint" in css
    assert ".active-filter-badge-container" in css
    assert ".active-filter-pill" in css
    assert ".btn-clear-filter" in css

    # ダークモード定義の確認
    assert '[data-theme="dark"] .active-filter-pill' in css
    assert 'body.dark-mode .active-filter-pill' in css


def test_analysis_js_monthly_dividend_logic():
    """static/js/analysis.js に配当月フィルタ関連の関数と母集団分離が実装されていることを確認"""
    js_path = os.path.join(BASE_DIR, "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # ステートとヘルパー関数の存在
    assert "let selectedDividendMonth = null;" in js
    assert "let baseFilteredHoldingsData = [];" in js
    assert "function getDividendMonthsForItem(" in js
    assert "function hasDividendInMonth(" in js
    assert "function toggleDividendMonthFilter(" in js

    # Chart.js onClick / onHover ハンドラの存在
    assert "onClick: (event, elements) =>" in js
    assert "toggleDividendMonthFilter(clickedMonth)" in js
    assert "onHover: (event, elements) =>" in js
    assert "target.style.cursor = elements && elements.length > 0 ? 'pointer' : 'default';" in js

    # 母集団分離（縮退防止）
    assert "baseFilteredHoldingsData = allHoldingsData.filter(" in js
    assert "filteredHoldingsData = baseFilteredHoldingsData.filter(" in js
    assert "renderCharts(filteredHoldingsData, baseFilteredHoldingsData);" in js

    # バッジ「✕」クリアボタンのイベント登録
    assert "document.getElementById('btn-clear-dividend-month')" in js
    assert "selectedDividendMonth = null;" in js

    # 既存のツールチップ要件 (label の存在 & afterLabel の非存在) の確認
    monthly_chart_section = js.split("getElementById('monthly-dividend-chart')")[1].split("updateChart")[0]
    assert "label: (c) => `${c.dataset.label}:" in monthly_chart_section
    assert "afterLabel" not in monthly_chart_section
