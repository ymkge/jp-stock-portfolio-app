import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app import app, policy_manager_instance, llm_service_instance

client = TestClient(app)

def test_api_get_investment_policy(tmp_path):
    response = client.get("/api/investment-policy")
    assert response.status_code == 200
    data = response.json()
    assert "api_key_masked" in data
    assert "has_api_key" in data
    assert "selected_model" in data
    assert "policy_prompt" in data

def test_api_save_and_reset_investment_policy():
    # 1. 設定保存
    save_payload = {
        "api_key": "test_api_key_12345678",
        "selected_model": "gemini-flash-lite-latest",
        "policy_prompt": "結合テスト用方針",
        "reset": False
    }
    response = client.post("/api/investment-policy", json=save_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["has_api_key"] is True
    assert data["selected_model"] == "gemini-flash-lite-latest"
    assert data["policy_prompt"] == "結合テスト用方針"

    # 2. リセット
    reset_payload = {"reset": True}
    response = client.post("/api/investment-policy", json=reset_payload)
    assert response.status_code == 200
    data_reset = response.json()
    assert "インカムゲイン特化型" in data_reset["policy_prompt"]

@patch("app.fetch_asset_data_smart_cached")
@patch.object(llm_service_instance, "diagnose_stock")
def test_api_llm_diagnose_success(mock_diagnose, mock_fetch):
    mock_fetch.return_value = (
        {
            "code": "7164",
            "name": "全国保証",
            "price": "4500",
            "currency": "JPY",
            "asset_type": "jp_stock"
        },
        True
    )
    mock_diagnose.return_value = {
        "error": False,
        "fit_level": "fit",
        "confidence_score": 90,
        "decision_label": "【強い買い（コア）】",
        "estimated_yield": "約4.4%",
        "recommended_shares": "約3株〜4株",
        "shield_and_valuation": "良好",
        "business_10y_eval": "安定",
        "tactical_advice": "買い推奨",
        "summary": "優秀な銘柄です。"
    }

    payload = {
        "code": "7164",
        "asset_type": "jp_stock",
        "force": True
    }
    response = client.post("/api/llm/diagnose", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["fit_level"] == "fit"
    assert data["decision_label"] == "【強い買い（コア）】"
    mock_diagnose.assert_called_once()
    assert mock_diagnose.call_args.kwargs.get("force") is True

@patch("app.fetch_asset_data_smart_cached")
def test_api_llm_diagnose_asset_not_found(mock_fetch):
    mock_fetch.return_value = (None, False)

    payload = {
        "code": "0000",
        "asset_type": "jp_stock"
    }
    response = client.post("/api/llm/diagnose", json=payload)
    assert response.status_code == 400
    assert "銘柄コード 0000 のデータが取得できませんでした。" in response.json()["detail"]


def test_monthly_dividend_chart_tooltip_rollback():
    """monthly-dividend-chart のツールチップから afterLabel (前月比表示) が削除され、予想受取額のみが表示されることを検証"""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # monthly-dividend-chart の定義部分を抽出
    monthly_chart_section = content.split("getElementById('monthly-dividend-chart')")[1].split("updateChart")[0]
    
    # label の存在確認と afterLabel の非存在確認
    assert "label: (c) => `${c.dataset.label}:" in monthly_chart_section
    assert "afterLabel" not in monthly_chart_section


def test_dividend_history_chart_tooltip_retention():
    """dividend-history-chart のツールチップに afterLabel (前月比表示) が引き続き維持されていることを検証"""
    import os
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # dividend-history-chart の定義部分を抽出
    history_chart_section = content.split("getElementById('dividend-history-chart')")[1].split("processAnalysisData")[0]
    
    # label および afterLabel (前月比) の維持確認
    assert "label: (c) =>" in history_chart_section
    assert "afterLabel: (c) =>" in history_chart_section
    assert "前月比:" in history_chart_section


def test_disclaimer_banner_and_footer_in_html():
    """トップ画面 (/) および分析画面 (/analysis) に免責事項バナー・フッター・法的4要素が常時表示され、閉じるボタンが不在であることを検証"""
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "top-disclaimer-banner" in res_index.text
    assert "免責事項:" in res_index.text
    assert "一切の責任を負いません" in res_index.text
    assert "app-disclaimer-footer" in res_index.text
    # 法的4要素の検証
    assert "投資助言等の否定" in res_index.text
    assert "データの無保証" in res_index.text
    assert "AI診断結果の性質" in res_index.text
    assert "完全免責" in res_index.text
    # 閉じるボタン・再表示ボタン・非表示化スクリプトの不在検証 (常時表示仕様 #288)
    assert "btn-close-disclaimer" not in res_index.text
    assert "btn-restore-disclaimer" not in res_index.text
    assert "disclaimer_banner_closed" not in res_index.text
    assert "llm-disclaimer-note" in res_index.text

    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    assert "top-disclaimer-banner" in res_analysis.text
    assert "app-disclaimer-footer" in res_analysis.text
    assert "投資助言等の否定" in res_analysis.text
    assert "データの無保証" in res_analysis.text
    assert "AI診断結果の性質" in res_analysis.text
    assert "btn-close-disclaimer" not in res_analysis.text
    assert "btn-restore-disclaimer" not in res_analysis.text
    assert "disclaimer_banner_closed" not in res_analysis.text
    assert "完全免責" in res_analysis.text


def test_llm_modal_first_view_and_responsive_css():
    """案件 #248: AI診断モーダルのファーストVIEW完全収容、内部スクロール、グリッドレイアウト、ダークモードCSSの検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. モーダル高さ制限と内部スクロール検証
    assert "#llm-diagnosis-modal .modal-content" in css_content
    assert ".modal-content" in css_content
    assert ".modal-body" in css_content
    assert "max-height: calc(100vh - 40px);" in css_content
    assert "overflow-y: auto;" in css_content

    # 2. レスポンシブ2列レイアウトとコンパクトブロック検証
    assert ".llm-grid-container" in css_content
    assert "grid-template-columns: 1fr 1fr;" in css_content
    assert "@media (max-width: 768px)" in css_content
    assert "grid-template-columns: 1fr;" in css_content
    assert ".llm-section-block" in css_content

    # 3. ダークモード配色設計検証
    assert "body.dark-mode .llm-section-block" in css_content

    # 4. 強調スタイルの検証 (#249)
    assert ".llm-section-block.theme-highlight-summary" in css_content
    assert ".llm-section-block.theme-highlight-action" in css_content
    assert "body.dark-mode .llm-section-block.theme-highlight-summary" in css_content
    assert "body.dark-mode .llm-section-block.theme-highlight-action" in css_content

    # 5. 一元化された共通モーダル構造（.modal-body）が定義されているか検証 (#301)
    assert ".modal-body {" in css_content

    # JS/HTML構造検証
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "main.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "llm-grid-container" in js_content
    assert "llm-column" in js_content
    assert "llm-section-block" in js_content
    assert "theme-highlight-summary" in js_content
    assert "theme-highlight-action" in js_content
    assert "llm-section-title" in js_content
    assert "llm-text-content" in js_content


def test_llm_modal_dark_mode_visibility_issue249():
    """案件 #249: AI診断モーダル強調カードおよび標準カードのダークモード文字視認性・セレクタ網羅性の詳細検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. セレクタ網羅検証 ([data-theme="dark"], body.dark-mode, .dark-mode)
    assert '[data-theme="dark"] .llm-section-block.theme-highlight-summary' in css_content
    assert 'body.dark-mode .llm-section-block.theme-highlight-summary' in css_content
    assert '.dark-mode .llm-section-block.theme-highlight-summary' in css_content

    assert '[data-theme="dark"] .llm-section-block.theme-highlight-action' in css_content
    assert 'body.dark-mode .llm-section-block.theme-highlight-action' in css_content
    assert '.dark-mode .llm-section-block.theme-highlight-action' in css_content

    # 2. 強調カードの純白高コントラスト文字色修復 (#ffffff !important)
    assert "#ffffff !important" in css_content

    # 3. 標準他4カードおよび親コンテナ.llm-cardのダークモード背景・文字色保証
    assert "color: #e2e8f0;" in css_content
    assert '[data-theme="dark"] .llm-card' in css_content
    assert "background: #111827 !important;" in css_content

    # 4. 上部ヘッダー（確信度, Model, 概算利回り帯）のダークモード文字視認性保証 (補正2)
    assert '[data-theme="dark"] .llm-confidence-tag' in css_content
    assert 'color: #e2e8f0 !important;' in css_content
    assert '[data-theme="dark"] .llm-model-tag' in css_content
    assert 'color: #cbd5e1 !important;' in css_content
    assert '[data-theme="dark"] .llm-meta-strip' in css_content
    assert 'color: #f1f5f9 !important;' in css_content


def test_dark_mode_table_ui_enhancements_issues_251_252_253():
    """案件 #251, #252, #253: ダークモード時銘柄テーブルUI修復（ヘッダー背景色、銘柄名リンク高輝度シアン化、ホバー白化防止）の検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # Issue #251: 銘柄コードヘッダーの背景・文字色アサーション
    assert '[data-theme="dark"] table.portfolio-table th' in css_content
    assert 'background-color: #1e293b !important;' in css_content
    assert 'color: #f8fafc !important;' in css_content

    # Issue #252: 銘柄名リンク高輝度シアンブルーアサーション
    assert '[data-theme="dark"] table.portfolio-table a' in css_content
    assert 'color: #38bdf8 !important;' in css_content
    assert 'color: #7dd3fc !important;' in css_content

    # Issue #253: ホバー時行白化防止（スレートハイライト #334155）アサーション
    assert '[data-theme="dark"] .portfolio-table tbody tr:hover' in css_content
    assert 'background-color: #334155 !important;' in css_content


def test_dark_mode_update_report_and_filter_styles_issue_255():
    """案件 #255: ダークモード時 銘柄取得レポート帯(.update-report)および各種検索・フィルタフォーム(input/select/option)の視認性修復の検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. 取得レポート帯 (.update-report) アサーション
    assert '[data-theme="dark"] .update-report' in css_content
    assert 'background-color: #1e293b !important;' in css_content
    assert 'border: 1px solid #334155 !important;' in css_content
    assert 'color: #e2e8f0 !important;' in css_content
    assert 'color: #cbd5e1 !important;' in css_content

    # 2. 検索・フィルタ入力フォーム (input/select/option/placeholder) アサーション
    assert '[data-theme="dark"] input[type="text"]' in css_content
    assert '[data-theme="dark"] select' in css_content
    assert 'border: 1px solid #475569 !important;' in css_content
    assert 'color: #f8fafc !important;' in css_content
    assert 'color: #94a3b8 !important;' in css_content


def test_dark_mode_dna_diagnosis_box_issue254():
    """案件 #254: 国内株式ポートフォリオ体質 (DNA) 診断ボックスおよびインフォアイコンのダークモード文字視認性・セレクタ網羅性の検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. dna-diagnosis-box のトリプルセレクタ網羅検証 ([data-theme="dark"], body.dark-mode, .dark-mode)
    assert '[data-theme="dark"] .dna-diagnosis-box' in css_content
    assert 'body.dark-mode .dna-diagnosis-box' in css_content
    assert '.dark-mode .dna-diagnosis-box' in css_content

    # 2. dna-diagnosis-box のスタイル定義アサーション (#1e293b, #38bdf8, #f8fafc)
    assert 'background-color: #1e293b !important;' in css_content
    assert 'border-left: 4px solid #38bdf8 !important;' in css_content
    assert 'color: #f8fafc !important;' in css_content

    # 3. dna-info-icon のトリプルセレクタとスタイル定義アサーション
    assert '[data-theme="dark"] .dna-info-icon' in css_content
    assert 'body.dark-mode .dna-info-icon' in css_content
    assert '.dark-mode .dna-info-icon' in css_content
    assert 'background: #334155 !important;' in css_content
    assert 'color: #cbd5e1 !important;' in css_content


def test_dark_mode_personality_and_searchable_select_issue_257():
    """案件 #257: ポートフォリオ性格診断ボックス(.personality-summary, .advice-box)および業種検索ラッパー(.searchable-select-wrapper)のダークモード視認性・高コントラスト修復の検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. personality-summary & advice-box のアサーション
    assert '[data-theme="dark"] .personality-summary' in css_content
    assert '[data-theme="dark"] .advice-box' in css_content
    assert 'border-left: 5px solid #38bdf8 !important;' in css_content

    # 2. searchable-select-wrapper のアサーション
    assert '[data-theme="dark"] .searchable-select-wrapper' in css_content
    assert 'border: 1px solid #475569 !important;' in css_content


def test_dark_mode_holding_management_modal_issue_258():
    """案件 #258: 保有情報管理モーダル(#management-modal)および編集フォーム(#holding-form-container)のダークモード文字同化・ハンパデザイン修復の検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. モーダル親コンテナ (#management-modal) アサーション
    assert '[data-theme="dark"] #management-modal' in css_content
    assert 'body.dark-mode #management-modal' in css_content
    assert '.dark-mode #management-modal' in css_content
    assert 'background-color: #111827 !important;' in css_content

    # 2. 編集フォームコンテナ (#holding-form-container) および見出し・ラベルアサーション
    assert '[data-theme="dark"] #holding-form-container' in css_content
    assert '[data-theme="dark"] #holding-form-title' in css_content
    assert 'color: #cbd5e1 !important;' in css_content

    # 3. フォーム入力欄 (number/text/textarea/select) アサーション
    assert '[data-theme="dark"] #holding-form input[type="number"]' in css_content
    assert '[data-theme="dark"] #holding-form textarea' in css_content

    # 4. モーダルボタン類 (btn-secondary, add-new-holding-btn, cancel-form-btn) アサーション
    assert '[data-theme="dark"] #add-new-holding-btn' in css_content
    assert '[data-theme="dark"] #cancel-form-btn' in css_content


def test_dark_mode_split_alert_modal_issue_260():
    """案件 #260: 株式分割適用確認モーダル(#split-alert-modal)および分割詳細カード(.split-detail-card)のダークモード文字同化・デザイン修復の検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. モーダル親コンテナ (#split-alert-modal) アサーション
    assert '[data-theme="dark"] #split-alert-modal .modal-content' in css_content
    assert 'body.dark-mode #split-alert-modal .modal-content' in css_content
    assert '.dark-mode #split-alert-modal .modal-content' in css_content

    # 2. 分割詳細カード (.split-detail-card) およびヘッダーアサーション
    assert '[data-theme="dark"] .split-detail-card' in css_content
    assert 'body.dark-mode .split-detail-card' in css_content
    assert '.dark-mode .split-detail-card' in css_content
    assert '[data-theme="dark"] .split-detail-header' in css_content

    # 3. プレビューテーブル (.split-detail-table) アサーション
    assert '[data-theme="dark"] .split-detail-table th' in css_content
    assert '[data-theme="dark"] .split-detail-table td' in css_content

    # 4. アクションボタン (btn-dismiss-split, btn-apply-split) アサーション
    assert '[data-theme="dark"] .btn-dismiss-split' in css_content
    assert '[data-theme="dark"] .btn-apply-split' in css_content
    assert 'background-color: #0284c7 !important;' in css_content


@patch("app._get_processed_asset_data")
@patch("app.scraper.get_exchange_rate")
def test_api_portfolio_analysis_daily_change_rankings(mock_get_rate, mock_get_assets):
    """案件 #261: /api/portfolio/analysis で daily_change_rankings が正しく取得できることの検証"""
    mock_get_rate.return_value = 150.0
    mock_get_assets.return_value = (
        [
            {
                "code": "9999",
                "name": "トヨタ",
                "asset_type": "jp_stock",
                "holdings": [{"quantity": 100, "purchase_price": 2000, "account_type": "特定口座"}],
                "price": 2500,
                "change": 50,
                "change_percent": 2.0,
                "currency": "JPY"
            }
        ],
        {"last_updated": "2026-08-13 12:00:00"}
    )

    response = client.get("/api/portfolio/analysis")
    assert response.status_code == 200
    data = response.json()
    assert "daily_change_rankings" in data
    assert "monthly_change_rankings" in data
    rankings = data["daily_change_rankings"]
    assert "day_gainers_top10" in rankings
    assert "day_losers_top10" in rankings
    assert len(rankings["day_gainers_top10"]) == 1
    assert rankings["day_gainers_top10"][0]["code"] == "9999"
    assert rankings["day_gainers_top10"][0]["daily_change_jpy"] == 5000.0


def test_daily_change_ranking_css_dark_mode_selectors():
    """案件 #261: 当日資産変動ランキングコンポーネントの CSS ダークモードトリプルセレクタの存在検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. ranking-card-header のトリプルセレクタ
    assert '[data-theme="dark"] .ranking-card-header' in css_content
    assert 'body.dark-mode .ranking-card-header' in css_content
    assert '.dark-mode .ranking-card-header' in css_content

    # 2. ranking-tab-btn のトリプルセレクタ
    assert '[data-theme="dark"] .ranking-tab-btn' in css_content
    assert 'body.dark-mode .ranking-tab-btn' in css_content
    assert '.dark-mode .ranking-tab-btn' in css_content

    # 3. ranking-table の th/td/hover のトリプルセレクタ
    assert '[data-theme="dark"] .ranking-table th' in css_content
    assert 'body.dark-mode .ranking-table th' in css_content
    assert '.dark-mode .ranking-table th' in css_content
    assert '[data-theme="dark"] .ranking-table td' in css_content

    # 4. gainer-badge / loser-badge のトリプルセレクタ
    assert '[data-theme="dark"] .ranking-change-badge.gainer-badge' in css_content
    assert 'body.dark-mode .ranking-change-badge.gainer-badge' in css_content
    assert '.dark-mode .ranking-change-badge.gainer-badge' in css_content
    assert '[data-theme="dark"] .ranking-change-badge.loser-badge' in css_content
    assert 'body.dark-mode .ranking-change-badge.loser-badge' in css_content
    assert '.dark-mode .ranking-change-badge.loser-badge' in css_content


def test_daily_ranking_modal_ui_and_dark_mode_issue261():
    """案件 #261: 当日資産変動ランキングモーダル(#daily-ranking-modal)の起動ボタン・モーダル構造・ダークモードトリプルセレクタ検証"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "analysis.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 1. HTML起動ボタンおよびモーダル構造アサーション
    assert 'id="btn-open-daily-ranking-modal"' in html_content
    assert 'id="daily-ranking-modal"' in html_content
    assert 'id="btn-close-daily-ranking-modal"' not in html_content
    assert 'id="btn-close-daily-ranking-modal-footer"' in html_content
    assert 'id="tab-gainers-top20"' in html_content
    assert 'id="tab-losers-top20"' in html_content
    assert 'class="modal-content large-modal"' in html_content
    assert 'class="modal-body"' in html_content

    # 2. CSS モーダル親コンテナのダークモードトリプルセレクタ検証
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert '[data-theme="dark"] #daily-ranking-modal .modal-content' in css_content
    assert 'body.dark-mode #daily-ranking-modal .modal-content' in css_content
    assert '.dark-mode #daily-ranking-modal .modal-content' in css_content
    assert '.btn-ranking-trigger' in css_content

    # 3. static/js/analysis.js におけるモーダル制御 (Escキー、背景クリック、閉じるボタン等) の検証
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'btnOpenDailyRankingModal' in js_content
    assert 'btnCloseDailyRankingModal' in js_content
    assert 'btnCloseDailyRankingModalFooter' in js_content
    assert "e.key === 'Escape'" in js_content
    assert "e.target === dailyRankingModal" in js_content


def test_daily_change_ranking_link_dark_mode_visibility_issue263():
    """案件 #263: 当日資産変動ランキング (TOP10) モーダル内銘柄名リンクのダークモード視認性修復検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. トリプルセレクタのアサーション
    assert '[data-theme="dark"] .ranking-table a' in css_content
    assert 'body.dark-mode .ranking-table a' in css_content
    assert '.dark-mode .ranking-table a' in css_content
    assert '[data-theme="dark"] .ranking-table .stock-code-link' in css_content

    # 2. スタイルプロパティのアサーション
    assert 'color: #38bdf8 !important;' in css_content
    assert 'color: #7dd3fc !important;' in css_content
    assert 'font-weight: 600;' in css_content
    assert 'text-decoration: underline;' in css_content


def test_dividend_spec_note_style_consistency_issue266():
    """案件 #266: dividend-spec-note のCSSスタイルが性格診断ボックスの配色仕様およびトリプルセレクタと一致していることを検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. ライトモード配色の検証
    assert ".dividend-spec-note" in content
    assert "#f0f7ff" in content  # アイスブルー背景
    assert "#0284c7" in content  # シアンブルータイトル/強調
    assert "#475569" in content  # スレートグレー注記

    # 2. ダークモード配色の検証
    assert "#1e293b" in content  # ダークスレート背景
    assert "#38bdf8" in content  # スカイブルー左枠線/タイトル/強調
    assert "#f8fafc" in content  # 本文文字色
    assert "#cbd5e1" in content  # ライトスレート注記

    # 3. トリプルセレクタの網羅性検証
    assert '[data-theme="dark"] .dividend-spec-note' in content
    assert 'body.dark-mode .dividend-spec-note' in content
    assert '.dark-mode .dividend-spec-note' in content


def test_monthly_ranking_modal_ui_issue270():
    """案件 #270: 期間切替メインタブ(⚡ 当日比 / 📅 先月比)およびJSレンダリング・金額非表示マスク連携の検証"""
    import os
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "analysis.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 1. HTML内メインタブおよびラジオ/ボタン要素の検証
    assert 'class="ranking-period-tabs"' in html_content
    assert 'id="tab-period-daily"' in html_content
    assert 'id="tab-period-monthly"' in html_content
    assert 'id="ranking-month-label"' in html_content

    # 2. static/js/analysis.js における期間切替タブ・月次ランキング描画・金額非表示マスク処理の検証
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'renderMonthlyChangeRankings' in js_content
    assert 'month_gainers_top10' in js_content
    assert 'month_losers_top10' in js_content
    assert 'tab-period-daily' in js_content
    assert 'tab-period-monthly' in js_content

def test_monthly_ranking_purchase_tag_ui_issue272():
    """案件 #272: 当月買付銘柄のサブテキストタグ (monthly-purchase-tag) レンダリングおよびCSS/JSの検証"""
    import os

    # 1. JSの当月買付表示ロジック、口/株単位判定、金額マスク連携の検証
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'is_purchased_this_month' in js_content
    assert 'purchased_quantity' in js_content
    assert 'monthly-purchase-tag' in js_content
    assert '🛒 当月買付:' in js_content
    assert "investment_trust' ? '口' : '株'" in js_content
    assert 'approx_invested_jpy' in js_content

    # 2. CSSのスタイル定義およびダークモード表示の検証
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert '.monthly-purchase-tag' in css_content
    assert 'color: #0284c7' in css_content or '#0284c7' in css_content
    assert 'color: #38bdf8' in css_content or '#38bdf8' in css_content


def test_profit_taking_grouped_by_code_issue277():
    """Issue #277: 同一銘柄が複数口座 (新NISA/特定等) に存在する場合に1行に合算されるか検証"""
    from app import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    # ダミーポートフォリオデータ: 同一銘柄 "7203" (トヨタ) を特定口座と新NISA口座の2つで保有
    mock_portfolio = [
        {
            "code": "7203",
            "name": "トヨタ自動車",
            "asset_type": "jp_stock",
            "holdings": [
                {
                    "account_type": "specific",
                    "quantity": 100,
                    "purchase_price": 2000,
                    "acquisition_price": 2000
                },
                {
                    "account_type": "nisa_growth",
                    "quantity": 100,
                    "purchase_price": 2000,
                    "acquisition_price": 2000
                }
            ]
        }
    ]

    mock_scraped_data = {
        "7203": {
            "code": "7203",
            "name": "トヨタ自動車",
            "price": "3,000",
            "per": "10.0",
            "pbr": "1.0",
            "roe": "10.0",
            "dividend_yield": "3.33",
            "annual_dividend": "100",
            "dividend_per_share": "100"
        }
    }

    processed_assets = [
        {
            "code": "7203",
            "name": "トヨタ自動車",
            "asset_type": "jp_stock",
            "price": "3,000",
            "per": "10.0",
            "pbr": "1.0",
            "roe": "10.0",
            "dividend_yield": "3.33",
            "annual_dividend": "100",
            "dividend_per_share": "100",
            "holdings": [
                {
                    "account_type": "specific",
                    "quantity": 100,
                    "purchase_price": 2000,
                    "acquisition_price": 2000
                },
                {
                    "account_type": "nisa_growth",
                    "quantity": 100,
                    "purchase_price": 2000,
                    "acquisition_price": 2000
                }
            ]
        }
    ]

    with patch("app.portfolio_manager.load_portfolio", return_value=mock_portfolio), \
         patch("app._get_processed_asset_data", return_value=(processed_assets, {})), \
         patch("app.history_manager.get_pending_split_alerts", return_value=[]), \
         patch("app.history_manager.save_snapshot"), \
         patch("app.history_manager.save_daily_data"), \
         patch("app.scraper.get_exchange_rate", return_value=155.0):
        test_cli = TestClient(app)
        response = test_cli.get("/api/portfolio/analysis")
        assert response.status_code == 200
        data = response.json()

        candidates = data.get("profit_taking_candidates", [])
        # 複数口座に分散していても7203は1件に集約合算されること
        codes = [c["code"] for c in candidates]
        assert codes.count("7203") == 1

        toyota = candidates[0]
        assert toyota["quantity"] == 200
        assert toyota["profit_loss"] == 200000.0
        assert toyota["estimated_annual_dividend"] == 20000.0
        assert toyota["market_value"] == 600000.0
        assert toyota["dividend_years_ratio"] == 10.0
        assert toyota["dividend_yield"] == 3.33
        assert toyota["profit_taking_badge"]["level"] == 1


def test_profit_taking_dividend_yield_issue280():
    """Issue #280: 利確検討リストへの直近配当利回り(%)表示追加の自動テスト"""
    import os

    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert '.yield-pill-highlight' in css_content

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert '配当利回り' in js_content
    assert 'yield-pill-highlight' in js_content


def test_profit_taking_masked_amount_issue278():
    """Issue #278: isAmountVisible=false 時における配当年数の伏字マスク化 (***年分) の自動テスト"""
    import os

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert '***年分' in js_content
    assert 'renderProfitTakingSection(fullAnalysisData.profit_taking_candidates' in js_content


def test_rankings_top20_html_and_js_issue274():
    """Issue #274: HTMLテンプレートおよびJSスクリプト内の TOP20 表記およびDOM要素のアサーション"""
    import os

    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "analysis.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    assert '🚀 資産変動ランキング TOP20' in html_content
    assert '🚀 資産変動ランキング (TOP20)' in html_content
    assert 'tab-gainers-top20' in html_content
    assert 'tab-losers-top20' in html_content

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'day_gainers_top20' in js_content
    assert 'month_gainers_top20' in js_content
    assert 'tab-gainers-top20' in js_content


def test_profit_taking_table_header_visibility():
    """ホワイトモード時の利確・銘柄入替検討リストテーブルヘッダー白文字固定 (#ffffff) の検証テスト"""
    import os

    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert '.profit-taking-table thead th' in css_content
    assert 'color: #ffffff !important' in css_content

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'profit-taking-table' in js_content
    assert 'color: #ffffff;' in js_content or 'color: #ffffff' in js_content


@patch("app._get_processed_asset_data")
@patch("app.scraper.get_exchange_rate", return_value=155.0)
@patch("app.llm_service_instance.diagnose_profit_taking")
def test_profit_taking_ai_endpoint_and_modal_issue281(mock_diagnose, mock_rate, mock_get_assets):
    mock_get_assets.return_value = ([{
        "code": "7203",
        "name": "トヨタ自動車",
        "industry": "輸送用機器",
        "asset_type": "jp_stock",
        "holdings": [{"quantity": 100, "acquisition_price": 2000}]
    }], {})
    """Issue #281: 専用APIエンドポイント /api/ai-diagnosis/profit-taking およびモーダル構造の自動テスト"""
    import os

    mock_diagnose.return_value = {
        "error": False,
        "code": "7203",
        "action": "PARTIAL_SELL",
        "action_label": "🟡 一部利確・元本回収を推奨",
        "target_sell_ratio": "保有株の1/2",
        "fundamentals_analysis": "良好",
        "profit_taking_advice": "元本回収推奨",
        "summary": "一部利確推奨"
    }

    # APIリクエストのテスト
    response = client.post("/api/ai-diagnosis/profit-taking", json={"code": "7203", "force": False})
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "7203"
    assert data["action"] == "PARTIAL_SELL"

    # HTML テンプレートに専用モーダル構造が含まれていること
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "analysis.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    assert 'id="profit-taking-ai-modal"' in html_content
    assert 'id="pt-ai-modal-body"' in html_content

    # static/js/analysis.js に連動処理が含まれていること
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert '/api/ai-diagnosis/profit-taking' in js_content
    assert 'openProfitTakingAiModal' in js_content


def test_profit_taking_ai_modal_reopen_display_flex_issue282():
    """Issue #282: モーダル2回目以降再オープン時の modal.style.display = 'flex' 復元のアサーションテスト"""
    import os

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    # openProfitTakingAiModal 内で hidden 削除と同時に style.display = 'flex' が設定されていること
    assert "openProfitTakingAiModal" in js_content
    assert "modal.style.display = 'flex';" in js_content or "modal.style.display = \"flex\";" in js_content
    assert "closeProfitTakingAiModal" in js_content


def test_profit_taking_ai_industry_growth_evaluation_issue283():
    """Issue #283: 利確AI診断での業種将来性・国策・成長力評価カードの描画および引き渡しテスト"""
    import os

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    # JSモーダルレンダリング内に「🚀 業種将来性・国策・成長力評価」が含まれていること
    assert "🚀 業種将来性・国策・成長力評価" in js_content
    assert "data.industry_growth_evaluation" in js_content


def test_profit_taking_ai_blank_modal_fix_issue286():
    """Issue #286: 利確AI診断モーダルの白紙表示不具合修正の検証 (JSエラーチェック強化 ✕ CSS文字色明示)"""
    import os

    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    # 1. JS側でのエラー多重防衛条件の検証
    assert "!data.action" in js_content
    assert "🔄 再診断をお試しください" in js_content

    # 2. CSS文字色明示指定の検証
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert ".pt-ai-result-card" in css_content
    assert "color: #0f172a !important;" in css_content
    assert "color: #f8fafc !important;" in css_content


def test_profit_taking_ai_retry_btn_visibility_issue287():
    """Issue #287: 利確AI診断モーダルの再診断ボタンの視認性・スタイリッシュピルクラスの検証"""
    import os

    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. style.css における .pt-ai-retry-btn のライト/ダークテーマ文字色指定検証
    assert ".pt-ai-retry-btn" in css_content
    assert "color: #4f46e5 !important;" in css_content
    assert "color: #818cf8 !important;" in css_content

    # 2. analysis.js 内で btn-link ではなく pt-ai-retry-btn が適用されていることの検証
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert "class=\"pt-ai-retry-btn ms-2\"" in js_content


def test_get_market_fibonacci_api_issue231():
    """Issue #231: GET /api/market/fibonacci の全7水準数値・絵文字・ゾーン判定検証"""
    res = client.get("/api/market/fibonacci")
    assert res.status_code == 200
    data = res.json()
    assert data["error"] is False
    assert "n225" in data
    assert "topix" in data
    assert "commentary" in data

    # 日経平均の全7レベル検証
    n225 = data["n225"]
    assert n225["name"] == "日経平均株価"
    assert len(n225["levels"]) == 7
    emojis = [l["emoji"] for l in n225["levels"]]
    assert emojis == ["🔴", "📉", "🎯", "⚖️", "🛡️", "⚠️", "🟢"]
    assert n225["levels"][0]["level"] == 0.0
    assert n225["levels"][-1]["level"] == 100.0
    assert n225["levels"][0]["price"] == n225["high_price"]
    assert n225["levels"][-1]["price"] == n225["low_price"]

    # TOPIXの全7レベル検証
    topix = data["topix"]
    assert topix["name"] == "TOPIX"
    assert len(topix["levels"]) == 7
    assert topix["levels"][0]["price"] == topix["high_price"]
    assert topix["levels"][-1]["price"] == topix["low_price"]


def test_post_market_fibonacci_refresh_api_issue231():
    """Issue #231: POST /api/market/fibonacci/refresh のGemini AIモック最新化テスト"""
    mock_llm_res = {
        "error": False,
        "n225": {
            "high_price": 75000.00,
            "high_date": "2026年8月",
            "low_price": 31000.00,
            "low_date": "2023年11月"
        },
        "topix": {
            "high_price": 4200.00,
            "high_date": "2026年8月",
            "low_price": 2300.00,
            "low_date": "2023年11月"
        },
        "market_commentary": "モックAIによるテスト市場分析コメントです。"
    }

    # テスト前の highlight_rules.json をバックアップし、テスト後に必ず復元する
    rules_path = "highlight_rules.json"
    backup = None
    if os.path.exists(rules_path):
        with open(rules_path, "r", encoding="utf-8") as f:
            backup = f.read()

    try:
        with patch("app.llm_service_instance.fetch_market_fibonacci_llm", return_value=mock_llm_res):
            res = client.post("/api/market/fibonacci/refresh")
            assert res.status_code == 200
            data = res.json()
            assert data["error"] is False
            assert data["n225"]["high_price"] == 75000.00
            assert data["n225"]["low_price"] == 31000.00
            assert data["topix"]["high_price"] == 4200.00
            assert data["topix"]["low_price"] == 2300.00
    finally:
        if backup is not None:
            with open(rules_path, "w", encoding="utf-8") as f:
                f.write(backup)


def test_market_fibonacci_frontend_elements_issue231():
    """Issue #231: / および /analysis テンプレートのJS組み込み・ボタン・モーダル・タブの存在を検証"""
    res_main = client.get("/")
    assert res_main.status_code == 200
    html_main = res_main.text

    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    html_analysis = res_analysis.text

    # 1. 専用 JS script タグ
    script_tag = '<script src="/static/js/marketFibonacci.js?v=1.0"></script>'
    assert script_tag in html_main, "main page missing marketFibonacci.js script tag"
    assert script_tag in html_analysis, "analysis page missing marketFibonacci.js script tag"

    # 2. トリガーボタン id="btn-show-market-fibonacci"
    btn_id = 'id="btn-show-market-fibonacci"'
    assert btn_id in html_main, "main page missing btn-show-market-fibonacci"
    assert btn_id in html_analysis, "analysis page missing btn-show-market-fibonacci"

    # 3. モーダルダイアログ id="market-fibonacci-modal"
    modal_id = 'id="market-fibonacci-modal"'
    assert modal_id in html_main, "main page missing market-fibonacci-modal"
    assert modal_id in html_analysis, "analysis page missing market-fibonacci-modal"

    # 4. タブ切り替え onclick="switchMarketFibTab(...)"
    assert 'onclick="switchMarketFibTab(\'n225\')"' in html_main
    assert 'onclick="switchMarketFibTab(\'topix\')"' in html_main
    assert 'onclick="switchMarketFibTab(\'n225\')"' in html_analysis
    assert 'onclick="switchMarketFibTab(\'topix\')"' in html_analysis

    # 5. JS ファイル内容のグローバル展開検証 & 新バッジ・ハイライトクラスアサーション (#289)
    assert os.path.exists("static/js/marketFibonacci.js")
    with open("static/js/marketFibonacci.js", "r", encoding="utf-8") as f:
        js_content = f.read()
    assert "window.switchMarketFibTab = switchMarketFibTab;" in js_content
    assert "window.fetchMarketFibonacciData = fetchMarketFibonacciData;" in js_content
    assert "window.initMarketFibonacciModal = initMarketFibonacciModal;" in js_content
    assert "fib-current-zone-badge" in js_content
    assert "fib-row-highlight" in js_content

    # 6. フッターピルボタン ✕ サマリーカードクラス検証 (#289, #290)
    assert "fib-close-pill-btn" in html_main
    assert "fib-close-pill-btn" in html_analysis
    assert "fib-summary-card" in html_main
    assert "fib-summary-card" in html_analysis
    assert "fib-summary-title" in js_content


def test_split_alert_message_text_issue292():
    """案件 #292: 株式分割アラートのバナーおよびモーダル本文の文言が『監視銘柄』に補正されているか検証"""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    html_content = response.text

    # ポジティブテスト (新文言の存在確認)
    assert "株式分割（または併合）が検知された監視銘柄があります。" in html_content
    assert "以下の監視銘柄で株式分割（または併合）が検知されました。" in html_content

    # ネガティブテスト (旧文言の完全排除確認)
    assert "検知された保有銘柄" not in html_content
    assert "以下の保有銘柄で" not in html_content


def test_market_fibonacci_auto_update_on_new_high_and_low_issue295():
    """案件 #295: リアルタイム現在値が最高値を突破/最安値を下回った際にフィボナッチ水準が自動繰り上げ/繰り下げ更新されるか検証"""
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock
    from app import app

    client = TestClient(app)

    # 1. 現在値が過去最高値を突破した場合 (TOPIX 現在値 4146.0 > 過去最高値 4101.96)
    mock_idx_scraper = MagicMock()
    mock_idx_scraper.fetch_data.side_effect = lambda code: (
        {"price": "68,000.0"} if code == "998407.O" else {"price": "4,146.0"}
    )

    mock_llm_res = {
        "error": False,
        "n225": {"high_price": 72353.0, "high_date": "2026年6月", "low_price": 30500.29, "low_date": "2023年10月"},
        "topix": {"high_price": 4101.96, "high_date": "2026年7月", "low_price": 2217.10, "low_date": "2023年10月"},
        "market_commentary": "TOPIX新高値更新テスト"
    }

    with patch("app.scraper.get_scraper", return_value=mock_idx_scraper), \
         patch("app.llm_service_instance.fetch_market_fibonacci_llm", return_value=mock_llm_res), \
         patch("os.replace", MagicMock()):
        
        # POST /refresh の検証
        res_post = client.post("/api/market/fibonacci/refresh")
        assert res_post.status_code == 200

        # GET / の検証 (動的保護)
        res_get = client.get("/api/market/fibonacci")
        assert res_get.status_code == 200
        data = res_get.json()
        assert data["error"] is False
        
        # TOPIXの最高値（0.0%水準）が現在値 4146.0 に繰り上がっていること
        topix_info = data["topix"]
        assert topix_info["high_price"] == 4146.0
        assert topix_info["levels"][0]["price"] == 4146.0

    # 2. 現在値が過去最安値を下回った場合 (N225 現在値 28000.0 < 過去最安値 30500.29)
    mock_idx_scraper_low = MagicMock()
    mock_idx_scraper_low.fetch_data.side_effect = lambda code: (
        {"price": "28,000.0"} if code == "998407.O" else {"price": "2,500.0"}
    )

    with patch("app.scraper.get_scraper", return_value=mock_idx_scraper_low), \
         patch("app.llm_service_instance.fetch_market_fibonacci_llm", return_value=mock_llm_res), \
         patch("os.replace", MagicMock()):
        
        res_get_low = client.get("/api/market/fibonacci")
        assert res_get_low.status_code == 200
        data_low = res_get_low.json()
        
        # 日経平均の最安値（100.0%水準）が現在値 28000.0 に繰り下がっていること
        n225_info = data_low["n225"]
        assert n225_info["low_price"] == 28000.0
        assert n225_info["levels"][6]["price"] == 28000.0


def test_investment_policy_modal_ui_theme_issue296():
    """案件 #296: 投資方針モーダルに丸型閉じるボタンおよびダークモード用CSS定義が存在するか検証"""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    # 1. HTML構造の検証
    res_html = client.get("/")
    assert res_html.status_code == 200
    html_text = res_html.text

    assert 'id="btn-close-policy-modal" class="modal-close modal-close-btn"' in html_text
    assert 'id="policy-api-key-input"' in html_text
    assert 'id="policy-prompt-textarea"' in html_text
    assert 'id="policy-model-select"' in html_text

    # 2. CSSルールの存在検証
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200
    css_text = res_css.text

    assert '#policy-prompt-textarea' in css_text
    assert '#policy-api-key-input' in css_text
    assert '#policy-model-select' in css_text
    assert '[data-theme="dark"] #investment-policy-modal .modal-content' in css_text
    assert '[data-theme="dark"] #policy-prompt-textarea' in css_text


def test_add_asset_endpoint_custom_jp_stock_codes_issue294():
    """案件 #294: 6623.N (名証), 130A (新規格), 7203.T (サフィックス) 等の銘柄コードが国内株として正常判定・追加されるかテスト"""
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    # モックの準備 (本番DB書き込み保護)
    mock_scraped = {"code": "6623.N", "name": "テスト名証", "price": 1000, "asset_type": "jp_stock"}

    with patch("app.portfolio_manager.add_asset", return_value=True) as mock_add, \
         patch("app.portfolio_manager.get_stock_info", side_effect=lambda code: {"code": code, "holdings": []}), \
         patch("app._fetch_scraped_data_with_cache", return_value=mock_scraped):
        
        # 1. 6623.N (名証サフィックス)
        res1 = client.post("/api/stocks", json={"code": "6623.N"})
        assert res1.status_code == 200
        mock_add.assert_called_with("6623.N", "jp_stock")

        # 2. 130A (英数字混在国内株)
        res2 = client.post("/api/stocks", json={"code": "130A"})
        assert res2.status_code == 200
        mock_add.assert_called_with("130A", "jp_stock")

        # 3. 7203.T (東証サフィックス付き)
        res3 = client.post("/api/stocks", json={"code": "7203.T"})
        assert res3.status_code == 200
        mock_add.assert_called_with("7203.T", "jp_stock")

        # 4. 米国株 AAPL, BRK.B が誤って jp_stock にならないことの分離検証
        res4 = client.post("/api/stocks", json={"code": "AAPL"})
        assert res4.status_code == 200
        mock_add.assert_called_with("AAPL", "us_stock")


def test_get_stocks_instant_cancellation_issue299():
    """案件 #299: クライアント切断検知時、全銘柄タスクが asyncio.sleep 待機を一切消費せず 0秒で即時一括キャンセル完了することのテスト"""
    from fastapi.testclient import TestClient
    from app import app, _get_processed_asset_data
    import asyncio
    import time
    from unittest.mock import patch, MagicMock

    client = TestClient(app)

    # 1. CSSスタイルの存在検証
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200
    assert '.btn-updating-cancel' in res_css.text

    # 2. クライアント切断時、複数銘柄(5件)が asyncio.sleep 待機を一切消費せず 0秒で即時一括キャンセル完了することを検証
    mock_request = MagicMock()
    mock_request.is_disconnected = MagicMock(side_effect=lambda: True)

    dummy_portfolio = [
        {"code": f"720{i}", "asset_type": "jp_stock"} for i in range(5)
    ]

    start_time = time.perf_counter()
    with patch("app.history_manager.save_daily_data") as mock_save_daily, \
         patch("app.portfolio_manager.load_portfolio", return_value=dummy_portfolio):
        
        processed_data, metadata = asyncio.run(_get_processed_asset_data(request=mock_request, force=True))
        
        # 1銘柄につき 1.5秒〜4秒待機するはずが、即時キャンセルフラグにより 0.5秒未満で一括終了すること
        elapsed = time.perf_counter() - start_time
        assert elapsed < 0.5, f"Expected instant cancellation (<0.5s), but took {elapsed:.2f}s"
        
        # 切断が検知されたため、DB保存(save_daily_data)が一切呼び出されていないこと
        mock_save_daily.assert_not_called()
        assert processed_data == []


def test_analytics_page_asset_history_mom_summary_issue300():
    """案件 #300: analytics ページの資産推移における先月末比要素・CSS・JSロジックの存在および表示検証"""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    # 1. templates/analysis.html 内に #asset-history-mom-summary が存在すること
    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    assert 'id="asset-history-mom-summary"' in res_analysis.text
    assert 'id="asset-mom-value"' in res_analysis.text
    assert 'id="capital-mom-value"' in res_analysis.text

    # 2. static/css/style.css 内に .history-mom-summary スタイルが存在すること
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200
    assert '.history-mom-summary' in res_css.text

    # 3. static/js/analysis.js 内に先月末比(Tooltip afterLabel & サマリー描画)のスクリプトが存在すること
    res_js = client.get("/static/js/analysis.js")
    assert res_js.status_code == 200
    assert '先月末比:' in res_js.text
    assert 'asset-history-mom-summary' in res_js.text


def test_modal_responsive_styles_issue301():
    """案件 #301: 小画面・ノートPCでのモーダル上下削れを防止する一元標準レスポンシブCSSおよびHTML構造の検証"""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    # 1. CSSルール内の max-height: calc(100vh - 40px) および Flexbox 設定の検証
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200
    assert 'max-height: calc(100vh - 40px);' in res_css.text
    assert 'overscroll-behavior: contain;' in res_css.text

    # 2. templates/index.html および templates/analysis.html 内のモーダル共通構造検証
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert 'id="market-fibonacci-modal"' in res_index.text
    # .fib-tabsが.modal-header内部（.modal-bodyの直前）に存在することを確認
    assert 'class="modal-header d-flex flex-column' in res_index.text
    assert 'id="fib-tab-n225"' in res_index.text
    assert 'id="fib-tab-topix"' in res_index.text

    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    assert 'id="market-fibonacci-modal"' in res_analysis.text
    assert 'class="modal-header d-flex flex-column' in res_analysis.text
    assert 'id="fib-tab-n225"' in res_analysis.text
    assert 'id="fib-tab-topix"' in res_analysis.text


def test_modal_padding_issue302():
    """案件 #302: モーダル左端・右端の詰まり解消とパディング一元標準化 (padding: 1.25rem 1.5rem) の検証"""
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app)

    # 1. style.css 内で .modal-body の左右パディング 1.5rem が設定されていること
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200
    assert "padding: 1.25rem 1.5rem;" in res_css.text

    # 2. templates/index.html 内に padding: 20px 0; や padding: 15px 0; が残っていないこと
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert 'style="padding: 20px 0;"' not in res_index.text
    assert 'style="padding: 15px 0;"' not in res_index.text

    # 3. templates/analysis.html 内に padding: 15px 0; や padding: 18px 5px; が残っていないこと
    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    assert 'style="padding: 15px 0;' not in res_analysis.text
    assert 'style="padding: 18px 5px;' not in res_analysis.text
