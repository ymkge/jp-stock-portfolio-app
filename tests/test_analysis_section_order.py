"""tests/test_analysis_section_order.py
analyticsページ（ポートフォリオ分析画面）の左カラムにおける各セクションの表示順序検証テスト (#353)
"""

import os
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_analysis_page_section_order():
    """templates/analysis.html の左カラム各セクションおよび見出しがユーザー指定の順序通りに並んでいることを検証 (#353)"""
    html_path = os.path.join(BASE_DIR, "templates", "analysis.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert '<div class="analysis-left-column">' in html
    assert '<div class="analysis-right-column">' in html

    left_col = html.split('<div class="analysis-left-column">')[1].split('<div class="analysis-right-column">')[0]

    # 1. セクションクラスの順序検証
    expected_section_classes = [
        "portfolio-summary",
        "portfolio-history",
        "portfolio-chart",
        "portfolio-personality",
        "portfolio-radar",
        "portfolio-dna",
        "concentration-risk",
    ]
    section_indices = [left_col.index(cls) for cls in expected_section_classes]
    assert section_indices == sorted(section_indices), (
        f"セクションクラスの出現順序が指定と異なります: {expected_section_classes}"
    )

    # 2. 見出し (h3) の順序検証（ユーザー指定順）
    expected_headings = [
        "サマリー",
        "資産推移",
        "配当推移 (履歴)",
        "月別配当分布 (予測)",
        "ポートフォリオ構成",
        "国内株式ポートフォリオ性格診断",
        "国内株式ポートフォリオ特性 (Radar Chart)",
        "国内株式ポートフォリオ体質 (DNA)",
        "分散度・リスク分析",
    ]
    heading_indices = [left_col.index(h) for h in expected_headings]
    assert heading_indices == sorted(heading_indices), (
        f"見出しの出現順序が指定と異なります: {expected_headings}"
    )


def test_portfolio_history_css_margin_uniformity():
    """static/css/style.css において .portfolio-history の不要な margin-top: 1rem が除去され、カード間余白が均一化されていることを検証 (#353)"""
    css_path = os.path.join(BASE_DIR, "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    assert ".portfolio-history {\n    margin-top: 1rem;\n}" not in css
