"""
AIおすすめ5選（絞り込み銘柄購入推奨Top5）モーダルのドラッグ移動および
各カード内現在株価バッジ描画の自動テスト (#376)

AGENTS.md 規約 0.2 に従い、本番DB (portfolio_history.db) への書き込みを行わず、
完全隔離状態でテストを実施。
"""

import os
import pytest


def test_html_filtered_rec_modal_draggable_header():
    """index.html におすすめ5選モーダルのドラッグ用ヘッダーおよびインジケータが存在すること (#376)"""
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")
    assert os.path.exists(html_path), "index.html が存在すること"

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. おすすめ5選モーダル内のドラッグ可能ヘッダー定義
    assert 'id="filtered-rec-modal-header"' in html
    assert 'draggable-header' in html
    assert 'drag-handle-indicator' in html


def test_css_filtered_rec_draggable_and_current_price_badge():
    """style.css にドラッグ操作共通スタイルおよび現在株価バッジスタイルが定義されていること (#376)"""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    assert os.path.exists(css_path), "style.css が存在すること"

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # 1. 共通ドラッグヘッダーおよびオーバーレイ透過度スタイル
    assert "#filtered-recommendation-modal.modal-overlay" in css
    assert ".modal-header.draggable-header" in css
    assert "cursor: grab" in css
    assert "touch-action: none" in css
    assert ".modal-content.is-dragging" in css

    # 2. おすすめ5選カード内 現在株価バッジスタイル
    assert ".rec-mini-badge.badge-current-price" in css
    assert '[data-theme="dark"] .rec-mini-badge.badge-current-price' in css


def test_js_filtered_rec_draggable_and_price_logic():
    """main.js に makeModalDraggable 共通化、おすすめ5選のドラッグ初期化、現在株価バッジ描画ロジックが存在すること (#376)"""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "main.js")
    assert os.path.exists(js_path), "main.js が存在すること"

    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # 1. 共通ドラッグ関数 makeModalDraggable
    assert "function makeModalDraggable(modalOverlay, headerSelector = '.modal-header')" in js
    assert "return { resetPosition };" in js

    # 2. おすすめ5選モーダルへのドラッグ適用
    assert "const filteredRecModalDraggable = makeModalDraggable(filteredRecModal, '#filtered-rec-modal-header');" in js
    assert "if (filteredRecModalDraggable) filteredRecModalDraggable.resetPosition();" in js

    # 3. 推奨銘柄カード内への現在株価バッジ描画ロジック
    assert "currentPriceBadge" in js
    assert "badge-current-price" in js
    assert "💹 現在値:" in js
