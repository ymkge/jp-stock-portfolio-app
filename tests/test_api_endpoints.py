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
    """トップ画面 (/) および分析画面 (/analysis) に免責事項バナー・フッター・法的4要素・AIモーダル注記が正しく含まれていることを検証"""
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
    # 再表示ボタンおよびAI診断モーダル注記の検証
    assert "btn-restore-disclaimer" in res_index.text
    assert "llm-disclaimer-note" in res_index.text

    res_analysis = client.get("/analysis")
    assert res_analysis.status_code == 200
    assert "top-disclaimer-banner" in res_analysis.text
    assert "app-disclaimer-footer" in res_analysis.text
    assert "投資助言等の否定" in res_analysis.text
    assert "データの無保証" in res_analysis.text
    assert "AI診断結果の性質" in res_analysis.text
    assert "完全免責" in res_analysis.text
    assert "btn-restore-disclaimer" in res_analysis.text


def test_llm_modal_first_view_and_responsive_css():
    """案件 #248: AI診断モーダルのファーストVIEW完全収容、内部スクロール、グリッドレイアウト、ダークモードCSSの検証"""
    import os
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. モーダル高さ制限と内部スクロール検証
    assert "#llm-diagnosis-modal .modal-dialog" in css_content
    assert "#llm-diagnosis-modal .modal-content" in css_content
    assert "#llm-diagnosis-modal .modal-body" in css_content
    assert "max-height: 88vh;" in css_content
    assert "max-height: calc(88vh - 120px);" in css_content
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

    # 5. 他モーダルへの副作用防止確認（汎用モーダルクラスを直接汚染せず#llm-diagnosis-modalでスコープしているか）
    assert "#llm-diagnosis-modal .modal-body {" in css_content

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
    assert 'id="tab-gainers-top10"' in html_content
    assert 'id="tab-losers-top10"' in html_content
    assert 'max-height: 85vh' in html_content
    assert 'overflow-y: auto' in html_content

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


def test_profit_taking_api_and_ui_issue273_and_275():
    """Issue #273 & #275: 利確検討リスト (profit_taking_candidates) の専用モーダル化およびAPI・UI連動の自動テスト"""
    import os

    # 1. JSのモーダル開閉ロジックおよび描画関数の検証
    js_path = os.path.join(os.path.dirname(__file__), "..", "static", "js", "analysis.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    assert 'profit_taking_candidates' in js_content
    assert 'renderProfitTakingSection' in js_content
    assert 'renderProfitTakingBadge' in js_content
    assert 'btn-open-profit-taking-modal' in js_content
    assert 'profit-taking-modal' in js_content

    # 2. HTMLのトリガーボタンおよびモーダル構造の検証 (旧カード非存在の検証)
    html_path = os.path.join(os.path.dirname(__file__), "..", "templates", "analysis.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    assert 'btn-open-profit-taking-modal' in html_content
    assert 'profit-taking-modal' in html_content
    assert 'profit-taking-content' in html_content
    # 常時表示カード (.profit-taking-section) は分析ページ本体から削除されていること
    assert 'class="profit-taking-section card"' not in html_content

    # 3. CSSの専用モーダルダークモードトリプルセレクタの検証
    css_path = os.path.join(os.path.dirname(__file__), "..", "static", "css", "style.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    assert '#profit-taking-modal' in css_content
    assert '[data-theme="dark"] #profit-taking-modal' in css_content
    assert 'body.dark-mode #profit-taking-modal' in css_content
    assert '.dark-mode #profit-taking-modal' in css_content









