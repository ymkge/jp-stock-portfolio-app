"""
AI投資方針適合診断モーダルのドラッグ移動および現在株価表示の自動テスト (#374)

AGENTS.md 規約 0.2 に従い、本番DB (portfolio_history.db) への書き込みを行わず、
完全隔離状態でテストを実施。
"""

import os
import pytest


def test_html_llm_modal_draggable_and_price_header():
    """index.html にドラッグ用ヘッダーおよび現在株価バッジコンテナが存在すること (#374)"""
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "index.html")
    assert os.path.exists(html_path), "index.html が存在すること"

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. ドラッグ可能ヘッダークラスおよびドラッグインジケータ
    assert 'class="modal-header llm-draggable-header"' in html or 'llm-draggable-header' in html
    assert 'drag-handle-indicator' in html
    assert 'id="llm-modal-header"' in html

    # 2. 現在株価・前日比・配当利回りバッジ要素
    assert 'id="llm-modal-price-header"' in html
    assert 'id="llm-modal-current-price"' in html
    assert 'id="llm-modal-price-change"' in html
    assert 'id="llm-modal-dividend-yield"' in html


def test_css_llm_modal_draggable_and_price_styles():
    """style.css にドラッグ操作用CSSおよび株価バッジスタイルが定義されていること (#374)"""
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    assert os.path.exists(css_path), "style.css が存在すること"

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # 1. ドラッグ用カーソルとタッチアクション
    assert ".llm-draggable-header" in css
    assert "cursor: grab" in css
    assert "touch-action: none" in css

    # 2. ドラッグ中のカクつき防止 (transition: none)
    assert ".is-dragging" in css
    assert "transition: none !important" in css

    # 3. 株価バッジスタイル
    assert ".llm-price-header" in css
    assert ".llm-price-badge-item" in css
    assert ".llm-price-val" in css
    assert ".llm-change-val" in css
    assert ".llm-yield-val" in css

    # 4. ダークモードスタイル
    assert '[data-theme="dark"] .llm-price-header' in css


def test_js_llm_modal_drag_and_price_logic():
    """main.js に Pointer Events によるドラッグ制御、位置リセット、株価反映ロジックが存在すること (#374)"""
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "main.js")
    assert os.path.exists(js_path), "main.js が存在すること"

    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # 1. ドラッグ移動関数およびリセット関数
    assert "function initDraggableLlmModal()" in js
    assert "function resetLlmModalPosition()" in js
    assert "initDraggableLlmModal();" in js

    # 2. Pointer Events API の利用
    assert "pointerdown" in js
    assert "pointermove" in js
    assert "pointerup" in js
    assert "setPointerCapture" in js
    assert "releasePointerCapture" in js

    # 3. インタラクティブ要素除外ガード
    assert "e.target.closest('button, .modal-close" in js

    # 4. 画面外脱走防止バウンダリ制限
    assert "getBoundingClientRect" in js
    assert "window.innerWidth" in js
    assert "window.innerHeight" in js

    # 5. 現在株価・前日比・配当利回り反映処理
    assert "llmModalPriceHeader" in js
    assert "llmModalCurrentPrice" in js
    assert "llmModalPriceChange" in js
    assert "llmModalDividendYield" in js
    assert "price-up" in js
    assert "price-down" in js
