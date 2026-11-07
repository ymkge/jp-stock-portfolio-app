import os
import pytest

def test_sector_summary_factors_and_confidence_ui():
    """案件 #380: セクター動向短評の下落・上昇要因および確信度バッジのJS/CSS整合性テスト"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js_path = os.path.join(base_dir, "static", "js", "analysis.js")
    css_path = os.path.join(base_dir, "static", "css", "style.css")

    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # JSレンダリングロジックの検証
    assert "data.downside_factors" in js
    assert "data.upside_factors" in js
    assert "renderFactorConfidenceBadge" in js
    assert "ind-factor-confidence-badge" in js
    assert "industry-ai-downside-box" in js
    assert "industry-ai-upside-box" in js
    assert "📉 主な下落・軟調要因" in js
    assert "📈 主な上昇・牽引要因" in js
    assert "🎯 確信度:" in js

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # CSSスタイルの検証
    assert ".industry-ai-downside-box" in css
    assert ".industry-ai-upside-box" in css
    assert ".ind-factor-confidence-badge" in css
    assert ".ind-factor-confidence-badge.is-high" in css
    assert ".ind-factor-confidence-badge.is-mid" in css
    assert ".ind-factor-confidence-badge.is-caution" in css

    # ダークモードの検証
    assert '[data-theme="dark"] .industry-ai-downside-box' in css
    assert '[data-theme="dark"] .industry-ai-upside-box' in css
    assert '[data-theme="dark"] .ind-factor-confidence-badge.is-high' in css
    assert '[data-theme="dark"] .ind-factor-confidence-badge.is-mid' in css
    assert '[data-theme="dark"] .ind-factor-confidence-badge.is-caution' in css
