/**
 * 主要指数 フィボナッチリトレースメント モーダル制御モジュール (#231)
 */

let marketFibData = null;
let currentFibTab = 'n225';

async function fetchMarketFibonacciData(isRefresh = false) {
    const summaryEl = document.getElementById('fib-index-summary-card');
    const tableBodyEl = document.getElementById('market-fib-table-body');
    const commentaryEl = document.getElementById('market-fib-ai-commentary-text');
    const refreshBtn = document.getElementById('btn-refresh-market-fib');

    if (summaryEl) summaryEl.innerHTML = '<div style="text-align: center; padding: 10px;">⏳ フィボナッチ水準を計算中...</div>';
    if (tableBodyEl) tableBodyEl.innerHTML = '<tr><td colspan="3" style="text-align: center; padding: 15px;">データを読み込み中...</td></tr>';
    if (refreshBtn && isRefresh) {
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = '⏳ Gemini AI最新化中...';
    }

    try {
        const url = isRefresh ? '/api/market/fibonacci/refresh' : '/api/market/fibonacci';
        const options = isRefresh ? { method: 'POST' } : { method: 'GET' };
        const response = await fetch(url, options);
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTPエラー ${response.status}`);
        }

        const data = await response.json();
        marketFibData = data;
        renderMarketFibonacciModal();
    } catch (err) {
        console.error('Failed to fetch market fibonacci data:', err);
        if (summaryEl) summaryEl.innerHTML = `<div style="color: #ef4444; padding: 10px;">⚠️ エラー: ${err.message}</div>`;
        if (commentaryEl) commentaryEl.innerText = `エラーが発生しました: ${err.message}`;
    } finally {
        if (refreshBtn) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = '🔄 Gemini AIで最新化';
        }
    }
}

function switchMarketFibTab(tabKey) {
    currentFibTab = tabKey;
    const tabN225 = document.getElementById('fib-tab-n225');
    const tabTOPIX = document.getElementById('fib-tab-topix');

    if (tabN225) tabN225.classList.toggle('active', tabKey === 'n225');
    if (tabTOPIX) tabTOPIX.classList.toggle('active', tabKey === 'topix');

    renderMarketFibonacciModal();
}

function renderMarketFibonacciModal() {
    if (!marketFibData) return;

    const indexData = marketFibData[currentFibTab];
    if (!indexData) return;

    const summaryEl = document.getElementById('fib-index-summary-card');
    const tableBodyEl = document.getElementById('market-fib-table-body');
    const commentaryEl = document.getElementById('market-fib-ai-commentary-text');
    const updatedTagEl = document.getElementById('market-fib-updated-tag');

    if (updatedTagEl) {
        updatedTagEl.innerText = `基準更新: ${marketFibData.updated_at || '最新'}`;
    }

    // 1. サマリーカード描画
    if (summaryEl) {
        const unit = currentFibTab === 'n225' ? '円' : 'pt';
        const curPriceStr = indexData.current_price > 0 ? `${indexData.current_price.toLocaleString()} ${unit}` : '取得中...';
        summaryEl.innerHTML = `
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                <div>
                    <h4 class="fib-summary-title">${indexData.name}</h4>
                    <div class="fib-summary-date">
                        最安値: <strong class="fib-summary-low">${indexData.low_price.toLocaleString()}${unit}</strong> (${indexData.low_date}) 〜 
                        最高値: <strong class="fib-summary-high">${indexData.high_price.toLocaleString()}${unit}</strong> (${indexData.high_date})
                    </div>
                </div>
                <div style="text-align: right;">
                    <div class="fib-summary-label">現在値 & 到達エリア</div>
                    <div class="fib-summary-price">
                        ${curPriceStr}
                    </div>
                    <span class="fib-current-zone-badge">${indexData.current_zone}</span>
                </div>
            </div>
        `;
    }

    // 2. テーブル描画
    if (tableBodyEl) {
        const unit = currentFibTab === 'n225' ? '円' : 'pt';
        let html = '';
        (indexData.levels || []).forEach((item) => {
            const isHighlight = indexData.current_zone && indexData.current_zone.includes(item.emoji);
            const rowClass = isHighlight ? 'class="fib-row-highlight"' : '';
            
            html += `
                <tr ${rowClass} style="border-bottom: 1px solid var(--border-color, #e2e8f0);">
                    <td style="padding: 10px 12px;">
                        <span style="font-size: 1.1rem; margin-right: 6px;">${item.emoji}</span>
                        <span>${item.name}</span>
                    </td>
                    <td style="padding: 10px 12px; text-align: right; font-family: monospace; font-size: 0.95rem;">
                        <strong>${item.price.toLocaleString()}</strong> <small>${unit}</small>
                    </td>
                    <td style="padding: 10px 12px; font-size: 0.85rem; color: var(--text-color-secondary, #475569);">
                        ${item.meaning}
                    </td>
                </tr>
            `;
        });
        tableBodyEl.innerHTML = html;
    }

    // 3. AI解説描画
    if (commentaryEl) {
        const commText = marketFibData.commentary || 'AIによる市場見通し解説を作成しました。';
        commentaryEl.innerText = commText;
    }
}

function initMarketFibonacciModal() {
    const btnShow = document.getElementById('btn-show-market-fibonacci');
    const modal = document.getElementById('market-fibonacci-modal');
    const btnCloseHeader = document.getElementById('btn-close-market-fib-modal');
    const btnCloseFooter = document.getElementById('btn-close-market-fib-footer');
    const btnRefresh = document.getElementById('btn-refresh-market-fib');

    function openModal() {
        if (!modal) return;
        modal.classList.remove('hidden');
        modal.style.display = 'flex';
        document.body.classList.add('modal-open');
        fetchMarketFibonacciData(false);
    }

    function closeModal() {
        if (!modal) return;
        modal.classList.add('hidden');
        modal.style.display = 'none';
        document.body.classList.remove('modal-open');
    }

    if (btnShow) btnShow.addEventListener('click', openModal);
    if (btnCloseHeader) btnCloseHeader.addEventListener('click', closeModal);
    if (btnCloseFooter) btnCloseFooter.addEventListener('click', closeModal);

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
    }

    if (btnRefresh) {
        btnRefresh.addEventListener('click', () => {
            fetchMarketFibonacciData(true);
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
            closeModal();
        }
    });
}

// グローバル空間へのバインド
window.switchMarketFibTab = switchMarketFibTab;
window.fetchMarketFibonacciData = fetchMarketFibonacciData;
window.initMarketFibonacciModal = initMarketFibonacciModal;

document.addEventListener('DOMContentLoaded', () => {
    initMarketFibonacciModal();
});
