/**
 * marketAnomaly.js
 * 投資のアノマリー（季節性・傾向）参照・分析機能 (#298, #307)
 */

let anomalyData = null;
let currentSelectedMonth = new Date().getMonth() + 1;
let currentAnomalyTab = 'current'; // 'current' | 'calendar' | 'proverbs'
let aiDiagnosisCache = {}; // { 1: { commentary: '...', diagnosed_at: '...', is_cached: true }, ... }

document.addEventListener('DOMContentLoaded', () => {
    initAnomalyModal();
});

function initAnomalyModal() {
    const btnOpen = document.getElementById('btn-open-market-anomaly-modal');
    const btnCloseHeader = document.getElementById('btn-close-investment-anomaly-modal');
    const btnCloseFooter = document.getElementById('btn-close-investment-anomaly-modal-footer');
    const btnRefreshAi = document.getElementById('btn-refresh-anomaly-ai');
    const modal = document.getElementById('investment-anomaly-modal');

    if (btnOpen) {
        btnOpen.addEventListener('click', () => {
            openAnomalyModal();
        });
    }

    if (btnCloseHeader) {
        btnCloseHeader.addEventListener('click', closeAnomalyModal);
    }
    if (btnCloseFooter) {
        btnCloseFooter.addEventListener('click', closeAnomalyModal);
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeAnomalyModal();
            }
        });
    }

    if (btnRefreshAi) {
        btnRefreshAi.addEventListener('click', () => {
            fetchAnomalyAiDiagnosis(currentSelectedMonth, true);
        });
    }
}

async function openAnomalyModal() {
    const modal = document.getElementById('investment-anomaly-modal');
    if (!modal) return;

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    if (!anomalyData) {
        await loadAnomalyData();
    } else {
        renderAnomalyModalContent();
    }
}

function closeAnomalyModal() {
    const modal = document.getElementById('investment-anomaly-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
    document.body.style.overflow = '';
}

async function loadAnomalyData() {
    const container = document.getElementById('anomaly-modal-body-container');
    if (container) {
        container.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"></div><div class="mt-2 text-muted">アノマリーデータを読み込み中...</div></div>';
    }

    try {
        const resp = await fetch('/api/anomalies');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        anomalyData = data;
        if (data.current_month) {
            currentSelectedMonth = data.current_month;
        }
        renderAnomalyModalContent();
    } catch (err) {
        console.error('Failed to load anomaly data:', err);
        if (container) {
            container.innerHTML = `<div class="alert alert-danger my-3">アノマリーデータの取得に失敗しました: ${err.message}</div>`;
        }
    }
}

function switchAnomalyTab(tabName) {
    currentAnomalyTab = tabName;
    const btnTabCurrent = document.getElementById('anomaly-tab-current');
    const btnTabCalendar = document.getElementById('anomaly-tab-calendar');
    const btnTabProverbs = document.getElementById('anomaly-tab-proverbs');

    if (btnTabCurrent) btnTabCurrent.classList.toggle('active', tabName === 'current');
    if (btnTabCalendar) btnTabCalendar.classList.toggle('active', tabName === 'calendar');
    if (btnTabProverbs) btnTabProverbs.classList.toggle('active', tabName === 'proverbs');

    renderAnomalyModalContent();
}

function selectAnomalyMonth(monthNum) {
    currentSelectedMonth = monthNum;
    currentAnomalyTab = 'current';
    
    const btnTabCurrent = document.getElementById('anomaly-tab-current');
    const btnTabCalendar = document.getElementById('anomaly-tab-calendar');
    if (btnTabCurrent) btnTabCurrent.classList.add('active');
    if (btnTabCalendar) btnTabCalendar.classList.remove('active');

    renderAnomalyModalContent();
}

function updateAnomalyAiButtonLabel(monthNum) {
    const btnRefreshAi = document.getElementById('btn-refresh-anomaly-ai');
    if (btnRefreshAi) {
        btnRefreshAi.innerHTML = `🤖 Gemini AIで${monthNum}月を診断`;
        btnRefreshAi.title = `Gemini AI で${monthNum}月のアノマリー診断を生成`;
    }
}

function renderAnomalyModalContent() {
    const container = document.getElementById('anomaly-modal-body-container');
    if (!container || !anomalyData) return;

    if (currentAnomalyTab === 'current') {
        renderCurrentMonthTab(container);
    } else if (currentAnomalyTab === 'calendar') {
        renderCalendarTab(container);
    } else if (currentAnomalyTab === 'proverbs') {
        renderProverbsTab(container);
    }
}

function renderCurrentMonthTab(container) {
    const monthlyMap = anomalyData.monthly_anomalies || {};
    const item = monthlyMap[String(currentSelectedMonth)] || monthlyMap[currentSelectedMonth] || {
        month: currentSelectedMonth,
        title: `${currentSelectedMonth}月のアノマリー`,
        summary: '季節的傾向と市場動向',
        risk_level: 'medium',
        reasons: [],
        actions: ''
    };

    updateAnomalyAiButtonLabel(currentSelectedMonth);

    const isThisMonth = currentSelectedMonth === (anomalyData.current_month || new Date().getMonth() + 1);
    const monthBadgeTag = isThisMonth ? '<span class="badge bg-primary ms-2" style="font-size: 0.75rem;">今月</span>' : '';

    let riskBadgeHtml = '<span class="badge bg-secondary">中リスク</span>';
    if (item.risk_level === 'high') {
        riskBadgeHtml = '<span class="badge bg-danger" style="font-size: 0.8rem;">🔴 高警戒・高ボラティリティ</span>';
    } else if (item.risk_level === 'low') {
        riskBadgeHtml = '<span class="badge bg-success" style="font-size: 0.8rem;">🟢 好調期待・低リスク</span>';
    } else {
        riskBadgeHtml = '<span class="badge bg-warning text-dark" style="font-size: 0.8rem;">🟡 中立・中リスク</span>';
    }

    const reasonsListHtml = (item.reasons || []).map(r => `<li style="margin-bottom: 6px; line-height: 1.5;">${r}</li>`).join('');

    const cached = aiDiagnosisCache[currentSelectedMonth];
    let commentaryContent = `『🤖 Gemini AIで${currentSelectedMonth}月を診断』ボタンを押すと、現在のアノマリーに基づくワンポイントアドバイスを生成します。`;
    let timeContent = '';

    if (cached) {
        commentaryContent = cached.commentary || commentaryContent;
        if (cached.diagnosed_at) {
            timeContent = `${cached.is_cached ? '(キャッシュ)' : '(最新)'} ${cached.diagnosed_at} 更新`;
        }
    }

    container.innerHTML = `
        <div class="anomaly-month-header-card card p-3 mb-3" style="background: var(--card-bg, #f8fafc); border-left: 4px solid var(--primary-color, #4f46e5); border-radius: 8px;">
            <div class="d-flex justify-content-between align-items-center mb-2 flex-wrap gap-2">
                <div class="d-flex align-items-center gap-2">
                    <h3 style="margin: 0; font-size: 1.3rem;" class="fw-bold">📅 ${currentSelectedMonth}月のアノマリー</h3>
                    ${monthBadgeTag}
                </div>
                <div>${riskBadgeHtml}</div>
            </div>
            <div class="fw-bold text-primary mb-1" style="font-size: 1.05rem;">
                ${item.title || ''}
            </div>
            <div class="text-muted" style="font-size: 0.9rem;">
                ${item.summary || ''}
            </div>
        </div>

        <div class="row g-3">
            <div class="col-md-6">
                <div class="card h-100 p-3" style="border-radius: 8px;">
                    <h5 class="fw-bold mb-2" style="font-size: 0.95rem; color: var(--primary-color, #4f46e5); display: flex; align-items: center; gap: 6px;">
                        💡 発生の主な理由・歴史的背景
                    </h5>
                    <ul class="mb-0 ps-3 text-secondary" style="font-size: 0.88rem;">
                        ${reasonsListHtml || '<li>特筆すべき背景データなし</li>'}
                    </ul>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card h-100 p-3" style="border-radius: 8px;">
                    <h5 class="fw-bold mb-2" style="font-size: 0.95rem; color: var(--primary-color, #4f46e5); display: flex; align-items: center; gap: 6px;">
                        ⚡ 個人投資家のアクション指針
                    </h5>
                    <div class="text-secondary" style="font-size: 0.88rem; line-height: 1.6;">
                        ${item.actions || '慎重なポジション調整を心がけてください。'}
                    </div>
                </div>
            </div>
        </div>

        <!-- AI相場環境×アノマリー診断カード -->
        <div id="anomaly-ai-commentary-card" class="card mt-3 p-3" style="background: rgba(99, 102, 241, 0.05); border: 1px solid rgba(99, 102, 241, 0.2); border-radius: 8px;">
            <div style="font-weight: 600; font-size: 0.9rem; color: var(--primary-color, #4f46e5); margin-bottom: 6px; display: flex; align-items: center; justify-content: space-between;">
                <span class="d-flex align-items-center gap-1">🤖 Gemini AI ${currentSelectedMonth}月のアノマリーワンポイント解説</span>
                <span id="anomaly-ai-updated-at" class="text-muted fw-normal" style="font-size: 0.75rem;">${timeContent}</span>
            </div>
            <div id="anomaly-ai-commentary-text" style="font-size: 0.85rem; line-height: 1.5; color: var(--text-color, #334155);">
                ${commentaryContent}
            </div>
        </div>
    `;
}

function renderCalendarTab(container) {
    const monthlyMap = anomalyData.monthly_anomalies || {};
    const curM = anomalyData.current_month || new Date().getMonth() + 1;

    let gridHtml = '<div class="row row-cols-1 row-cols-sm-2 row-cols-md-3 row-cols-lg-4 g-3 mb-3">';

    for (let m = 1; m <= 12; m++) {
        const item = monthlyMap[String(m)] || monthlyMap[m] || {};
        const isCurrent = m === curM;
        const isSelected = m === currentSelectedMonth;

        let riskTag = '🟡 中立';
        let borderStyle = 'border: 1px solid var(--border-color, #e2e8f0);';
        if (item.risk_level === 'high') {
            riskTag = '🔴 高警戒';
        } else if (item.risk_level === 'low') {
            riskTag = '🟢 好調';
        }

        if (isSelected) {
            borderStyle = 'border: 2px solid var(--primary-color, #4f46e5); background: rgba(79, 70, 229, 0.05);';
        }

        gridHtml += `
            <div class="col">
                <div class="card h-100 p-2 anomaly-month-grid-card" onclick="selectAnomalyMonth(${m})" style="cursor: pointer; ${borderStyle} border-radius: 8px; transition: transform 0.15s ease;">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span class="fw-bold" style="font-size: 0.95rem;">${m}月 ${isCurrent ? '<span class="badge bg-primary" style="font-size: 0.65rem;">今月</span>' : ''}</span>
                        <span style="font-size: 0.75rem;">${riskTag}</span>
                    </div>
                    <div class="fw-bold text-truncate text-primary" style="font-size: 0.82rem;" title="${item.title || ''}">
                        ${item.title || ''}
                    </div>
                    <div class="text-muted text-truncate" style="font-size: 0.75rem; margin-top: 4px;" title="${item.summary || ''}">
                        ${item.summary || ''}
                    </div>
                </div>
            </div>
        `;
    }

    gridHtml += '</div>';

    container.innerHTML = `
        <div class="mb-2 text-muted" style="font-size: 0.85rem;">
            💡 気になる月をクリックすると、その月のアノマリー詳細とアドバイスへ切り替わります。
        </div>
        ${gridHtml}
    `;
}

function renderProverbsTab(container) {
    const proverbs = anomalyData.market_proverbs || [];
    if (!proverbs.length) {
        container.innerHTML = '<div class="text-center py-4 text-muted">格言データがありません</div>';
        return;
    }

    const cardsHtml = proverbs.map(item => `
        <div class="card p-3 mb-3" style="border-left: 4px solid #3b82f6; border-radius: 8px;">
            <div class="fw-bold mb-1" style="font-size: 1rem; color: var(--primary-color, #1e293b);">
                📜 ${item.title || ''}
            </div>
            ${item.subtitle ? `<div class="text-primary mb-2 fw-semibold" style="font-size: 0.82rem;">${item.subtitle}</div>` : ''}
            <div class="text-secondary" style="font-size: 0.88rem; line-height: 1.5;">
                ${item.description || ''}
            </div>
        </div>
    `).join('');

    container.innerHTML = `
        <div class="mb-2 text-muted" style="font-size: 0.85rem;">
            💡 株式市場で長年言い伝えられている代表的な格言・慣習の解説です。
        </div>
        <div>
            ${cardsHtml}
        </div>
    `;
}

async function fetchAnomalyAiDiagnosis(monthNum, force = true) {
    const textEl = document.getElementById('anomaly-ai-commentary-text');
    const timeEl = document.getElementById('anomaly-ai-updated-at');
    const btnRefreshAi = document.getElementById('btn-refresh-anomaly-ai');
    if (!textEl) return;

    if (btnRefreshAi) {
        btnRefreshAi.disabled = true;
        btnRefreshAi.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> 診断生成中...';
    }

    textEl.innerHTML = `<span class="spinner-border spinner-border-sm text-primary me-2"></span>Gemini AI で${monthNum}月のアノマリーを最新診断中...`;

    try {
        const resp = await fetch('/api/ai-diagnosis/anomaly', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ month: monthNum, force: force })
        });

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const result = await resp.json();

        if (result.error) {
            textEl.innerHTML = `<span class="text-danger">⚠️ ${result.message}</span>`;
            return;
        }

        const commentaryText = result.commentary || '診断結果を取得できませんでした。';
        textEl.innerText = commentaryText;

        const timeStr = `${result.is_cached ? '(キャッシュ)' : '(最新)'} ${result.diagnosed_at || ''} 更新`;
        if (timeEl) {
            timeEl.innerText = timeStr;
        }

        // フロントエンドキャッシュに保存
        aiDiagnosisCache[monthNum] = {
            commentary: commentaryText,
            diagnosed_at: result.diagnosed_at || '',
            is_cached: result.is_cached || false
        };
    } catch (err) {
        console.error('Failed to fetch anomaly AI diagnosis:', err);
        textEl.innerHTML = `<span class="text-danger">⚠️ AI診断通信エラー: ${err.message}</span>`;
    } finally {
        if (btnRefreshAi) {
            btnRefreshAi.disabled = false;
            updateAnomalyAiButtonLabel(monthNum);
        }
    }
}
