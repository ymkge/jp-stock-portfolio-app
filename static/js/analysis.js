// static/js/analysis.js

document.addEventListener('DOMContentLoaded', () => {
    // --- グローバル変数 (初期化順序のために上部に配置) ---
    let allHoldingsData = [];
    let fullAnalysisData = {};
    let highlightRules = null;
    let filteredHoldingsData = [];
    let currentSort = { key: 'market_value', order: 'desc' };
    let isAmountVisible = true;
    let fetchController = null; // AbortControllerを保持
    let recentCodes = [];

    // --- DOM要素の取得 ---
    const alertContainer = document.getElementById('alert-container');
    const portfolioSummary = document.querySelector('.portfolio-summary');
    const analysisTableBody = document.querySelector('#analysis-table tbody');
    const toggleVisibilityCheckbox = document.getElementById('toggle-visibility');
    const analysisFilterInput = document.getElementById('analysis-filter-input');
    const industryFilterSelect = document.getElementById('industry-filter');
    const accountTypeFilterSelect = document.getElementById('account-type-filter');
    const securityCompanyFilterSelect = document.getElementById('security-company-filter');
    const buySignalFilterSelect = document.getElementById('buy-signal-filter');
    const downloadAnalysisCsvButton = document.getElementById('download-analysis-csv-button');
    const chartToggleBtns = document.querySelectorAll('.chart-toggle-btn');
    const loadingIndicator = document.getElementById('loading-indicator');
    const updateReportContainer = document.getElementById('update-report-container');
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const btnRecentFilter = document.getElementById('btn-recent-filter');

    // --- 新規DOM要素 ---
    const industryKpiTableBody = document.querySelector('#industry-kpi-table tbody');
    const analysisTabBtns = document.querySelectorAll('.analysis-tab-btn');
    const detailsTabContent = document.getElementById('details-tab-content');
    const industryKpiTabContent = document.getElementById('industry-kpi-tab-content');
    const detailsFilterControls = document.getElementById('details-filter-controls');

    // --- Chart.jsインスタンス ---
    let industryChart, accountTypeChart, countryChart, securityCompanyChart, dividendIndustryChart;
    let assetHistoryChart, dividendHistoryChart, monthlyDividendChart, radarChart;

    // --- 業種別KPIソート状態 ---
    let industryKpiSort = { key: 'market_value', order: 'desc' };

    // --- テーマ管理 ---
    function initTheme() {
        const savedTheme = localStorage.getItem('theme');
        if (savedTheme === 'dark') {
            document.documentElement.classList.add('dark-mode');
            if (darkModeToggle) darkModeToggle.checked = true;
        } else {
            document.documentElement.classList.remove('dark-mode');
            if (darkModeToggle) darkModeToggle.checked = false;
        }
        updateAllCharts();
    }

    if (darkModeToggle) {
        darkModeToggle.addEventListener('change', () => {
            if (darkModeToggle.checked) {
                document.documentElement.classList.add('dark-mode');
                localStorage.setItem('theme', 'dark');
            } else {
                document.documentElement.classList.remove('dark-mode');
                localStorage.setItem('theme', 'light');
            }
            updateAllCharts();
        });
    }

    // --- 当日資産変動ランキング モーダル開閉制御 (#261) ---
    const btnOpenDailyRankingModal = document.getElementById('btn-open-daily-ranking-modal');
    const dailyRankingModal = document.getElementById('daily-ranking-modal');
    const btnCloseDailyRankingModal = document.getElementById('btn-close-daily-ranking-modal');
    const btnCloseDailyRankingModalFooter = document.getElementById('btn-close-daily-ranking-modal-footer');

    if (btnOpenDailyRankingModal && dailyRankingModal) {
        btnOpenDailyRankingModal.addEventListener('click', () => {
            dailyRankingModal.classList.remove('hidden');
            dailyRankingModal.style.display = 'flex';
        });

        const closeRankingModal = () => {
            dailyRankingModal.classList.add('hidden');
            dailyRankingModal.style.display = 'none';
        };

        if (btnCloseDailyRankingModal) btnCloseDailyRankingModal.addEventListener('click', closeRankingModal);
        if (btnCloseDailyRankingModalFooter) btnCloseDailyRankingModalFooter.addEventListener('click', closeRankingModal);

        dailyRankingModal.addEventListener('click', (e) => {
            if (e.target === dailyRankingModal) closeRankingModal();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !dailyRankingModal.classList.contains('hidden')) {
                closeRankingModal();
            }
        });
    }

    // --- 利確・銘柄入替検討リスト モーダル開閉制御 (#275) ---
    const btnOpenProfitTakingModal = document.getElementById('btn-open-profit-taking-modal');
    const profitTakingModal = document.getElementById('profit-taking-modal');
    const btnCloseProfitTakingModalFooter = document.getElementById('btn-close-profit-taking-modal-footer');
    const profitTakingAiModal = document.getElementById('profit-taking-ai-modal');
    const btnCloseProfitTakingAiModal = document.getElementById('btn-close-profit-taking-ai-modal');

    if (btnOpenProfitTakingModal && profitTakingModal) {
        btnOpenProfitTakingModal.addEventListener('click', () => {
            profitTakingModal.classList.remove('hidden');
            profitTakingModal.style.display = 'flex';
        });

        const closeProfitTakingModal = () => {
            profitTakingModal.classList.add('hidden');
            profitTakingModal.style.display = 'none';
        };

        if (btnCloseProfitTakingModalFooter) btnCloseProfitTakingModalFooter.addEventListener('click', closeProfitTakingModal);

        profitTakingModal.addEventListener('click', (e) => {
            if (e.target === profitTakingModal) closeProfitTakingModal();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !profitTakingModal.classList.contains('hidden')) {
                closeProfitTakingModal();
            }
        });
    }

    if (profitTakingAiModal) {
        const closeProfitTakingAiModal = () => {
            profitTakingAiModal.classList.add('hidden');
            profitTakingAiModal.style.display = 'none';
        };

        if (btnCloseProfitTakingAiModal) btnCloseProfitTakingAiModal.addEventListener('click', closeProfitTakingAiModal);

        profitTakingAiModal.addEventListener('click', (e) => {
            if (e.target === profitTakingAiModal) closeProfitTakingAiModal();
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !profitTakingAiModal.classList.contains('hidden')) {
                closeProfitTakingAiModal();
            }
        });
    }

    function getChartThemeColors() {
        const style = getComputedStyle(document.documentElement);
        return {
            text: style.getPropertyValue('--text-color').trim() || '#343a40',
            grid: style.getPropertyValue('--chart-grid-color').trim() || 'rgba(0, 0, 0, 0.1)',
            muted: style.getPropertyValue('--text-muted').trim() || '#6c757d'
        };
    }

    function updateAllCharts() {
        // データがある場合のみ再描画
        if (filteredHoldingsData && filteredHoldingsData.length > 0) {
            renderCharts(filteredHoldingsData);
            renderRadarChart(calculateWeightedStats(filteredHoldingsData));
            fetchAndRenderHistoryData();
        }
    }

    initTheme();

    // --- タブ切り替え制御 ---
    if (analysisTabBtns) {
        analysisTabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                analysisTabBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                if (tab === 'details') {
                    if (detailsTabContent) detailsTabContent.classList.remove('hidden');
                    if (industryKpiTabContent) industryKpiTabContent.classList.add('hidden');
                    if (detailsFilterControls) detailsFilterControls.classList.remove('hidden');
                } else {
                    if (detailsTabContent) detailsTabContent.classList.add('hidden');
                    if (industryKpiTabContent) industryKpiTabContent.classList.remove('hidden');
                    if (detailsFilterControls) detailsFilterControls.classList.add('hidden');
                    renderIndustryKpiTable(fullAnalysisData.industry_summary);
                }
            });
        });
    }

    // --- スケルトンUI表示 ---
    function showSkeletons() {
        // 1. 左カラムのカード群
        const cardSkeletons = {
            'summary-content': `<div class="skeleton skeleton-text" style="width: 80%;"></div><div class="skeleton skeleton-text" style="width: 70%;"></div><div class="skeleton skeleton-text" style="width: 90%;"></div><div class="skeleton skeleton-text" style="width: 60%;"></div>`,
            'dna-content': `<div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text"></div>`,
            'risk-content': `<div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text"></div>`,
            'personality-content': `<div class="skeleton skeleton-text" style="height: 3rem; width: 100%;"></div><div class="skeleton skeleton-text"></div><div class="skeleton skeleton-text"></div>`
        };

        Object.entries(cardSkeletons).forEach(([id, html]) => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = html;
        });

        // 3. チャートエリア (円形と矩形)
        const chartContainers = document.querySelectorAll('.chart-container');
        chartContainers.forEach(container => {
            const canvas = container.querySelector('canvas');
            if (canvas) canvas.classList.add('hidden');
            const existing = container.querySelector('.skeleton-overlay');
            if (existing) existing.remove();
            const isPie = container.parentElement.classList.contains('portfolio-chart');
            const skeletonHtml = isPie 
                ? `<div class="skeleton-overlay" style="display:flex; justify-content:center; align-items:center; height:100%;"><div class="skeleton skeleton-circle" style="width:200px; height:200px;"></div></div>`
                : `<div class="skeleton-overlay" style="height:100%;"><div class="skeleton skeleton-rect"></div></div>`;
            container.insertAdjacentHTML('beforeend', skeletonHtml);
        });

        renderTableSkeletons();
    }

    function hideSkeletons() {
        const overlays = document.querySelectorAll('.skeleton-overlay');
        overlays.forEach(o => o.remove());
        const hiddenCanvases = document.querySelectorAll('canvas.hidden');
        hiddenCanvases.forEach(c => c.classList.remove('hidden'));
    }

    function renderTableSkeletons() {
        analysisTableBody.innerHTML = Array(5).fill(0).map(() => `
            <tr class="skeleton-row">
                ${Array(16).fill(0).map(() => `<td><div class="skeleton skeleton-cell"></div></td>`).join('')}
            </tr>
        `).join('');

        if (industryKpiTableBody) {
            industryKpiTableBody.innerHTML = Array(5).fill(0).map(() => `
                <tr class="skeleton-row">
                    ${Array(8).fill(0).map(() => `<td><div class="skeleton skeleton-cell"></div></td>`).join('')}
                </tr>
            `).join('');
        }
    }

    // --- データ取得とレンダリング ---
    async function fetchHighlightRules() {
        try {
            const response = await fetch('/api/highlight-rules');
            if (!response.ok) throw new Error('Failed to fetch rules');
            highlightRules = await response.json();
            if (allHoldingsData && allHoldingsData.length > 0) {
                filterAndRender();
            }
        } catch (error) {
            console.error('Error fetching highlight rules:', error);
        }
    }

    async function fetchAndRenderAnalysisData() {
        if (fetchController) {
            fetchController.abort();
        }
        fetchController = new AbortController();
        const signal = fetchController.signal;

        const cachedData = window.appState.getState('analysis');
        if (cachedData) {
            processAnalysisData(cachedData);
            const cachedMetadata = cachedData.metadata || (cachedData.data && cachedData.data.metadata);
            if (cachedMetadata) {
                renderUpdateReport(cachedMetadata);
            }
            fetchAndRenderHistoryData();
        } else {
            showSkeletons();
        }

        try {
            const currentMetadata = cachedData ? (cachedData.metadata || (cachedData.data && cachedData.data.metadata)) : null;
            let loadingMsg = cachedData ? '最新データを取得中...' : 'データを取得中...';
            if (currentMetadata) {
                loadingMsg += `<br><small class="loading-sub-text">対象: ${currentMetadata.total_count}件の銘柄情報を更新しています</small>`;
            }
            loadingIndicator.innerHTML = loadingMsg;
            loadingIndicator.classList.remove('hidden');

            const response = await fetch('/api/portfolio/analysis', { signal });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new window.appState.HttpError(errorData.detail || `HTTP error! status: ${response.status}`, response.status);
            }

            const analysisData = await response.json();
            window.appState.updateState('analysis', analysisData);
            window.appState.updateTimestamp();
            
            hideSkeletons();
            processAnalysisData(analysisData);
            if (analysisData.metadata) {
                renderUpdateReport(analysisData.metadata);
            }
            loadingIndicator.classList.add('hidden');
            fetchAndRenderHistoryData();

        } catch (error) {
            if (error.name === 'AbortError') return;
            console.error('Analysis fetch error:', error);
            if (error instanceof window.appState.HttpError && error.status === 429) {
                console.log('Backend is currently throttling or updating. Using cached data.');
            } else if (!cachedData) {
                showAlert(`分析データの取得に失敗しました。(${error.message})`, 'danger');
                analysisTableBody.innerHTML = `<tr><td colspan="16" style="text-align:center; color: var(--danger-color);">データの取得に失敗しました。再読み込みしてください。</td></tr>`;
            }
            loadingIndicator.classList.add('hidden');
            hideSkeletons();
        }
    }

    let isSyncing = false;

    function renderUpdateReport(metadata) {
        if (!updateReportContainer || !metadata) return;
        if (isSyncing) {
            updateReportContainer.classList.add('hidden');
            return;
        }
        const timeStr = new Date(metadata.fetched_at).toLocaleString();
        const successClass = metadata.fail_count > 0 ? 'loss' : 'profit';
        
        let throttlingHint = '';
        if (metadata.circuit_breaker_triggered) {
            throttlingHint = `
                <div class="throttling-hint mt-2 p-2 border border-danger rounded bg-danger-subtle text-danger" style="font-size: 0.85rem;">
                    <i class="fas fa-exclamation-triangle me-1"></i>
                    <strong>アクセス制限(403)を検知しました。</strong><br>
                    連続アクセスによるサーバー負荷を避けるため、更新を中断しました。15分ほど待機してから再度お試しください。
                </div>
            `;
        }

        updateReportContainer.innerHTML = `
            <div class="update-report">
                <div class="update-report-stats">
                    <span>対象: <strong>${metadata.total_count}</strong>件</span>
                    <span>成功: <strong class="profit">${metadata.success_count}</strong></span>
                    <span>失敗: <strong class="${successClass}">${metadata.fail_count}</strong></span>
                    <small class="update-report-time">(内訳: 国内株${metadata.jp_count}, 投信${metadata.it_count}, 米国株${metadata.us_count})</small>
                </div>
                <div class="update-report-time">
                    取得時間: ${metadata.duration}s | 更新時刻: ${timeStr}
                </div>
                ${throttlingHint}
            </div>
        `;
        updateReportContainer.classList.remove('hidden');
    }

    async function fetchAndRenderHistoryData() {
        try {
            const response = await fetch('/api/history/summary');
            if (!response.ok) throw new Error('履歴データの取得に失敗しました');
            const historyData = await response.json();
            renderHistoryCharts(historyData);
        } catch (error) {
            console.error('History fetch error:', error);
        }
    }

    function renderHistoryCharts(historyData) {
        if (!historyData || historyData.length === 0) return;
        const colors = getChartThemeColors();
        const labels = historyData.map(d => d.snapshot_month);
        const marketValues = historyData.map(d => d.total_market_value);
        const profitLosses = historyData.map(d => d.total_profit_loss);
        const originalInvestments = marketValues.map((mv, i) => mv - profitLosses[i]);
        const dividends = historyData.map(d => d.total_dividend);
        const commonOptions = {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: colors.text } },
                tooltip: {
                    mode: 'index', intersect: false,
                    callbacks: { label: function(context) {
                        let label = context.dataset.label || ''; if (label) label += ': ';
                        const formattedValue = isAmountVisible ? formatNumber(context.raw, 0) + '円' : '***円';
                        return label + formattedValue;
                    }}
                }
            },
            scales: {
                x: { grid: { color: colors.grid }, ticks: { color: colors.muted } },
                y: { beginAtZero: true, grid: { color: colors.grid }, ticks: { color: colors.muted, callback: function(v) { return isAmountVisible ? formatNumber(v, 0) + '円' : '***円'; } } }
            }
        };
        const assetCanvas = document.getElementById('asset-history-chart');
        if (assetCanvas) {
            const existingChart = Chart.getChart(assetCanvas); if (existingChart) existingChart.destroy();
            new Chart(assetCanvas.getContext('2d'), {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{ label: '総資産額', data: marketValues, borderColor: '#4e73df', backgroundColor: 'rgba(78, 115, 223, 0.1)', fill: true, tension: 0.3 },
                               { label: '投資元本', data: originalInvestments, borderColor: '#858796', borderDash: [5, 5], fill: false, tension: 0 }]
                },
                options: commonOptions
            });
        }
        const divCanvas = document.getElementById('dividend-history-chart');
        if (divCanvas) {
            const existingChart = Chart.getChart(divCanvas); if (existingChart) existingChart.destroy();
            const divOptions = JSON.parse(JSON.stringify(commonOptions));
            divOptions.plugins = divOptions.plugins || {};
            divOptions.plugins.tooltip = divOptions.plugins.tooltip || {};
            divOptions.plugins.tooltip.callbacks = {
                label: (c) => `${c.dataset.label}: ${isAmountVisible ? formatNumber(c.raw, 0) + '円' : '***円'}`,
                afterLabel: (c) => {
                    const idx = c.dataIndex;
                    const dataArr = c.dataset.data;
                    const val = c.raw || 0;
                    if (idx === 0) {
                        return isAmountVisible ? '前月比: -' : '前月比: ***円';
                    }
                    const prevVal = dataArr[idx - 1] || 0;
                    const diff = val - prevVal;
                    
                    if (!isAmountVisible) {
                        return '前月比: ***円';
                    }
                    
                    if (diff > 0) {
                        if (prevVal > 0) {
                            const pct = ((diff / prevVal) * 100).toFixed(1);
                            return `前月比: +${formatNumber(diff, 0)}円 (+${pct}%)`;
                        } else {
                            return `前月比: +${formatNumber(diff, 0)}円 (新規計測)`;
                        }
                    } else if (diff < 0) {
                        if (prevVal > 0) {
                            const pct = ((diff / prevVal) * 100).toFixed(1);
                            return `前月比: ${formatNumber(diff, 0)}円 (${pct}%)`;
                        } else {
                            return `前月比: ${formatNumber(diff, 0)}円`;
                        }
                    } else {
                        return `前月比: ±0円`;
                    }
                }
            };

            new Chart(divCanvas.getContext('2d'), {
                type: 'bar',
                data: { labels: labels, datasets: [{ label: '年間配当予定額', data: dividends, backgroundColor: '#1cc88a', borderRadius: 4 }] },
                options: divOptions
            });
        }
    }

    function processAnalysisData(analysisData) {
        if (!analysisData) return;
        const actualData = analysisData.holdings_list ? analysisData : (analysisData.data || {});
        fullAnalysisData = actualData;
        allHoldingsData = actualData.holdings_list || [];
        isAmountVisible = !toggleVisibilityCheckbox.checked;
        populateFilters();
        filterAndRender();
        renderProfitTakingSection(fullAnalysisData.profit_taking_candidates || [], isAmountVisible);
    }

    function filterAndRender() {
        const filterText = analysisFilterInput.value.toLowerCase().trim();
        const selectedIndustry = industryFilterSelect.value;
        const selectedAccountType = accountTypeFilterSelect.value;
        const selectedSecurityCompany = securityCompanyFilterSelect.value;
        const selectedBuySignal = buySignalFilterSelect.value;

        // 最近の銘柄ボタンのアクティブ状態の同期
        if (btnRecentFilter) {
            const queryText = analysisFilterInput.value.trim();
            if (recentCodes.length > 0 && queryText === recentCodes.join(' ')) {
                btnRecentFilter.classList.add('active');
            } else {
                btnRecentFilter.classList.remove('active');
            }
        }

        filteredHoldingsData = allHoldingsData.filter(item => {
            let matchesText = true;
            if (filterText) {
                const keywords = filterText.split(/[\s,，]+/).filter(k => k !== "");
                if (keywords.length > 0) {
                    matchesText = keywords.some(keyword =>
                        String(item.code).toLowerCase().includes(keyword) ||
                        String(item.name || '').toLowerCase().includes(keyword)
                    );
                }
            }
            const matchesIndustry = !selectedIndustry || item.industry === selectedIndustry || (selectedIndustry === 'N/A' && !item.industry);
            const matchesAccountType = !selectedAccountType || item.account_type === selectedAccountType;
            const matchesSecurityCompany = !selectedSecurityCompany || (item.security_company || '-') === selectedSecurityCompany;
            const isDiamond = item.is_diamond === true || (item.buy_signal && item.buy_signal.is_diamond === true);
            const ma75 = item.moving_average_75 || item.ma75;
            const isLongTermDiscount = item.is_long_term_discount === true ||
                                       (item.raw_sell_signal && item.raw_sell_signal.level === 3) ||
                                       (item.sell_signal && item.sell_signal.level === 3) ||
                                       (item.price > 0 && ma75 && item.price < ma75);
            const isFallingKnife = (item.sell_signal && item.sell_signal.level === 4) ||
                                  (item.raw_sell_signal && item.raw_sell_signal.level === 4);
            const matchesBuySignal = !selectedBuySignal || (
                (selectedBuySignal === 'strict-dip' && isDiamond && item.buy_signal && item.buy_signal.level >= 1) ||
                (selectedBuySignal === 'strict-low' && isDiamond && isLongTermDiscount && !isFallingKnife) ||
                (selectedBuySignal === 'overheated' && (
                    (item.sell_signal && (item.sell_signal.level === 1 || item.sell_signal.level === 2 || item.sell_signal.level === 4)) ||
                    (item.sell_signal && item.sell_signal.level === 3 && !isDiamond)
                ))
            );
            return matchesText && matchesIndustry && matchesAccountType && matchesSecurityCompany && matchesBuySignal;
        });
        sortHoldings(filteredHoldingsData);
        renderAnalysisTable(filteredHoldingsData);
        renderSummary(filteredHoldingsData);
        renderCharts(filteredHoldingsData);
        if (fullAnalysisData && fullAnalysisData.profit_taking_candidates) {
            renderProfitTakingSection(fullAnalysisData.profit_taking_candidates, isAmountVisible);
        }
        if (fullAnalysisData && (fullAnalysisData.daily_change_rankings || fullAnalysisData.monthly_change_rankings)) {
            renderRankingModalContent();
        }
        updateSortHeaders();
    }

    function renderAnalysisTable(holdings) {
        if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) { renderTableSkeletons(); return; }
        analysisTableBody.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            analysisTableBody.innerHTML = `<tr><td colspan="18" style="text-align:center;">該当する保有銘柄はありません。</td></tr>`;
            return;
        }
        holdings.forEach(item => {
            const row = analysisTableBody.insertRow();
            const createCell = (html, className = '') => { 
                const cell = row.insertCell(); cell.innerHTML = html; 
                if (html === 'N/A' || html === '--' || html === '-') cell.className = (className ? className + ' ' : '') + 'na-value';
                else if (className) cell.className = className; 
                return cell; 
            };
            const createCellWithTooltip = (html, className = '', tooltipText = '') => { 
                const cell = createCell(html, className); 
                if (tooltipText) cell.title = tooltipText; 
                return cell; 
            };

            if (item.error) {
                const displayError = item.error_message || item.error;
                row.className = 'error-row';
                row.title = displayError.replace(/<br>/g, '\n').replace(/<[^>]*>?/gm, '');
                createCell(item.code, 'numeric');
                createCell(displayError, 'error-message').colSpan = 17;
                return;
            }

            const profitLoss = parseFloat(item.profit_loss);
            const profitLossRate = parseFloat(item.profit_loss_rate);
            const profitLossClass = isNaN(profitLoss) ? '' : (profitLoss >= 0 ? 'profit' : 'loss');
            const profitLossRateClass = isNaN(profitLossRate) ? '' : (profitLossRate >= 0 ? 'profit' : 'loss');
            let codeHtml = item.code;
            if (item.split_alert) {
                codeHtml += ` <span class="split-badge confirmed" data-code="${item.code}" title="株式分割が検知されました。調整が必要です（メインページで適用してください）。">✂️</span>`;
            } else if (item.potential_split) {
                codeHtml += ` <span class="split-badge potential" title="最新価格が直近終値と大きく乖離しています（比率: ${item.potential_split_ratio}）。株式分割が発生した可能性があります。手動で履歴同期を実行してください。">⚠️</span>`;
            }
            createCell(codeHtml, 'numeric');
            let nameHtml = `<span class="fw-bold me-1">${item.name}</span>`;
            const isDiamond = item.is_diamond || (item.buy_signal && item.buy_signal.is_diamond);
            if (item.buy_signal) nameHtml += renderBuySignalBadge(item.buy_signal, isDiamond);
            if (item.sell_signal) nameHtml += renderSellSignalBadge(item.sell_signal, isDiamond);
            if (item.exhaustion_signal) nameHtml += renderExhaustionSignalBadge(item.exhaustion_signal);
            if (item.profit_taking_badge || item.profit_taking_signal) nameHtml += renderProfitTakingBadge(item);
            createCell(nameHtml);
            createCell(item.industry || 'N/A');
            createCell(item.asset_type === 'jp_stock' ? '国内株式' : (item.asset_type === 'investment_trust' ? '投資信託' : (item.asset_type === 'us_stock' ? '米国株式' : 'N/A')));
            createCell(item.security_company || '-');
            createCell(item.account_type);
            createCell(formatNumber(item.quantity, item.asset_type === 'investment_trust' ? 6 : 0), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            createCell(formatNumber(item.purchase_price, 2), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            createCell(formatNumber(item.price, 2), 'numeric');
            createCell(formatNumber(item.estimated_annual_dividend, 0), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            createCell(formatNumber(item.estimated_annual_dividend_after_tax, 0), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            
            // 配当性向のセル描画 (ツールチップで過去の履歴を表示)
            if (item.payout_ratio !== undefined && item.payout_ratio !== null && item.payout_ratio !== 'N/A') {
                const payoutVal = `${parseFloat(item.payout_ratio).toFixed(1)}%`;
                const payoutClass = 'numeric ' + getHighlightClass('payout_ratio', item.payout_ratio, item.asset_type);
                const payoutHistoryTooltip = formatPayoutRatioHistory(item.payout_ratio_history);
                if (payoutHistoryTooltip) {
                    createCellWithTooltip(payoutVal, payoutClass, payoutHistoryTooltip);
                } else {
                    createCell(payoutVal, payoutClass);
                }
            } else {
                createCell('-', 'numeric na-value');
            }

            // DOEのセル描画 (日本株のみ)
            if (item.asset_type === 'jp_stock' && item.doe !== undefined && item.doe !== null && item.doe !== 'N/A') {
                const doeVal = `${parseFloat(item.doe).toFixed(2)}%`;
                const doeClass = 'numeric ' + getHighlightClass('doe', item.doe, item.asset_type);
                const bpsVal = item.bps && item.bps !== 'N/A' ? parseFloat(item.bps).toLocaleString() : 'N/A';
                createCellWithTooltip(doeVal, doeClass, `BPS（実績）: ${bpsVal}円\n算出式: 予想配当金 / BPS`);
            } else {
                createCell('-', 'numeric na-value');
            }
            
            createCell(formatNumber(item.dividend_contribution, 2), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            createCell(formatNumber(item.market_value, 0), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            createCell(formatNumber(item.profit_loss, 0), `numeric ${!isAmountVisible ? 'masked-amount' : ''} ${profitLossClass}`);
            createCell(formatNumber(item.profit_loss_rate, 2), `numeric ${!isAmountVisible ? 'masked-amount' : ''} ${profitLossRateClass}`);
            createCell(item.memo || '-');
        });
    }

    function renderIndustryKpiTable(summary) {
        if (!summary || !industryKpiTableBody) return;
        
        // ソート適用
        const sortedSummary = [...summary].sort((a, b) => {
            let valA = a[industryKpiSort.key];
            let valB = b[industryKpiSort.key];
            
            if (typeof valA === 'string') {
                return industryKpiSort.order === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
            }
            return industryKpiSort.order === 'asc' ? valA - valB : valB - valA;
        });

        industryKpiTableBody.innerHTML = '';
        sortedSummary.forEach(item => {
            const row = industryKpiTableBody.insertRow();
            row.style.cursor = 'pointer';
            row.title = `${item.name}の詳細を表示`;
            row.addEventListener('click', () => {
                const detailsTab = document.querySelector('.analysis-tab-btn[data-tab="details"]');
                if (detailsTab) detailsTab.click();
                if (industryFilterSelect) {
                    const searchInput = document.getElementById('analysis-industry-search');
                    if (searchInput) {
                        searchInput.value = '';
                    }
                    populateIndustryFilter('');
                    industryFilterSelect.value = item.name;
                    industryFilterSelect.dispatchEvent(new Event('change'));
                }
            });

            const createCell = (html, className = '') => { const cell = row.insertCell(); cell.innerHTML = html; if (className) cell.className = className; return cell; };
            const plClass = item.profit_loss >= 0 ? 'profit' : 'loss';
            const plRateClass = item.profit_loss_rate >= 0 ? 'profit' : 'loss';

            createCell(item.name, 'fw-bold');
            createCell(item.stock_count, 'numeric');
            createCell(formatNumber(item.market_value, 0), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            createCell(formatNumber(item.market_value_ratio, 2) + '%', 'numeric');
            createCell(formatNumber(item.profit_loss, 0), 'numeric ' + (!isAmountVisible ? 'masked-amount' : '') + ' ' + plClass);
            createCell(formatNumber(item.profit_loss_rate, 2) + '%', 'numeric ' + plRateClass);
            createCell(formatNumber(item.annual_dividend_after_tax, 0), 'numeric ' + (!isAmountVisible ? 'masked-amount' : ''));
            createCell(formatNumber(item.yield_after_tax, 2) + '%', 'numeric');
        });
        
        updateIndustryKpiSortHeaders();
    }

    function updateIndustryKpiSortHeaders() {
        const headers = document.querySelectorAll('#industry-kpi-table .sortable');
        headers.forEach(th => {
            th.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (th.dataset.key === industryKpiSort.key) {
                th.classList.add('sort-active', `sort-${industryKpiSort.order}`);
            }
        });
    }

    // KPIテーブルのソートイベントリスナー
    document.querySelectorAll('#industry-kpi-table th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const key = th.dataset.key;
            if (industryKpiSort.key === key) {
                industryKpiSort.order = industryKpiSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                industryKpiSort.key = key;
                industryKpiSort.order = 'desc';
            }
            renderIndustryKpiTable(fullAnalysisData.industry_summary);
        });
    });

    function renderSummary(holdings) {
        const totalMarketValue = holdings.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        const totalProfitLoss = holdings.reduce((sum, item) => sum + (parseFloat(item.profit_loss) || 0), 0);
        const totalInvestment = totalMarketValue - totalProfitLoss;
        const totalProfitLossRate = totalInvestment !== 0 ? (totalProfitLoss / totalInvestment) * 100 : 0;
        const totalEstimatedAnnualDividend = holdings.reduce((sum, item) => sum + (parseFloat(item.estimated_annual_dividend) || 0), 0);
        const totalEstimatedAnnualDividendAfterTax = holdings.reduce((sum, item) => sum + (parseFloat(item.estimated_annual_dividend_after_tax) || 0), 0);
        const dividendPayingHoldings = holdings.filter(item => (parseFloat(item.estimated_annual_dividend) || 0) > 0);
        const mvOfDividendPaying = dividendPayingHoldings.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        const costOfDividendPaying = dividendPayingHoldings.reduce((sum, item) => { const mv = parseFloat(item.market_value) || 0; const pl = parseFloat(item.profit_loss) || 0; return sum + (mv - pl); }, 0);
        const yieldOnCurrent = mvOfDividendPaying > 0 ? (totalEstimatedAnnualDividend / mvOfDividendPaying * 100) : 0;
        const yieldOnCost = costOfDividendPaying > 0 ? (totalEstimatedAnnualDividend / costOfDividendPaying * 100) : 0;
        const summaryProfitLossClass = totalProfitLoss >= 0 ? 'profit' : 'loss';
        const summaryProfitLossRateClass = totalProfitLossRate >= 0 ? 'profit' : 'loss';
        const currentTotalMV = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        const currentTotalPL = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.profit_loss) || 0), 0);
        const currentTotalDiv = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.estimated_annual_dividend) || 0), 0);
        const prev = fullAnalysisData.previous_summary;
        const prevDate = prev ? prev.snapshot_date : null;
        const calcDiff = (current, previous) => (!previous || previous === 0) ? null : ((current - previous) / previous) * 100;
        
        const formatDiff = (diff, date) => { 
            if (diff === null) return ''; 
            const cls = diff >= 0 ? 'profit' : 'loss'; 
            const sign = diff >= 0 ? '+' : ''; 
            const dateStr = date ? `${date} との比較` : '過去データとの比較';
            return `<small class="${cls} numeric" style="margin-left: 8px; font-weight: bold;" title="${dateStr}です">(${sign}${diff.toFixed(2)}%)</small>`; 
        };

        const isFiltered = holdings.length !== allHoldingsData.length;
        const momSuffixMV = !isFiltered ? formatDiff(calcDiff(currentTotalMV, prev ? prev.total_market_value : 0), prevDate) : '';
        const momSuffixPL = !isFiltered ? formatDiff(calcDiff(currentTotalPL, prev ? prev.total_profit_loss : 0), prevDate) : '';
        const momSuffixDiv = !isFiltered ? formatDiff(calcDiff(currentTotalDiv, prev ? prev.total_dividend : 0), prevDate) : '';
        
        const summaryContent = document.getElementById('summary-content');
        const compareDateLabel = document.getElementById('compare-date-label');
        
        if (summaryContent) {
            if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) return;
            
            // 比較対象日の表示 (ヘッダー横のラベルへ)
            if (compareDateLabel) {
                compareDateLabel.textContent = (prevDate && !isFiltered) ? `(比較対象: ${prevDate})` : '';
            }
            
            summaryContent.innerHTML = `
                <p>総評価額: <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalMarketValue, 0)}円</span>${momSuffixMV}</p>
                <p>総損益: <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossClass}">${formatNumber(totalProfitLoss, 0)}円</span>${momSuffixPL}</p>
                <p>総損益率: <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossRateClass}">${formatNumber(totalProfitLossRate, 2)}%</span></p>
                <p>年間配当合計: <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividend, 0)}円</span>${momSuffixDiv}</p>
                <p>年間配当合計(税引後): <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividendAfterTax, 0)}円</span></p>
                <hr>
                <p title="配当が発生する資産の評価額合計です">配当対象資産の評価額: <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(mvOfDividendPaying, 0)}円</span></p>
                <p title="配当が出る銘柄のみを対象とした利回りです">配当利回り(現在値): <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(yieldOnCurrent, 2)}%</span></p>
                <p title="配当が出る銘柄のみを対象とした、投資額に対する利回りです">配当利回り(取得値): <span class="numeric ${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(yieldOnCost, 2)}%</span></p>
            `;
        }
        const stats = calculateWeightedStats(holdings); renderDNAAndRisk(stats); renderRadarChart(stats);
    }

    function renderRadarChart(stats) {
        if (!stats || !highlightRules || !highlightRules.radar_chart) return;
        const canvas = document.getElementById('radar-chart'); if (!canvas) return;
        const existingChart = Chart.getChart(canvas); if (existingChart) existingChart.destroy();
        const colors = getChartThemeColors();
        const normalize = (val, min, max, reverse = false) => { if (val === null || val === undefined) return 0; let score = ((val - min) / (max - min)) * 100; if (reverse) score = 100 - score; return Math.min(Math.max(score, 0), 100); };
        const safeGet = (obj, path, def = 0) => path.split('.').reduce((acc, part) => acc && acc[part], obj) || def;
        const scores = [(normalize(stats.weighted_per, 10, 40, true) + normalize(stats.weighted_pbr, 0.7, 2.5, true)) / 2, normalize(stats.weighted_roe, 0, 20), normalize(stats.weighted_yield, 0, 5), normalize(stats.weighted_years, 0, 10), normalize(stats.weighted_momentum, 0, 5), (normalize(stats.top5_ratio, 20, 60, true) + normalize(stats.hhi, 1000, 3000, true)) / 2, Math.min(100, (safeGet(stats, 'style_breakdown.safetyScore', 0) * (stats.hhi > 2500 ? 0.9 : 1.0)))];
        const bm = highlightRules.radar_chart.benchmarks;
        const benchmarkScores = [(normalize(bm.valuation_per, 10, 40, true) + normalize(bm.valuation_pbr, 0.7, 2.5, true)) / 2, normalize(bm.profitability_roe, 0, 20), normalize(bm.income_yield, 0, 5), normalize(bm.quality_years, 0, 10), normalize(bm.momentum_score, 0, 5), (normalize(bm.diversification_top5, 20, 60, true) + normalize(bm.diversification_hhi, 1000, 3000, true)) / 2, bm.safety_score || 50];
        radarChart = new Chart(canvas.getContext('2d'), {
            type: 'radar',
            data: { labels: highlightRules.radar_chart.labels, datasets: [{ label: 'マイ・ポートフォリオ', data: scores, backgroundColor: 'rgba(78, 115, 223, 0.2)', borderColor: '#4e73df', pointBackgroundColor: '#4e73df', pointBorderColor: '#fff', pointHoverBackgroundColor: '#fff', pointHoverBorderColor: '#4e73df', borderWidth: 3 }, { label: 'ベンチマーク (市場平均)', data: benchmarkScores, backgroundColor: 'transparent', borderColor: '#858796', borderDash: [5, 5], pointRadius: 0, borderWidth: 1 }] },
            options: { responsive: true, maintainAspectRatio: false, scales: { r: { min: 0, max: 100, beginAtZero: true, ticks: { stepSize: 20, display: false }, grid: { color: colors.grid }, angleLines: { color: colors.grid }, pointLabels: { color: colors.text, font: { size: 12, weight: 'bold' } } } }, plugins: { legend: { position: 'bottom', labels: { color: colors.text } }, tooltip: { callbacks: { label: (context) => `${context.dataset.label}: ${Math.round(context.raw)}点`, footer: (context) => { const item = context[0]; const desc = (highlightRules?.radar_chart?.descriptions || {})[item.label] || ""; return desc.length > 30 ? "\n" + desc.match(/.{1,30}/g).join("\n") : (desc ? "\n" + desc : ""); } } } } }
        });
    }

    function calculateWeightedStats(holdings) {
        const totalMarketValue = holdings.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        if (totalMarketValue === 0) return null;

        // 国内株式のみを抽出
        const jpHoldings = holdings.filter(item => item.asset_type === 'jp_stock');
        const totalJpMarketValue = jpHoldings.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);

        const metrics = ['per', 'pbr', 'roe', 'yield', 'consecutive_increase_years', 'momentum'];
        const weightedSums = { per: 0, pbr: 0, roe: 0, yield: 0, consecutive_increase_years: 0, momentum: 0 };
        const weightsTotal = { per: 0, pbr: 0, roe: 0, yield: 0, consecutive_increase_years: 0, momentum: 0 };
        const contributorData = { per: [], pbr: [], roe: [], yield: [], consecutive_increase_years: [], momentum: [] };

        // DNA指標の計算は国内株式のみを対象とする
        jpHoldings.forEach(item => {
            const mv = parseFloat(item.market_value) || 0;
            metrics.forEach(m => {
                let val = item[m];
                if (m === 'momentum' && item.score_details) {
                    const d = item.score_details;
                    val = (d.trend_short || 0) + (d.trend_medium || 0) + (d.trend_long || 0) + (d.trend_signal || 0);
                }
                if (typeof val === 'string') val = parseFloat(val.replace(/,/g, '').replace(/%|倍/g, '').trim());
                if (typeof val === 'number' && !isNaN(val) && isFinite(val) && mv > 0) {
                    weightedSums[m] += val * mv;
                    weightsTotal[m] += mv;
                    contributorData[m].push({ code: item.code, name: item.name, impact: val * mv, val: val });
                }
            });
        });

        // 寄与度トップ3の抽出
        const contributors = {};
        metrics.forEach(m => {
            contributors[m] = contributorData[m]
                .sort((a, b) => Math.abs(b.impact) - Math.abs(a.impact))
                .slice(0, 3);
        });

        // 分散度（HHI, Top5）の計算はポートフォリオ全体（全holdings）を対象とする
        const assetInfo = {};
        holdings.forEach(item => {
            const mv = parseFloat(item.market_value) || 0;
            if (mv > 0 && item.code) {
                if (!assetInfo[item.code]) assetInfo[item.code] = { name: item.name, mv: 0 };
                assetInfo[item.code].mv += mv;
            }
        });
        const sortedAssets = Object.values(assetInfo).sort((a, b) => b.mv - a.mv);
        let hhi = 0; sortedAssets.forEach(a => { const pct = (a.mv / totalMarketValue) * 100; hhi += pct * pct; });
        const top5 = (sortedAssets.slice(0, 5).reduce((s, v) => s + v.mv, 0) / totalMarketValue) * 100;
        const top_assets = sortedAssets.slice(0, 5).map(a => ({ name: a.name, ratio: (a.mv / totalMarketValue) * 100 }));

        // カバー率は「国内株式の中でのカバー率」とする
        const coverages = {};
        metrics.forEach(m => {
            coverages[m] = totalJpMarketValue > 0 ? (weightsTotal[m] / totalJpMarketValue) * 100 : 0;
        });

        return {
            weighted_per: weightsTotal.per > 0 ? weightedSums.per / weightsTotal.per : null,
            weighted_pbr: weightsTotal.pbr > 0 ? weightedSums.pbr / weightsTotal.pbr : null,
            weighted_roe: weightsTotal.roe > 0 ? weightedSums.roe / weightsTotal.roe : null,
            weighted_yield: weightsTotal.yield > 0 ? weightedSums.yield / weightsTotal.yield : null,
            weighted_years: weightsTotal.consecutive_increase_years > 0 ? weightedSums.consecutive_increase_years / weightsTotal.consecutive_increase_years : null,
            weighted_momentum: weightsTotal.momentum > 0 ? weightedSums.momentum / weightsTotal.momentum : null,
            contributors,
            coverages,
            hhi,
            top5_ratio: top5,
            top_assets,
            total_jp_market_value: totalJpMarketValue, // 国内株の合計評価額を返却
            // スタイル診断も国内株式のみを対象とする
            style_breakdown: calculateStyleBreakdown(jpHoldings, totalJpMarketValue)
        };
    }

    function calculateStyleBreakdown(holdings, totalMv) {
        if (totalMv <= 0) return null;
        const defInd = ["食料品", "医薬品", "電気・ガス業", "陸運業", "情報・通信業"], cycInd = ["輸送用機器", "鉄鋼", "海運業", "卸売業", "鉱業", "機械", "化学", "非鉄金属", "ガラス・土石製品"];
        const breakdown = { cyclicality: { defensive: 0, cyclical: 0, other: 0 }, style: { value: 0, growth: 0, blend: 0 }, marketCap: { large: 0, midSmall: 0 } };
        let safetyScore = 0;
        holdings.forEach(item => {
            const mv = parseFloat(item.market_value) || 0; if (mv <= 0) return;
            const ind = item.industry || "その他"; if (defInd.includes(ind)) breakdown.cyclicality.defensive += mv; else if (cycInd.includes(ind)) breakdown.cyclicality.cyclical += mv; else breakdown.cyclicality.other += mv;
            const parseVal = (v) => typeof v === 'string' ? parseFloat(v.replace(/,/g, '').replace(/%|倍/g, '').trim()) : (typeof v === 'number' && !isNaN(v) ? v : null);
            const per = parseVal(item.per), pbr = parseVal(item.pbr), roe = parseVal(item.roe);
            if (per !== null && pbr !== null) { if (per < 15 && pbr < 1) breakdown.style.value += mv; else if (per > 25 || pbr > 2.5) breakdown.style.growth += mv; else breakdown.style.blend += mv; } else breakdown.style.blend += mv;
            let mcap = 0; const mcapV = item.market_cap; if (typeof mcapV === 'string') { const s = mcapV.replace(/,/g, ''); if (s.includes('兆')) mcap = parseFloat(s) * 1e12; else if (s.includes('億')) mcap = parseFloat(s) * 1e8; else mcap = parseFloat(s); } else if (typeof mcapV === 'number') mcap = mcapV;
            if (mcap >= 1e12) breakdown.marketCap.large += mv; else breakdown.marketCap.midSmall += mv;
            let assetS = 0; if (item.asset_type === 'investment_trust') assetS = 100; else if (item.asset_type === 'us_stock') assetS = 10; else { let p = 0; if (defInd.includes(ind)) p += 25; if (mcap >= 1e12) p += 25; else if (mcap >= 3e11) p += 12.5; if (parseInt(item.consecutive_increase_years || 0) >= 3) p += 25; if (pbr !== null && pbr <= 1.2) p += 25; if (roe !== null && roe < 0) p *= 0.5; assetS = p; }
            safetyScore += assetS * mv;
        });
        const toPct = (v) => (v / totalMv) * 100;
        return { cyclicality: { defensive: toPct(breakdown.cyclicality.defensive), cyclical: toPct(breakdown.cyclicality.cyclical), other: toPct(breakdown.cyclicality.other) }, style: { value: toPct(breakdown.style.value), growth: toPct(breakdown.style.growth), blend: toPct(breakdown.style.blend) }, marketCap: { large: toPct(breakdown.marketCap.large), midSmall: toPct(breakdown.marketCap.midSmall) }, safetyScore: safetyScore / totalMv };
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    let currentRankingPeriod = 'daily'; // 'daily' or 'monthly'
    let currentRankingTab = 'gainers'; // 'gainers' or 'losers'

    function renderRankingModalContent() {
        const rankingContainer = document.getElementById('daily-ranking-content');
        const tabPeriodDailyBtn = document.getElementById('tab-period-daily');
        const tabPeriodMonthlyBtn = document.getElementById('tab-period-monthly');
        const tabGainersBtn = document.getElementById('tab-gainers-top20') || document.getElementById('tab-gainers-top10');
        const tabLosersBtn = document.getElementById('tab-losers-top20') || document.getElementById('tab-losers-top10');
        const monthLabelSpan = document.getElementById('ranking-month-label');
        const modalTitle = document.getElementById('modal-ranking-title');

        if (!rankingContainer || !fullAnalysisData) return;

        const dailyRankings = fullAnalysisData.daily_change_rankings;
        const monthlyRankings = fullAnalysisData.monthly_change_rankings;

        if (monthlyRankings && monthlyRankings.month_label && monthLabelSpan) {
            monthLabelSpan.textContent = monthlyRankings.month_label;
        }

        if (tabPeriodDailyBtn && tabPeriodMonthlyBtn) {
            tabPeriodDailyBtn.onclick = () => {
                currentRankingPeriod = 'daily';
                tabPeriodDailyBtn.classList.add('active');
                tabPeriodMonthlyBtn.classList.remove('active');
                if (modalTitle) modalTitle.textContent = '🚀 当日 資産変動ランキング (TOP20)';
                renderRankingModalContent();
            };
            tabPeriodMonthlyBtn.onclick = () => {
                currentRankingPeriod = 'monthly';
                tabPeriodMonthlyBtn.classList.add('active');
                tabPeriodDailyBtn.classList.remove('active');
                const mLabel = (monthlyRankings && monthlyRankings.month_label) ? monthlyRankings.month_label : '先月末比';
                if (modalTitle) modalTitle.textContent = `🚀 先月比 資産変動ランキング (${mLabel} TOP20)`;
                renderRankingModalContent();
            };
        }

        if (tabGainersBtn && tabLosersBtn) {
            tabGainersBtn.onclick = () => {
                currentRankingTab = 'gainers';
                tabGainersBtn.classList.add('active');
                tabLosersBtn.classList.remove('active');
                renderRankingModalContent();
            };
            tabLosersBtn.onclick = () => {
                currentRankingTab = 'losers';
                tabLosersBtn.classList.add('active');
                tabGainersBtn.classList.remove('active');
                renderRankingModalContent();
            };
        }

        if (currentRankingPeriod === 'daily') {
            renderDailyChangeRankings(dailyRankings);
        } else {
            renderMonthlyChangeRankings(monthlyRankings);
        }
    }

    function renderDailyChangeRankings(rankingsData) {
        const rankingContainer = document.getElementById('daily-ranking-content');
        if (!rankingContainer) return;

        if (!rankingsData) {
            rankingContainer.innerHTML = '<p class="text-muted" style="text-align: center; padding: 15px;">当日の資産変動データは取得中またはありません。</p>';
            return;
        }

        const gainers = rankingsData.day_gainers_top20 || rankingsData.day_gainers_top10 || [];
        const losers = rankingsData.day_losers_top20 || rankingsData.day_losers_top10 || [];

        const currentList = currentRankingTab === 'gainers' ? gainers : losers;
        const isGainer = currentRankingTab === 'gainers';

        if (currentList.length === 0) {
            const msg = isGainer ? '当日の資産増加銘柄はありません。' : '当日の資産減少銘柄はありません。';
            rankingContainer.innerHTML = `<p class="text-muted" style="text-align: center; padding: 20px; font-size: 0.9rem;">${msg}</p>`;
            return;
        }

        let tableHtml = `
            <div class="table-responsive" style="overflow-x: auto;">
                <table class="ranking-table">
                    <thead>
                        <tr>
                            <th style="width: 55px; text-align: center;">順位</th>
                            <th>銘柄名 / コード</th>
                            <th style="text-align: right;">株価前日比</th>
                            <th style="text-align: right;">保有数</th>
                            <th style="text-align: right;">当日 資産変動額</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        currentList.forEach(item => {
            let rankIcon = `#${item.rank}`;
            let rankClass = `rank-num rank-${item.rank}`;
            if (item.rank === 1) rankIcon = '🥇';
            else if (item.rank === 2) rankIcon = '🥈';
            else if (item.rank === 3) rankIcon = '🥉';

            const symbol = item.currency === 'USD' ? '$' : '円';
            const changeSign = item.change > 0 ? '+' : '';
            const changePercentSign = item.change_percent > 0 ? '+' : '';
            const changeStr = (item.change !== null && item.change !== undefined) 
                ? `${changeSign}${formatNumber(item.change, item.currency === 'USD' ? 2 : 0)}${symbol}`
                : 'N/A';
            const changePercentStr = (item.change_percent !== null && item.change_percent !== undefined)
                ? `(${changePercentSign}${formatNumber(item.change_percent, 2)}%)`
                : '';

            const dailyChangeJpy = item.daily_change_jpy || 0;
            const jpySign = dailyChangeJpy > 0 ? '+' : '';
            
            let formattedDailyChange = `${jpySign}${formatNumber(dailyChangeJpy, 0)}円`;
            if (!isAmountVisible) {
                formattedDailyChange = `${jpySign}***円`;
            }

            const badgeClass = dailyChangeJpy > 0 ? 'gainer-badge' : 'loser-badge';

            tableHtml += `
                <tr>
                    <td style="text-align: center;"><span class="${rankClass}">${rankIcon}</span></td>
                    <td>
                        <a href="https://finance.yahoo.co.jp/quote/${item.code}" target="_blank" rel="noopener noreferrer" class="stock-code-link" style="font-weight: 600;">
                            ${escapeHtml(item.name || item.code)}
                        </a>
                        <small class="text-muted" style="display: block; font-size: 0.75rem;">${item.code}</small>
                    </td>
                    <td style="text-align: right;">
                        <span class="${item.change > 0 ? 'profit' : (item.change < 0 ? 'loss' : '')}" style="font-weight: 500;">
                            ${changeStr} <small style="font-size: 0.8rem;">${changePercentStr}</small>
                        </span>
                    </td>
                    <td style="text-align: right; font-size: 0.85rem;">
                        ${formatNumber(item.total_quantity, 0)}株
                    </td>
                    <td style="text-align: right;">
                        <span class="ranking-change-badge ${badgeClass}">
                            ${formattedDailyChange}
                        </span>
                    </td>
                </tr>
            `;
        });

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;
        rankingContainer.innerHTML = tableHtml;
    }

    function renderMonthlyChangeRankings(rankingsData) {
        const rankingContainer = document.getElementById('daily-ranking-content');
        if (!rankingContainer) return;

        if (!rankingsData || !rankingsData.has_last_month_data) {
            rankingContainer.innerHTML = '<p class="text-muted" style="text-align: center; padding: 25px; font-size: 0.9rem;">先月末のスナップショットデータがありません。<br>翌月になると先月末比のランキングが表示されます。</p>';
            return;
        }

        const gainers = rankingsData.month_gainers_top20 || rankingsData.month_gainers_top10 || [];
        const losers = rankingsData.month_losers_top20 || rankingsData.month_losers_top10 || [];
        const currentList = currentRankingTab === 'gainers' ? gainers : losers;
        const isGainer = currentRankingTab === 'gainers';

        if (currentList.length === 0) {
            const msg = isGainer ? '先月比の資産増加銘柄はありません。' : '先月比の資産減少銘柄はありません。';
            rankingContainer.innerHTML = `<p class="text-muted" style="text-align: center; padding: 20px; font-size: 0.9rem;">${msg}</p>`;
            return;
        }

        let tableHtml = `
            <div class="table-responsive" style="overflow-x: auto;">
                <table class="ranking-table">
                    <thead>
                        <tr>
                            <th style="width: 55px; text-align: center;">順位</th>
                            <th>銘柄名 / コード</th>
                            <th style="text-align: right;">先月末 評価額</th>
                            <th style="text-align: right;">現在 評価額</th>
                            <th style="text-align: right;">先月比 資産増減額</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        currentList.forEach(item => {
            let rankIcon = `#${item.rank}`;
            let rankClass = `rank-num rank-${item.rank}`;
            if (item.rank === 1) rankIcon = '🥇';
            else if (item.rank === 2) rankIcon = '🥈';
            else if (item.rank === 3) rankIcon = '🥉';

            const monthlyChangeJpy = item.monthly_change_jpy || 0;
            const jpySign = monthlyChangeJpy > 0 ? '+' : '';
            const pctSign = item.monthly_change_percent > 0 ? '+' : '';
            const pctStr = item.monthly_change_percent !== undefined ? `(${pctSign}${formatNumber(item.monthly_change_percent, 1)}%)` : '';

            let formattedPrevMv = `${formatNumber(item.last_month_market_value || 0, 0)}円`;
            let formattedCurrMv = `${formatNumber(item.current_market_value || 0, 0)}円`;
            let formattedMonthlyChange = `${jpySign}${formatNumber(monthlyChangeJpy, 0)}円`;

            if (!isAmountVisible) {
                formattedPrevMv = '***円';
                formattedCurrMv = '***円';
                formattedMonthlyChange = `${jpySign}***円`;
            }

            const badgeClass = monthlyChangeJpy > 0 ? 'gainer-badge' : 'loser-badge';
            
            let statusBadge = '';
            if (item.is_newly_added) {
                statusBadge = ' <span class="badge" style="background-color: #0284c7; color: white; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; font-weight: normal;">新規</span>';
            } else if (item.is_sold_out) {
                statusBadge = ' <span class="badge" style="background-color: #64748b; color: white; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; font-weight: normal;">売却済</span>';
            }

            let monthlyPurchaseHtml = '';
            if (item.is_purchased_this_month && item.purchased_quantity > 0) {
                const unitStr = item.asset_type === 'investment_trust' ? '口' : '株';
                const qtyFormatted = formatNumber(item.purchased_quantity, item.purchased_quantity % 1 === 0 ? 0 : 2);
                let investedFormatted = `${formatNumber(item.approx_invested_jpy || 0, 0)}円`;
                if (!isAmountVisible) {
                    investedFormatted = '***円';
                }
                monthlyPurchaseHtml = `<div class="monthly-purchase-tag" style="font-size: 0.72rem; color: #0284c7; font-weight: 500; margin-top: 3px; display: flex; align-items: center; gap: 3px;">🛒 当月買付: +${qtyFormatted}${unitStr} (約${investedFormatted})</div>`;
            }

            tableHtml += `
                <tr>
                    <td style="text-align: center;"><span class="${rankClass}">${rankIcon}</span></td>
                    <td>
                        <a href="https://finance.yahoo.co.jp/quote/${item.code}" target="_blank" rel="noopener noreferrer" class="stock-code-link" style="font-weight: 600;">
                            ${escapeHtml(item.name || item.code)}
                        </a>
                        <small class="text-muted" style="display: inline-block; font-size: 0.75rem; margin-left: 4px;">(${escapeHtml(item.code)})</small>
                        ${statusBadge}
                        ${monthlyPurchaseHtml}
                    </td>
                    <td style="text-align: right;" class="text-muted">${formattedPrevMv}</td>
                    <td style="text-align: right;">${formattedCurrMv}</td>
                    <td style="text-align: right;">
                        <span class="ranking-change-badge ${badgeClass}">
                            ${formattedMonthlyChange} <span style="font-size: 0.75rem; font-weight: normal;">${pctStr}</span>
                        </span>
                    </td>
                </tr>
            `;
        });

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;
        rankingContainer.innerHTML = tableHtml;
    }

    function renderDNAAndRisk(stats) {
        const dna = document.getElementById('dna-content'), risk = document.getElementById('risk-content'), personality = document.getElementById('personality-content');
        if (!stats) { [dna, risk, personality].forEach(el => { if (el) el.innerHTML = '<p>データなし</p>'; }); return; }
        
        const thresholds = highlightRules.radar_chart ? highlightRules.radar_chart.benchmarks : {};
        const dnaConfig = highlightRules.portfolio_dna || {};
        const dnaStandards = dnaConfig.standards || {};

        if (dna) {
            if (allHoldingsData.length === 0 && !loadingIndicator.classList.contains('hidden')) return;
            
            // 国内株式未保有時のガード処理
            if (!stats.total_jp_market_value || stats.total_jp_market_value === 0) {
                dna.innerHTML = `
                    <div class="empty-state" style="text-align: center; padding: 20px; color: var(--text-muted);">
                        <p>国内株式の保有データがないため、体質診断は行えません。</p>
                        <small>※本診断は国内株式のみを対象としています。</small>
                    </div>
                `;
            } else {
                const getColor = (v, t, type) => v === null ? '' : (type === 'lower' ? (v <= t ? 'profit' : (v <= t * 1.5 ? 'warning' : 'loss')) : (v >= t ? 'profit' : (v >= t * 0.7 ? 'warning' : 'loss')));
                const lowCov = Object.entries(stats.coverages || {}).filter(([k, v]) => v < 70 && ['per', 'pbr', 'roe', 'yield'].includes(k)).map(([k, v]) => `${k.toUpperCase()}(${Math.round(v)}%)`).join(', ');

                const renderMetric = (label, fullLabel, key, val, suffix, type) => {
                    const std = dnaStandards[key] || {};
                    const stdVal = std.value;
                    const stdLabel = std.label || '基準';
                    const cls = getColor(val, stdVal || (type === 'lower' ? 15 : 8), type);
                    const contributors = (stats.contributors[key] || []).map(c => `・${c.name}: ${formatNumber(c.val, key === 'per' || key === 'pbr' ? 2 : 1)}${suffix}`).join('\n');
                    const title = `【${fullLabel}の主要因】\n${contributors}\n\n※保有額による加重平均への寄与度が高い順`;
                    const diffIcon = val !== null && stdVal ? ( (type === 'lower' ? val <= stdVal : val >= stdVal) ? '<span class="profit">✔</span>' : '<span class="loss">▲</span>' ) : '';

                    return `
                        <div class="dna-metric-item">
                            <div class="dna-metric-header">
                                <span class="dna-metric-label">${label}</span>
                                <span class="dna-info-icon" title="${title}">ⓘ</span>
                            </div>
                            <div class="dna-metric-value">
                                <span class="numeric ${cls}">${formatNumber(val, 2)}${suffix}</span>
                                ${diffIcon}
                            </div>
                            <div class="dna-metric-standard">目標: ${stdVal}${suffix} (${stdLabel})</div>
                        </div>
                    `;
                };

                const perHtml = renderMetric('割安さ(利益)', '平均PER', 'per', stats.weighted_per, '倍', 'lower');
                const pbrHtml = renderMetric('割安さ(資産)', '平均PBR', 'pbr', stats.weighted_pbr, '倍', 'lower');
                const roeHtml = renderMetric('稼ぐ力', '平均ROE', 'roe', stats.weighted_roe, '%', 'higher');
                const yieldHtml = renderMetric('配当利回り', '平均利回り', 'yield', stats.weighted_yield, '%', 'higher');

                // 診断メッセージの決定
                const b = stats.style_breakdown;
                let diagnosisMsg = "";
                if (lowCov) {
                    diagnosisMsg = dnaConfig.diagnosis?.low_coverage || "⚠️ データ不足のため、診断結果は参考値です。";
                } else if (b) {
                    if (b.style.growth > 60) diagnosisMsg = dnaConfig.diagnosis?.growth || "将来の成長を期待した、勢いのある攻めの構成です。";
                    else if (b.style.value > 60) diagnosisMsg = dnaConfig.diagnosis?.value || "実力に対して割安な銘柄が中心の、どっしりした構成です。";
                    else diagnosisMsg = dnaConfig.diagnosis?.balanced || "バランスの取れた標準的な構成です。";
                }

                dna.innerHTML = `
                    <div class="dna-metrics-grid">
                        ${perHtml} ${pbrHtml} ${roeHtml} ${yieldHtml}
                    </div>
                    ${diagnosisMsg ? `<div class="dna-diagnosis-box">${diagnosisMsg}</div>` : ''}
                    ${lowCov ? `<div class="coverage-warning" style="margin-top:10px;">※カバー率不足: ${lowCov}</div>` : ''}
                `;
            }
        }
        if (risk) {
            if (allHoldingsData.length === 0 && !loadingIndicator.classList.contains('hidden')) return;
            
            const riskConfig = highlightRules.concentration_risk || {};
            const riskStandards = riskConfig.standards || {};
            const riskDescriptions = riskConfig.descriptions || {};

            const renderRiskMetric = (label, fullLabel, key, val, suffix, threshold) => {
                const std = riskStandards[key] || {};
                const stdVal = std.value || threshold;
                const stdLabel = std.label || '目標';
                const desc = riskDescriptions[key] || "";
                
                // Color logic: lower is better for risk metrics
                // HHI special handling for consistency with existing logic
                let cls = '';
                if (key === 'hhi') {
                    cls = val >= 2500 ? 'loss' : (val >= stdVal ? 'warning' : 'profit');
                } else {
                    cls = val <= stdVal ? 'profit' : (val <= stdVal * 1.5 ? 'warning' : 'loss');
                }
                
                const topContributors = (stats.top_assets || []).map(a => `・${a.name}: ${formatNumber(a.ratio, 1)}%`).join('\n');
                const title = `【${fullLabel}】\n${desc}\n\n【主要な保有銘柄】\n${topContributors}`;
                const diffIcon = val !== null && stdVal ? ( (val <= stdVal) ? '<span class="profit">✔</span>' : '<span class="loss">▲</span>' ) : '';

                return `
                    <div class="dna-metric-item">
                        <div class="dna-metric-header">
                            <span class="dna-metric-label">${label}</span>
                            <span class="dna-info-icon" title="${title}">ⓘ</span>
                        </div>
                        <div class="dna-metric-value">
                            <span class="numeric ${cls}">${formatNumber(val, key === 'hhi' ? 0 : 1)}${suffix}</span>
                            ${diffIcon}
                        </div>
                        <div class="dna-metric-standard">目標: ${stdVal}${suffix} (${stdLabel})</div>
                    </div>
                `;
            };

            const top5Html = renderRiskMetric('銘柄集中度', '上位5銘柄占有率', 'top5', stats.top5_ratio, '%', 40);
            const hhiHtml = renderRiskMetric('分散の質(HHI)', 'HHI指数', 'hhi', stats.hhi, '', 1500);

            risk.innerHTML = `
                <div class="dna-metrics-grid">
                    ${top5Html} ${hhiHtml}
                </div>
            `;
        }
        if (personality) {
            if (allHoldingsData.length === 0 && !loadingIndicator.classList.contains('hidden')) return;
            const b = stats.style_breakdown;
            if (!b) {
                personality.innerHTML = `
                    <div class="empty-state" style="text-align: center; padding: 20px; color: var(--text-muted);">
                        <p>国内株式の保有データがないため、性格診断は行えません。</p>
                        <small>※本診断は国内株式のみを対象としています。</small>
                    </div>
                `;
            } else {
                const cL = b.cyclicality.defensive > b.cyclicality.cyclical ? '守りに強い' : '景気に敏感な';
                const sL = b.style.value > b.style.growth ? '割安株中心' : '成長株中心';
                const capL = b.marketCap.large > 50 ? '大型株' : '中小型株';
                let adv = b.cyclicality.defensive > 60 && b.style.value > 50 ? "不況に強い構成です。" : (b.style.growth > 50 && b.marketCap.midSmall > 50 ? "攻めの構成です。" : (stats.hhi < 1000 ? "高度に分散されています。" : (stats.top5_ratio > 50 ? "集中投資に注意。" : "バランス良好です。")));
                personality.innerHTML = `<div class="personality-summary"><strong>診断: ${capL}の${cL}${sL}</strong><div class="advice-box">${adv}</div></div><div class="personality-bars"><div class="style-bar-group"><div class="style-bar-label"><span>敏感 ${formatNumber(b.cyclicality.cyclical, 0)}%</span><span>守り ${formatNumber(b.cyclicality.defensive, 0)}%</span></div><div class="progress-stacked"><div class="progress-bar cyclical" style="width: ${b.cyclicality.cyclical}%"></div><div class="progress-bar other" style="width: ${b.cyclicality.other}%"></div><div class="progress-bar defensive" style="width: ${b.cyclicality.defensive}%"></div></div></div><div class="style-bar-group"><div class="style-bar-label"><span>割安 ${formatNumber(b.style.value, 0)}%</span><span>成長 ${formatNumber(b.style.growth, 0)}%</span></div><div class="progress-stacked"><div class="progress-bar value" style="width: ${b.style.value}%"></div><div class="progress-bar blend" style="width: ${b.style.blend}%"></div><div class="progress-bar growth" style="width: ${b.style.growth}%"></div></div></div><div class="style-bar-group"><div class="style-bar-label"><span>大型 ${formatNumber(b.marketCap.large, 0)}%</span><span>中小型 ${formatNumber(b.marketCap.midSmall, 0)}%</span></div><div class="progress-stacked"><div class="progress-bar large" style="width: ${b.marketCap.large}%"></div><div class="progress-bar midSmall" style="width: ${b.marketCap.midSmall}%"></div></div></div></div>`;
            }
        }
    }

    function renderCharts(holdings) {
        if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) return;
        const industryB = {}, accountB = {}, countryB = {}, securityB = {}, divIndB = {};
        holdings.forEach(item => {
            const mv = parseFloat(item.market_value) || 0, div = parseFloat(item.estimated_annual_dividend) || 0, ind = item.industry || 'その他';
            if (mv > 0) { industryB[ind] = (industryB[ind] || 0) + mv; accountB[item.account_type || '不明'] = (accountB[item.account_type || '不明'] || 0) + mv; securityB[item.security_company || '-'] = (securityB[item.security_company || '-'] || 0) + mv; let c = item.asset_type === 'jp_stock' ? '日本' : (item.asset_type === 'us_stock' ? '米国' : '投資信託'); countryB[c] = (countryB[c] || 0) + mv; }
            if (div > 0) divIndB[ind] = (divIndB[ind] || 0) + div;
        });
        const colors = getChartThemeColors(), opts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { color: colors.text } }, tooltip: { callbacks: { label: (c) => { const total = c.dataset.data.reduce((s, v) => s + v, 0), pct = (c.raw / total * 100).toFixed(2); return `${c.label}: ${isAmountVisible ? formatNumber(c.raw, 0) + '円' : '***円'} (${pct}%)`; } } } } };
        const getD = (b) => ({ labels: Object.keys(b), datasets: [{ data: Object.values(b), backgroundColor: generateColors(Object.keys(b).length), hoverOffset: 4 }] });
        const canvasMap = { 'industry-chart': industryB, 'account-type-chart': accountB, 'security-company-chart': securityB, 'country-chart': countryB, 'dividend-industry-chart': divIndB };
        Object.entries(canvasMap).forEach(([id, data]) => { const canvas = document.getElementById(id); if (canvas && Object.keys(data).length > 0) { const ex = Chart.getChart(canvas); if (ex) ex.destroy(); new Chart(canvas, { type: 'pie', data: getD(data), options: opts }); } });
        renderMonthlyDividendChart(holdings);
        const active = document.querySelector('.chart-toggle-btn.active'); updateChart(active ? active.dataset.chartType : 'industry');
    }

    function renderMonthlyDividendChart(holdings) {
        if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) return;
        const mData = new Array(12).fill(0), months = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];
        holdings.forEach(item => {
            const div = parseFloat(item.estimated_annual_dividend) || 0; if (div <= 0) return;
            let base = null; if (item.settlement_month && typeof item.settlement_month === 'string') { const m = item.settlement_month.match(/(\d+)/); if (m) base = parseInt(m[1]); }
            if (base === null) return; const getI = (m, s) => (m + s - 1) % 12;
            if (item.asset_type === 'jp_stock') { mData[getI(base, 3)] += div / 2; mData[getI(base, 9)] += div / 2; }
            else if (item.asset_type === 'us_stock') { for (let i=3; i<=12; i+=3) mData[getI(base, i)] += div / 4; }
            else mData[getI(base, 3)] += div;
        });
        const canvas = document.getElementById('monthly-dividend-chart'); if (!canvas) return;
        const ex = Chart.getChart(canvas); if (ex) ex.destroy();
        const colors = getChartThemeColors();
        monthlyDividendChart = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: { labels: months, datasets: [{ label: '予想受取額', data: mData, backgroundColor: '#1cc88a', borderRadius: 4 }] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: colors.text } },
                    tooltip: {
                        callbacks: {
                            label: (c) => `${c.dataset.label}: ${isAmountVisible ? formatNumber(c.raw, 0) + '円' : '***円'}`
                        }
                    }
                },
                scales: {
                    x: { grid: { color: colors.grid }, ticks: { color: colors.muted } },
                    y: { beginAtZero: true, grid: { color: colors.grid }, ticks: { color: colors.muted, callback: (v) => isAmountVisible ? formatNumber(v, 0) + '円' : '***円' } }
                }
            }
        });
    }

    function updateChart(chartType) {
        document.querySelectorAll('.portfolio-chart .chart-container canvas').forEach(c => c.classList.add('hidden'));
        document.querySelectorAll('.chart-toggle-btn').forEach(b => b.classList.remove('active'));
        const active = document.querySelector(`.chart-toggle-btn[data-chart-type="${chartType}"]`); if (active) active.classList.add('active');
        const canvas = document.getElementById(`${chartType}-chart`); if (canvas) canvas.classList.remove('hidden');
    }

    const formatNumber = (num, fractionDigits = 0) => {
        const parsed = parseFloat(num); if (isNaN(parsed)) return 'N/A';
        return parsed.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
    };

    function showAlert(message, type = 'danger') {
        const alert = document.createElement('div'); alert.className = `alert alert-${type}`; alert.textContent = message;
        alertContainer.appendChild(alert); requestAnimationFrame(() => alert.classList.add('show'));
        setTimeout(() => { alert.classList.replace('show', 'hide'); alert.addEventListener('transitionend', () => alert.remove()); }, 5000);
    }

    function sortHoldings(data) {
        data.sort((a, b) => {
            const p = (v) => { if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '') return -Infinity; if (typeof v === 'object' && v.retracement !== undefined) return v.retracement; if (typeof v === 'string') { const n = parseFloat(v.replace(/,/g, '')); return isNaN(n) ? v : n; } return v; };
            const vA = p(a[currentSort.key]), vB = p(b[currentSort.key]);
            if (typeof vA === 'number' && typeof vB === 'number') return currentSort.order === 'asc' ? vA - vB : vB - vA;
            return currentSort.order === 'asc' ? String(vA).localeCompare(String(vB)) : String(vB).localeCompare(String(vA));
        });
    }

    function updateSortHeaders() {
        document.querySelectorAll('#analysis-table .sortable').forEach(h => { h.classList.remove('sort-active', 'sort-asc', 'sort-desc'); if (h.dataset.key === currentSort.key) h.classList.add('sort-active', `sort-${currentSort.order}`); });
    }

    let allIndustriesCache = [];

    function populateFilters() {
        allIndustriesCache = [...new Set(allHoldingsData.map(item => item.industry || 'N/A'))].sort();
        populateIndustryFilter('');
        const accounts = [...new Set(allHoldingsData.map(item => item.account_type || 'N/A'))].sort();
        accountTypeFilterSelect.innerHTML = '<option value="">すべての口座種別</option>' + accounts.map(acc => `<option value="${acc}">${acc}</option>`).join('');
        const companies = [...new Set(allHoldingsData.map(item => item.security_company || '-'))].sort();
        securityCompanyFilterSelect.innerHTML = '<option value="">すべての証券会社</option>' + companies.map(sc => `<option value="${sc}">${sc}</option>`).join('');
    }

    function populateIndustryFilter(searchText = '') {
        if (!industryFilterSelect) return;

        const currentValue = industryFilterSelect.value;
        const filteredIndustries = searchText
            ? allIndustriesCache.filter(ind => ind.toLowerCase().includes(searchText.toLowerCase()))
            : allIndustriesCache;

        let optionsHtml = '<option value="">すべての業種</option>' + 
            filteredIndustries.map(ind => `<option value="${ind}">${ind}</option>`).join('');

        industryFilterSelect.innerHTML = optionsHtml;

        // 【デグレ防止】選択状態の維持
        const hasCurrentValue = [...industryFilterSelect.options].some(opt => opt.value === currentValue);
        if (hasCurrentValue) {
            industryFilterSelect.value = currentValue;
        } else if (currentValue && currentValue !== "") {
            optionsHtml = `<option value="${currentValue}">${currentValue} (選択中)</option>` + optionsHtml;
            industryFilterSelect.innerHTML = optionsHtml;
            industryFilterSelect.value = currentValue;
        } else {
            industryFilterSelect.value = "";
        }
    }

    function generateColors(num) { const base = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796', '#5a5c69', '#6f42c1', '#fd7e14']; return Array.from({length: num}, (_, i) => base[i % base.length]); }

    async function fetchRecentStocks() {
        try {
            const response = await fetch('/api/recent-stocks');
            if (response.ok) {
                recentCodes = await response.json();
                if (recentCodes && recentCodes.length > 0 && btnRecentFilter) {
                    btnRecentFilter.style.display = 'inline-block';
                }
            }
        } catch (error) {
            console.error('Error fetching recent stocks:', error);
        }
    }

    if (btnRecentFilter) {
        btnRecentFilter.addEventListener('click', () => {
            const recentQuery = recentCodes.join(' ');
            if (analysisFilterInput.value.trim() === recentQuery) {
                analysisFilterInput.value = '';
            } else {
                analysisFilterInput.value = recentQuery;
            }
            filterAndRender();
        });
    }

    analysisFilterInput.addEventListener('input', filterAndRender);
    const analysisIndustrySearch = document.getElementById('analysis-industry-search');
    if (analysisIndustrySearch) {
        analysisIndustrySearch.addEventListener('input', function() {
            populateIndustryFilter(this.value);
        });
    }
    [industryFilterSelect, accountTypeFilterSelect, securityCompanyFilterSelect, buySignalFilterSelect].forEach(s => s.addEventListener('change', filterAndRender));
    document.querySelector('#analysis-table thead').addEventListener('click', (e) => { const h = e.target.closest('.sortable'); if (!h) return; const k = h.dataset.key; if (currentSort.key === k) currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc'; else { currentSort.key = k; currentSort.order = 'asc'; } filterAndRender(); });
    toggleVisibilityCheckbox.addEventListener('change', (e) => { 
        isAmountVisible = !e.target.checked; 
        renderAnalysisTable(filteredHoldingsData); 
        renderSummary(filteredHoldingsData); 
        renderCharts(filteredHoldingsData); 
        fetchAndRenderHistoryData(); 
        if (fullAnalysisData) {
            if (fullAnalysisData.profit_taking_candidates) {
                renderProfitTakingSection(fullAnalysisData.profit_taking_candidates, isAmountVisible);
            }
            if (fullAnalysisData.daily_change_rankings || fullAnalysisData.monthly_change_rankings) { 
                renderRankingModalContent(); 
            }
        } 
    });
    downloadAnalysisCsvButton.addEventListener('click', () => { window.location.href = '/api/portfolio/analysis/csv'; });
    chartToggleBtns.forEach(btn => btn.addEventListener('click', () => updateChart(btn.dataset.chartType)));
    window.addEventListener('pagehide', () => { if (fetchController) fetchController.abort(); });

    function renderBuySignalBadge(signal, isDiamond = false) {
        if (!signal) return '';
        const level = signal.level;
        const isLong = signal.label.includes('長期調整');
        
        // 排他的に1つのテーマを選択するロジック (優先順位順)
        let themeClass = '';
        if (level === 0) {
            themeClass = 'theme-unreliable';
        } else if (isDiamond && level === 2 && isLong) {
            themeClass = 'theme-rainbow';
        } else if (isDiamond && level === 2) {
            themeClass = 'theme-gold';
        } else if ((level === 2 && isLong) || (isDiamond && level === 1 && isLong)) {
            themeClass = 'theme-silver';
        } else if (isDiamond) {
            themeClass = 'theme-diamond';
        } else if (level === 2) {
            themeClass = 'theme-buy-lv2';
        } else if (level === 1) {
            themeClass = 'theme-buy-lv1';
        } else {
            themeClass = 'theme-unreliable';
        }

        const title = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${signal.reasons.join('\n')}`;
        return `<span class="signal-badge-base ${themeClass}" title="${title}"><span class="signal-badge-text"><span class="buy-signal-icon-inner">${signal.icon}</span>${signal.label}</span></span>`;
    }

    function renderSellSignalBadge(signal, isDiamond = false) {
        if (!signal) return '';
        
        // 売却はダイヤモンド属性に関わらず警告色を100%優先
        let themeClass = '';
        if (signal.level === 4) {
            themeClass = 'theme-sell-lv4';
        } else if (signal.level === 2) {
            themeClass = 'theme-sell-lv2';
        } else if (signal.level === 1) {
            themeClass = 'theme-sell-lv1';
        } else {
            themeClass = 'theme-sell-lv3';
        }

        const title = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${signal.reasons.join('\n')}`;
        const label = (isDiamond ? '💎 ' : '') + signal.label;
        return `<span class="signal-badge-base ${themeClass}" title="${title}"><span class="signal-badge-text"><span class="buy-signal-icon-inner">${signal.icon}</span>${label}</span></span>`;
    }

    function renderExhaustionSignalBadge(signal) {
        if (!signal) return '';
        let themeClass = signal.type === 'sell_the_fact' ? 'theme-exhaustion-warn' : 'theme-exhaustion-rebound';
        const title = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${signal.reasons.join('\n')}`;
        return `<span class="signal-badge-base ${themeClass}" title="${title}"><span class="signal-badge-text"><span class="buy-signal-icon-inner">${signal.icon}</span>${signal.label}</span></span>`;
    }

    function renderProfitTakingBadge(item) {
        let ptSignal = item.profit_taking_badge || item.profit_taking_signal;
        if (!ptSignal && item.holdings && item.holdings.length > 0) {
            for (const h of item.holdings) {
                if (h.profit_taking_badge) {
                    if (!ptSignal || h.profit_taking_badge.level > ptSignal.level) {
                        ptSignal = h.profit_taking_badge;
                    }
                }
            }
        }
        if (!ptSignal || !ptSignal.level) return '';

        const badgeStyle = `background-color: ${ptSignal.color || '#eab308'}; color: #ffffff; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 2px; box-shadow: 0 1px 2px rgba(0,0,0,0.15);`;
        const ratioText = (typeof isAmountVisible !== 'undefined' && !isAmountVisible) ? '***年分' : (ptSignal.dividend_years_ratio !== undefined ? `${ptSignal.dividend_years_ratio}年分` : '');
        const ratioStr = ratioText ? `（配当${ratioText}）` : '';
        const titleText = `【売り時・利確検討】\n${ptSignal.full_label || ptSignal.label} ${ratioStr}\n${ptSignal.recommended_action || ''}`;
        
        return `<span class="badge profit-taking-badge" style="${badgeStyle}" title="${titleText}">${ptSignal.full_label || ptSignal.label}</span>`;
    }

    function renderProfitTakingSection(candidates, isAmountVisible) {
        const container = document.getElementById('profit-taking-content');
        if (!container) return;

        if (!candidates || candidates.length === 0) {
            container.innerHTML = `
                <div class="empty-profit-taking text-center text-muted py-4" style="font-size: 0.9rem;">
                    <i class="fas fa-info-circle me-1" style="color: #3b82f6;"></i> 現在、含み益が年間予定配当の10年分以上に達している銘柄はありません。
                </div>
            `;
            return;
        }

        let tableHtml = `
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0 profit-taking-table" style="font-size: 0.88rem;">
                    <thead>
                        <tr class="table-dark" style="background: linear-gradient(to right, #0f172a, #1e293b); color: #ffffff;">
                            <th style="width: 60px; color: #ffffff;" class="text-center">順位</th>
                            <th style="color: #ffffff;">銘柄名 (コード)</th>
                            <th style="color: #ffffff;" class="text-end">現在評価額</th>
                            <th style="color: #ffffff;" class="text-end">含み益</th>
                            <th style="color: #ffffff;" class="text-end">年間予定配当</th>
                            <th style="color: #ffffff; width: 95px;" class="text-end">配当利回り</th>
                            <th style="width: 210px; color: #ffffff;" class="text-center">到達レベル (推薦アクション)</th>
                            <th style="width: 110px; color: #ffffff;" class="text-center">AI診断</th>
                        </tr>
                    </thead>
                    <tbody>
        `;

        candidates.forEach((item, index) => {
            const rankNum = item.rank || (index + 1);
            let rankBadgeHtml = `<span class="rank-badge-number">${rankNum}</span>`;
            if (rankNum === 1) rankBadgeHtml = `<span class="rank-medal-icon" title="第1位">🥇</span>`;
            else if (rankNum === 2) rankBadgeHtml = `<span class="rank-medal-icon" title="第2位">🥈</span>`;
            else if (rankNum === 3) rankBadgeHtml = `<span class="rank-medal-icon" title="第3位">🥉</span>`;

            const mvStr = isAmountVisible ? formatNumber(item.market_value, 0) + '円' : '***円';
            const plStr = isAmountVisible ? '+' + formatNumber(item.profit_loss, 0) + '円' : '***円';
            const divStr = isAmountVisible ? formatNumber(item.estimated_annual_dividend, 0) + '円' : '***円';
            
            const yieldVal = item.dividend_yield !== undefined && item.dividend_yield !== null 
                ? item.dividend_yield 
                : (item.market_value > 0 && item.estimated_annual_dividend > 0 ? ((item.estimated_annual_dividend / item.market_value) * 100) : null);
            const yieldStr = yieldVal !== null && !isNaN(yieldVal) ? yieldVal.toFixed(2) + '%' : 'N/A';

            const ratioText = isAmountVisible ? (item.dividend_years_ratio !== undefined ? item.dividend_years_ratio + '年分' : '') : '***年分';
            const badge = item.profit_taking_badge || {};

            let capsuleClass = 'profit-capsule-level-1';
            if (badge.level === 4) capsuleClass = 'profit-capsule-level-4';
            else if (badge.level === 3) capsuleClass = 'profit-capsule-level-3';
            else if (badge.level === 2) capsuleClass = 'profit-capsule-level-2';

            const tooltipText = `【到達レベル】${badge.full_label || badge.label || ''} (配当${ratioText})\n💡 【推薦アクション】${badge.recommended_action || ''}`;

            tableHtml += `
                <tr>
                    <td class="text-center">${rankBadgeHtml}</td>
                    <td>
                        <span class="fw-bold">${item.name || ''}</span>
                        <small class="text-muted ms-1">(${item.code})</small>
                    </td>
                    <td class="text-end numeric">${mvStr}</td>
                    <td class="text-end numeric">
                        <span class="profit-pill-highlight">${plStr}</span>
                    </td>
                    <td class="text-end numeric">${divStr}</td>
                    <td class="text-end numeric">
                        <span class="yield-pill-highlight">${yieldStr}</span>
                    </td>
                    <td class="text-center">
                        <span class="profit-capsule-badge ${capsuleClass}" title="${tooltipText}" style="cursor: help;">
                            <span>${badge.icon || ''}</span>
                            <span>${badge.label || ''} (${ratioText})</span>
                        </span>
                    </td>
                    <td class="text-center">
                        <button type="button" class="btn-pt-ai-diagnose" onclick="openProfitTakingAiModal('${item.code}')">
                            🤖 AI診断
                        </button>
                    </td>
                </tr>
            `;
        });

        tableHtml += `
                    </tbody>
                </table>
            </div>
        `;

        container.innerHTML = tableHtml;
    }

    async function openProfitTakingAiModal(code, force = false) {
        const modal = document.getElementById('profit-taking-ai-modal');
        const modalBody = document.getElementById('pt-ai-modal-body');
        const headerText = document.getElementById('pt-ai-modal-header-text');
        const badgeYears = document.getElementById('pt-ai-badge-years');
        const footerMeta = document.getElementById('pt-ai-modal-footer-meta');

        if (!modal || !modalBody) return;

        // 全候補の中から対象アイテムを探索
        let targetItem = null;
        if (fullAnalysisData && fullAnalysisData.profit_taking_candidates) {
            targetItem = fullAnalysisData.profit_taking_candidates.find(c => c.code === code);
        }

        const name = targetItem ? targetItem.name : code;
        const badge = targetItem ? (targetItem.profit_taking_badge || {}) : {};
        
        if (headerText) headerText.textContent = `🤖 AI利確・銘柄入替診断 : ${name} (${code})`;
        if (badgeYears) {
            badgeYears.textContent = `${badge.icon || '💰'} ${badge.label || '利確検討銘柄'}`;
            let capsuleClass = 'profit-capsule-level-1';
            if (badge.level === 4) capsuleClass = 'profit-capsule-level-4';
            else if (badge.level === 3) capsuleClass = 'profit-capsule-level-3';
            else if (badge.level === 2) capsuleClass = 'profit-capsule-level-2';
            badgeYears.className = `profit-capsule-badge ${capsuleClass} ms-2`;
        }

        modalBody.innerHTML = `
            <div class="text-center py-4">
                <div class="spinner-border text-indigo mb-2" role="status" style="width: 2.2rem; height: 2.2rem; color: #6366f1;"></div>
                <div style="font-size: 0.9rem;" class="fw-bold">AI利確・銘柄入替解析を実行中...</div>
                <div style="font-size: 0.78rem;" class="text-muted mt-1">業績・ファンダメンタルズ・配当効率を総合評価しています</div>
            </div>
        `;
        if (footerMeta) footerMeta.innerHTML = '';
        modal.classList.remove('hidden');
        modal.style.display = 'flex';

        try {
            const response = await fetch('/api/ai-diagnosis/profit-taking', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code, force: force })
            });

            const data = await response.json();
            if (!response.ok || data.error || !data.action) {
                const errMsg = data.message || 'AI利確診断の実行中にエラーが発生しました。';
                modalBody.innerHTML = `
                    <div class="alert alert-warning py-3 mb-0" style="font-size: 0.88rem;">
                        <i class="fas fa-exclamation-triangle me-1"></i> ${errMsg}
                    </div>
                `;
                if (footerMeta) {
                    footerMeta.innerHTML = `
                        <button type="button" class="pt-ai-retry-btn ms-2" onclick="openProfitTakingAiModal('${code}', true)" aria-label="銘柄のAI診断を再実行">
                            🔄 再診断をお試しください
                        </button>
                    `;
                }
                return;
            }

            // 成功レスポンスのレンダリング
            let badgeClass = 'pt-ai-badge-partial';
            if (data.action === 'HOLD') badgeClass = 'pt-ai-badge-hold';
            else if (data.action === 'FULL_SELL') badgeClass = 'pt-ai-badge-full';

            const cacheTag = data.is_cached 
                ? `<span class="badge bg-success-subtle text-success border border-success-subtle me-1">⚡ キャッシュ表示 (${data.diagnosed_at || ''})</span>`
                : `<span class="badge bg-indigo-subtle text-indigo border border-indigo-subtle me-1" style="background: rgba(99, 102, 241, 0.12); color: #4f46e5;">🤖 リアルタイム診断 (${data.diagnosed_at || ''})</span>`;

            const fundamentalsText = data.fundamentals_analysis || '直近業績・ファンダメンタルズおよび配当効率の分析を完了しました。';
            const adviceText = data.profit_taking_advice || '配当原資の最大化とポートフォリオ最適化の観点から助言を作成しました。';

            modalBody.innerHTML = `
                <div class="pt-ai-result-card text-center mb-3 py-3" style="background: var(--card-bg, #f8fafc); border-radius: 10px;">
                    <div class="text-muted small mb-1" style="font-size: 0.78rem;">AIの判定結果</div>
                    <div class="pt-ai-action-badge ${badgeClass} mb-2">
                        ${data.action_label || 'AI判定完了'}
                    </div>
                    <div class="fw-bold text-indigo mt-1" style="font-size: 0.92rem; color: #4f46e5;">
                        💡 ${data.target_sell_ratio || '状況に応じて調整'}
                    </div>
                </div>

                ${data.industry_growth_evaluation ? `
                <div class="pt-ai-result-card mb-3">
                    <div class="fw-bold mb-1" style="font-size: 0.88rem; color: #8b5cf6;">
                        🚀 業種将来性・国策・成長力評価
                    </div>
                    <div style="font-size: 0.85rem; line-height: 1.6;">
                        ${data.industry_growth_evaluation}
                    </div>
                </div>
                ` : ''}

                <div class="pt-ai-result-card mb-3">
                    <div class="fw-bold mb-1" style="font-size: 0.88rem; color: #0284c7;">
                        📊 業績動向とファンダメンタルズ評価
                    </div>
                    <div style="font-size: 0.85rem; line-height: 1.6;">
                        ${fundamentalsText}
                    </div>
                </div>

                <div class="pt-ai-result-card mb-0">
                    <div class="fw-bold mb-1" style="font-size: 0.88rem; color: #16a34a;">
                        💡 利確・恩株化・銘柄入替のアドバイス
                    </div>
                    <div style="font-size: 0.85rem; line-height: 1.6;">
                        ${adviceText}
                    </div>
                </div>
            `;

            if (footerMeta) {
                footerMeta.innerHTML = `
                    ${cacheTag}
                    <button type="button" class="pt-ai-retry-btn ms-2" onclick="openProfitTakingAiModal('${code}', true)" aria-label="銘柄のAI診断を再実行">
                        🔄 再診断
                    </button>
                `;
            }

        } catch (err) {
            modalBody.innerHTML = `
                <div class="alert alert-danger py-3 mb-0" style="font-size: 0.88rem;">
                    <i class="fas fa-times-circle me-1"></i> 通信エラーが発生しました: ${err.message}
                </div>
            `;
        }
    }

    // グローバルへ公開
    window.openProfitTakingAiModal = openProfitTakingAiModal;

    function getHighlightClass(key, value, assetType) {
        if (assetType !== 'jp_stock' && assetType !== 'us_stock') return '';
        if (!highlightRules) return '';
        const rules = highlightRules[key]; if (!rules || !value || value === 'N/A') return '';
        const num = parseFloat(String(value).replace(/[^0-9.-]/g, '')); if (isNaN(num)) return '';
        if (key === 'payout_ratio') {
            if (num > 0 && num <= rules.safe_max) return 'undervalued';
            if (num > rules.safe_max) return 'overvalued';
        } else if (key === 'doe') {
            if (assetType !== 'jp_stock') return '';
            if (num >= rules.good_min) return 'undervalued';
        } else {
            if (assetType !== 'jp_stock') return '';
            if (key === 'yield' || key === 'roe') { if (num >= rules.undervalued) return 'undervalued'; }
            else { if (num <= rules.undervalued) return 'undervalued'; if (num >= rules.overvalued) return 'overvalued'; }
        }
        return '';
    }

    function formatPayoutRatioHistory(historyList) {
        if (!historyList || historyList.length === 0) return '';
        return '配当性向の推移:\n' + historyList.map(item => {
            const date = item.settlementDateFormatted || item.settlementDate || '不明';
            const ratio = item.payoutRatioFormattedWithUnit || (item.payoutRatioValue !== undefined ? item.payoutRatioValue + '%' : 'N/A');
            return `・${date}: ${ratio}`;
        }).join('\n');
    }

    fetchHighlightRules();
    fetchAndRenderAnalysisData();
    fetchRecentStocks();

    // 免責事項バナーの制御 (閉じる / 再表示 & localStorage 連携)
    // --- バックグラウンド同期進捗バナー制御 (#262) ---
    let syncIntervalId = null;
    let syncCompletedTimerId = null;

    async function checkSyncStatus() {
        try {
            const response = await fetch('/api/portfolio/sync_status');
            if (!response.ok) return;
            const statusData = await response.json();
            const bannerEl = document.getElementById('sync-status-banner');
            if (!bannerEl) return;

            if (!statusData.is_syncing && statusData.status === 'idle') {
                bannerEl.classList.add('hidden');
                if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                if (syncIntervalId) { clearInterval(syncIntervalId); syncIntervalId = null; }
                return;
            }

            bannerEl.classList.remove('hidden');
            bannerEl.className = 'sync-status-banner';

            if (statusData.is_syncing && statusData.status === 'syncing') {
                isSyncing = true;
                if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                if (updateReportContainer) updateReportContainer.classList.add('hidden');
                bannerEl.classList.add('status-syncing');
                const currName = statusData.current_name || statusData.current_code || '';
                bannerEl.innerHTML = `
                    <span>🔄 前日・過去データを表示中（バックグラウンドで最新データを更新中: <strong>${statusData.completed_count} / ${statusData.total_count}</strong>件完了 | 現在: ${currName}）</span>
                    <small style="opacity: 0.8;">※画面操作はそのまま可能です</small>
                `;
            } else {
                isSyncing = false;
                if (statusData.status === 'completed') {
                    bannerEl.classList.add('status-completed');
                    const lastTime = statusData.last_completed_at ? new Date(statusData.last_completed_at).toLocaleString() : '';
                    bannerEl.innerHTML = `
                        <span>✅ 最新データへの更新が完了しました (${lastTime})</span>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <button type="button" onclick="location.reload()" class="btn-outline" style="padding: 2px 8px; font-size: 0.75rem;">画面を更新</button>
                            <button type="button" class="disclaimer-close-btn btn-close-sync-status" title="閉じる" aria-label="閉じる">&times;</button>
                        </div>
                    `;

                    const btnCloseSync = bannerEl.querySelector('.btn-close-sync-status');
                    if (btnCloseSync) {
                        btnCloseSync.onclick = () => {
                            bannerEl.classList.add('hidden');
                            if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                        };
                    }

                    if (syncCompletedTimerId) clearTimeout(syncCompletedTimerId);
                    syncCompletedTimerId = setTimeout(() => {
                        bannerEl.classList.add('hidden');
                        syncCompletedTimerId = null;
                    }, 5000);

                    if (syncIntervalId) { clearInterval(syncIntervalId); syncIntervalId = null; }
                } else if (statusData.status === 'circuit_broken') {
                    if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                    bannerEl.classList.add('status-circuit-broken');
                    bannerEl.innerHTML = `
                        <span>⚠️ ${statusData.error_message || 'アクセス制限を検知したため安全停止しました'}</span>
                    `;
                    if (syncIntervalId) { clearInterval(syncIntervalId); syncIntervalId = null; }
                }
            }
        } catch (e) {
            console.error('Failed to check sync status:', e);
        }
    }

    function initSyncStatusPolling() {
        checkSyncStatus();
        if (!syncIntervalId) {
            syncIntervalId = setInterval(checkSyncStatus, 3000);
        }
    }

    initSyncStatusPolling();

    // 過去の免責バナー閉じる記憶キーの自動クリーンアップ (常時表示仕様 #288)
    if (localStorage.getItem('disclaimer_banner_closed')) {
        localStorage.removeItem('disclaimer_banner_closed');
    }

    // --- 主要指数フィボナッチ参照モーダル制御 (#231) ---
    if (typeof initMarketFibonacciModal === 'function') {
        initMarketFibonacciModal();
    }
});
