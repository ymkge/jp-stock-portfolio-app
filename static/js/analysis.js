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

    // --- Chart.jsインスタンス ---
    let industryChart, accountTypeChart, countryChart, securityCompanyChart, dividendIndustryChart;
    let assetHistoryChart, dividendHistoryChart, monthlyDividendChart, radarChart;

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

    // --- スケルトンUI表示 ---
    function showSkeletons() {
        // 1. 市場サマリー (3枚のカード)
        const marketContainer = document.getElementById('market-summary-container');
        if (marketContainer) {
            marketContainer.innerHTML = Array(3).fill(0).map(() => `
                <div class="market-index-card">
                    <div class="skeleton skeleton-text" style="width: 40%; height: 1.2rem;"></div>
                    <div class="skeleton skeleton-text" style="width: 70%; height: 1.8rem; margin: 0.5rem 0;"></div>
                    <div class="skeleton skeleton-text" style="width: 90%;"></div>
                    <div class="skeleton skeleton-text" style="width: 80%;"></div>
                </div>
            `).join('');
            marketContainer.classList.remove('hidden');
        }

        // 2. 左カラムのカード群
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
            // radar-chart 等 ID があるものは残しつつ、スケルトンを被せる
            const canvas = container.querySelector('canvas');
            if (canvas) canvas.classList.add('hidden');
            
            // 既存のスケルトンがあれば削除
            const existing = container.querySelector('.skeleton-overlay');
            if (existing) existing.remove();

            const isPie = container.parentElement.classList.contains('portfolio-chart');
            const skeletonHtml = isPie 
                ? `<div class="skeleton-overlay" style="display:flex; justify-content:center; align-items:center; height:100%;"><div class="skeleton skeleton-circle" style="width:200px; height:200px;"></div></div>`
                : `<div class="skeleton-overlay" style="height:100%;"><div class="skeleton skeleton-rect"></div></div>`;
            
            container.insertAdjacentHTML('beforeend', skeletonHtml);
        });

        // 4. テーブル (5行のスケルトン)
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
    }

    // --- データ取得とレンダリング ---
    async function fetchHighlightRules() {
        try {
            const response = await fetch('/api/highlight-rules');
            if (!response.ok) throw new Error('Failed to fetch rules');
            highlightRules = await response.json();
            
            // ルールが取得できたら、既にデータがあれば再描画
            if (allHoldingsData && allHoldingsData.length > 0) {
                filterAndRender();
            }
        } catch (error) {
            console.error('Error fetching highlight rules:', error);
        }
    }

    async function fetchAndRenderAnalysisData() {
        if (fetchController) {
            fetchController.abort(); // 既存のリクエストをキャンセル
        }
        fetchController = new AbortController();
        const signal = fetchController.signal;

        const cachedData = window.appState.getState('analysis');
        if (cachedData) {
            processAnalysisData(cachedData);
            // 防衛的メタデータ取得
            const cachedMetadata = cachedData.metadata || (cachedData.data && cachedData.data.metadata);
            if (cachedMetadata) {
                renderUpdateReport(cachedMetadata);
            }
            fetchAndRenderHistoryData();
        } else {
            // キャッシュがない場合は即座にスケルトンを表示
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
            
            hideSkeletons(); // データが来たらスケルトンを隠す
            processAnalysisData(analysisData);
            if (analysisData.metadata) {
                renderUpdateReport(analysisData.metadata);
            }
            loadingIndicator.classList.add('hidden');

            // メインデータの更新が終わったら履歴データも取得
            fetchAndRenderHistoryData();

        } catch (error) {
            if (error.name === 'AbortError') {
                return;
            }
            
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

    function renderUpdateReport(metadata) {
        if (!updateReportContainer || !metadata) return;

        const timeStr = new Date(metadata.fetched_at).toLocaleString();
        const successClass = metadata.fail_count > 0 ? 'loss' : 'profit';

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
            </div>
        `;
        updateReportContainer.classList.remove('hidden');

        // 市場サマリーの描画
        if (metadata.market_indices) {
            renderMarketSummary(metadata.market_indices);
        }
    }

    /**
     * 市場指標サマリーをレンダリングする
     */
    function renderMarketSummary(indices) {
        const container = document.getElementById('market-summary-container');
        if (!container || !indices) return;

        let html = '';
        indices.forEach(idx => {
            const price = idx.price || '--';
            const change = idx.change || '--';
            const changePercent = idx.change_percent || '--';
            const wow = idx.wow_percent || '--';
            const mom = idx.mom_percent || '--';

            const getChangeClass = (val) => {
                if (typeof val === 'string') {
                    if (val.startsWith('+')) return 'price-up';
                    if (val.startsWith('-')) return 'price-down';
                } else if (typeof val === 'number') {
                    if (val > 0) return 'price-up';
                    if (val < 0) return 'price-down';
                }
                return '';
            };

            const formatPercent = (val) => {
                if (val === '--' || val === 'N/A' || val === null) return '--';
                if (typeof val === 'number') {
                    const sign = val > 0 ? '+' : '';
                    return `${sign}${val.toFixed(2)}%`;
                }
                // 文字列の場合でも数値なら+を付与
                const num = parseFloat(val);
                if (!isNaN(num)) {
                    const sign = num > 0 ? '+' : '';
                    return `${sign}${num.toFixed(2)}%`;
                }
                return `${val}%`;
            };

            const changeClass = getChangeClass(change);
            const wowClass = getChangeClass(wow);
            const momClass = getChangeClass(mom);

            html += `
                <a href="https://finance.yahoo.co.jp/quote/${idx.code}" target="_blank" class="market-index-link">
                    <div class="market-index-card">
                        <div class="market-index-header">
                            <span class="market-index-name">${idx.name}</span>
                            <span class="market-index-code" style="font-size: 0.7rem; color: var(--text-muted);">${idx.code}</span>
                        </div>
                        <div class="market-index-price">${price}</div>
                        <div class="market-index-changes">
                            <div class="market-index-row">
                                <span class="change-label">前日比:</span>
                                <span class="${changeClass}">${change} (${formatPercent(changePercent)})</span>
                            </div>
                            <div class="market-index-row">
                                <span class="change-label">前週比:</span>
                                <span class="${wowClass}">${formatPercent(wow)}</span>
                            </div>
                            <div class="market-index-row">
                                <span class="change-label">前月比:</span>
                                <span class="${momClass}">${formatPercent(mom)}</span>
                            </div>
                        </div>
                    </div>
                </a>
            `;
        });
        container.innerHTML = html;
        container.classList.remove('hidden');
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
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: { color: colors.text }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) label += ': ';
                            const formattedValue = isAmountVisible ? formatNumber(context.raw, 0) + '円' : '***円';
                            label += formattedValue;
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: colors.grid },
                    ticks: { color: colors.muted }
                },
                y: {
                    beginAtZero: true,
                    grid: { color: colors.grid },
                    ticks: {
                        color: colors.muted,
                        callback: function(value) {
                            return isAmountVisible ? formatNumber(value, 0) + '円' : '***円';
                        }
                    }
                }
            }
        };

        // 資産推移グラフ
        const assetCanvas = document.getElementById('asset-history-chart');
        if (assetCanvas) {
            const existingChart = Chart.getChart(assetCanvas);
            if (existingChart) existingChart.destroy();
            
            const assetCtx = assetCanvas.getContext('2d');
            assetHistoryChart = new Chart(assetCtx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: '総資産額',
                            data: marketValues,
                            borderColor: '#4e73df',
                            backgroundColor: 'rgba(78, 115, 223, 0.1)',
                            fill: true,
                            tension: 0.3
                        },
                        {
                            label: '投資元本',
                            data: originalInvestments,
                            borderColor: '#858796',
                            borderDash: [5, 5],
                            fill: false,
                            tension: 0
                        }
                    ]
                },
                options: commonOptions
            });
        }

        // 配当推移グラフ
        const divCanvas = document.getElementById('dividend-history-chart');
        if (divCanvas) {
            const existingChart = Chart.getChart(divCanvas);
            if (existingChart) existingChart.destroy();

            const divCtx = divCanvas.getContext('2d');
            dividendHistoryChart = new Chart(divCtx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: '年間配当予定額',
                        data: dividends,
                        backgroundColor: '#1cc88a',
                        borderRadius: 4
                    }]
                },
                options: commonOptions
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
    }

    // --- レンダリング関連 ---
    function filterAndRender() {
        const filterText = analysisFilterInput.value.toLowerCase();
        const selectedIndustry = industryFilterSelect.value;
        const selectedAccountType = accountTypeFilterSelect.value;
        const selectedSecurityCompany = securityCompanyFilterSelect.value;
        const selectedBuySignal = buySignalFilterSelect.value;

        filteredHoldingsData = allHoldingsData.filter(item => {
            const matchesText = String(item.code).toLowerCase().includes(filterText) ||
                                String(item.name || '').toLowerCase().includes(filterText);
            const matchesIndustry = !selectedIndustry || item.industry === selectedIndustry || (selectedIndustry === 'N/A' && !item.industry);
            const matchesAccountType = !selectedAccountType || item.account_type === selectedAccountType;
            const matchesSecurityCompany = !selectedSecurityCompany || (item.security_company || '-') === selectedSecurityCompany;
            
            const isDiamond = item.is_diamond === true || (item.buy_signal && item.buy_signal.is_diamond === true);
            const matchesBuySignal = !selectedBuySignal || (
                (selectedBuySignal === 'strict-dip' && isDiamond && item.buy_signal && item.buy_signal.level >= 1) ||
                (selectedBuySignal === 'strict-low' && isDiamond && item.sell_signal && item.sell_signal.level === 3) ||
                (selectedBuySignal === 'overheated' && item.sell_signal && (item.sell_signal.level === 1 || item.sell_signal.level === 2))
            );

            return matchesText && matchesIndustry && matchesAccountType && matchesSecurityCompany && matchesBuySignal;
        });

        sortHoldings(filteredHoldingsData);
        renderAnalysisTable(filteredHoldingsData);
        renderSummary(filteredHoldingsData);
        renderCharts(filteredHoldingsData);
        updateSortHeaders();
    }

    function renderAnalysisTable(holdings) {
        // データ取得中（loadingIndicatorが表示中）かつデータが0件ならスケルトンを維持
        if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) {
            renderTableSkeletons();
            return;
        }

        analysisTableBody.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            analysisTableBody.innerHTML = `<tr><td colspan="16" style="text-align:center;">該当する保有銘柄はありません。</td></tr>`;
            return;
        }

        holdings.forEach(item => {
            const row = analysisTableBody.insertRow();
            const createCell = (html, className = '') => {
                const cell = row.insertCell();
                cell.innerHTML = html;
                if (className) cell.className = className;
                return cell;
            };

            const profitLoss = parseFloat(item.profit_loss);
            const profitLossRate = parseFloat(item.profit_loss_rate);
            const profitLossClass = isNaN(profitLoss) ? '' : (profitLoss >= 0 ? 'profit' : 'loss');
            const profitLossRateClass = isNaN(profitLossRate) ? '' : (profitLossRate >= 0 ? 'profit' : 'loss');

            createCell(item.code);
            
            // 銘柄名とシグナルの表示
            let nameHtml = `<span class="fw-bold me-1">${item.name}</span>`;
            const isDiamond = item.is_diamond || (item.buy_signal && item.buy_signal.is_diamond);
            if (item.buy_signal) {
                nameHtml += renderBuySignalBadge(item.buy_signal, isDiamond);
            }
            if (item.sell_signal) {
                nameHtml += renderSellSignalBadge(item.sell_signal, isDiamond);
            }
            createCell(nameHtml);

            createCell(item.industry || 'N/A');
            createCell(item.asset_type === 'jp_stock' ? '国内株式' : (item.asset_type === 'investment_trust' ? '投資信託' : (item.asset_type === 'us_stock' ? '米国株式' : 'N/A')));
            createCell(item.security_company || '-'); 
            createCell(item.account_type);
            
            createCell(formatNumber(item.quantity, item.asset_type === 'investment_trust' ? 6 : 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.purchase_price, 2), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.price, 2));
            createCell(formatNumber(item.estimated_annual_dividend, 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.estimated_annual_dividend_after_tax, 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.dividend_contribution, 2), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.market_value, 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.profit_loss, 0), `${!isAmountVisible ? 'masked-amount' : ''} ${profitLossClass}`);
            createCell(formatNumber(item.profit_loss_rate, 2), `${!isAmountVisible ? 'masked-amount' : ''} ${profitLossRateClass}`);
            createCell(item.memo || '-'); 
        });
    }

    function renderSummary(holdings) {
        // 現在の計算値 (フィルタ後の holdings に基づく)
        const totalMarketValue = holdings.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        const totalProfitLoss = holdings.reduce((sum, item) => sum + (parseFloat(item.profit_loss) || 0), 0);
        const totalInvestment = totalMarketValue - totalProfitLoss;
        const totalProfitLossRate = totalInvestment !== 0 ? (totalProfitLoss / totalInvestment) * 100 : 0;
        
        const totalEstimatedAnnualDividend = holdings.reduce((sum, item) => sum + (parseFloat(item.estimated_annual_dividend) || 0), 0);
        const totalEstimatedAnnualDividendAfterTax = holdings.reduce((sum, item) => sum + (parseFloat(item.estimated_annual_dividend_after_tax) || 0), 0);

        const dividendPayingHoldings = holdings.filter(item => (parseFloat(item.estimated_annual_dividend) || 0) > 0);
        const mvOfDividendPaying = dividendPayingHoldings.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        const costOfDividendPaying = dividendPayingHoldings.reduce((sum, item) => {
            const mv = parseFloat(item.market_value) || 0;
            const pl = parseFloat(item.profit_loss) || 0;
            return sum + (mv - pl);
        }, 0);

        const yieldOnCurrent = mvOfDividendPaying > 0 ? (totalEstimatedAnnualDividend / mvOfDividendPaying * 100) : 0;
        const yieldOnCost = costOfDividendPaying > 0 ? (totalEstimatedAnnualDividend / costOfDividendPaying * 100) : 0;

        const summaryProfitLossClass = totalProfitLoss >= 0 ? 'profit' : 'loss';
        const summaryProfitLossRateClass = totalProfitLossRate >= 0 ? 'profit' : 'loss';

        // --- 30日前比 (MoM相当) の計算 ---
        const currentTotalMV = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        const currentTotalPL = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.profit_loss) || 0), 0);
        const currentTotalDiv = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.estimated_annual_dividend) || 0), 0);

        const prev = fullAnalysisData.previous_summary;
        
        const calcDiff = (current, previous) => {
            if (!previous || previous === 0) return null;
            return ((current - previous) / previous) * 100;
        };

        const formatDiff = (diff) => {
            if (diff === null) return '';
            const cls = diff >= 0 ? 'profit' : 'loss';
            const sign = diff >= 0 ? '+' : '';
            return `<small class="${cls}" style="margin-left: 8px; font-weight: bold;" title="30日前（または直近の過去データ）との比較です">(${sign}${diff.toFixed(2)}%)</small>`;
        };

        const isFiltered = holdings.length !== allHoldingsData.length;
        const momSuffixMV = !isFiltered ? formatDiff(calcDiff(currentTotalMV, prev ? prev.total_market_value : 0)) : '';
        const momSuffixPL = !isFiltered ? formatDiff(calcDiff(currentTotalPL, prev ? prev.total_profit_loss : 0)) : '';
        const momSuffixDiv = !isFiltered ? formatDiff(calcDiff(currentTotalDiv, prev ? prev.total_dividend : 0)) : '';

        // --- サマリー表示の更新 ---
        const summaryContent = document.getElementById('summary-content');
        if (summaryContent) {
            // データが0件かつ読み込み中ならスケルトンを表示
            if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) return;

            summaryContent.innerHTML = `
                <p>総評価額: <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalMarketValue, 0)}円</span>${momSuffixMV}</p>
                <p>総損益: <span class="${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossClass}">${formatNumber(totalProfitLoss, 0)}円</span>${momSuffixPL}</p>
                <p>総損益率: <span class="${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossRateClass}">${formatNumber(totalProfitLossRate, 2)}%</span></p>
                <p>年間配当合計: <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividend, 0)}円</span>${momSuffixDiv}</p>
                <p>年間配当合計(税引後): <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividendAfterTax, 0)}円</span></p>
                <hr>
                <p title="配当が発生する資産（投資信託等を除く）の評価額合計です">配当対象資産の評価額: <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(mvOfDividendPaying, 0)}円</span></p>
                <p title="配当が出る銘柄のみを対象とした利回りです">配当利回り(現在値): <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(yieldOnCurrent, 2)}%</span></p>
                <p title="配当が出る銘柄のみを対象とした、投資額に対する利回りです">配当利回り(取得値): <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(yieldOnCost, 2)}%</span></p>
            `;
        }

        const stats = calculateWeightedStats(holdings);
        renderDNAAndRisk(stats);
        renderRadarChart(stats);
    }

    function renderRadarChart(stats) {
        if (!stats || !highlightRules || !highlightRules.radar_chart) return;

        const canvas = document.getElementById('radar-chart');
        if (!canvas) return;

        const existingChart = Chart.getChart(canvas);
        if (existingChart) existingChart.destroy();

        const ctx = canvas.getContext('2d');
        const colors = getChartThemeColors();
        const config = highlightRules.radar_chart;
        const bm = config.benchmarks;

        const normalize = (val, min, max, reverse = false) => {
            if (val === null || val === undefined) return 0;
            let score = ((val - min) / (max - min)) * 100;
            if (reverse) score = 100 - score;
            return Math.min(Math.max(score, 0), 100);
        };

        const safeGet = (obj, path, def = 0) => {
            return path.split('.').reduce((acc, part) => acc && acc[part], obj) || def;
        };

        const scores = [
            (normalize(stats.weighted_per, 10, 40, true) + normalize(stats.weighted_pbr, 0.7, 2.5, true)) / 2,
            normalize(stats.weighted_roe, 0, 20),
            normalize(stats.weighted_yield, 0, 5),
            normalize(stats.weighted_years, 0, 10),
            normalize(stats.weighted_momentum, 0, 5),
            (normalize(stats.top5_ratio, 20, 60, true) + normalize(stats.hhi, 1000, 3000, true)) / 2,
            Math.min(100, (safeGet(stats, 'style_breakdown.safetyScore', 0) * (stats.hhi > 2500 ? 0.9 : 1.0)))
        ];

        const benchmarkScores = [
            (normalize(bm.valuation_per, 10, 40, true) + normalize(bm.valuation_pbr, 0.7, 2.5, true)) / 2,
            normalize(bm.profitability_roe, 0, 20),
            normalize(bm.income_yield, 0, 5),
            normalize(bm.quality_years, 0, 10),
            normalize(bm.momentum_score, 0, 5),
            (normalize(bm.diversification_top5, 20, 60, true) + normalize(bm.diversification_hhi, 1000, 3000, true)) / 2,
            bm.safety_score || 50
        ];

        radarChart = new Chart(ctx, {
            type: 'radar',
            data: {
                labels: config.labels,
                datasets: [
                    {
                        label: 'マイ・ポートフォリオ',
                        data: scores,
                        backgroundColor: 'rgba(78, 115, 223, 0.2)',
                        borderColor: '#4e73df',
                        pointBackgroundColor: '#4e73df',
                        pointBorderColor: '#fff',
                        pointHoverBackgroundColor: '#fff',
                        pointHoverBorderColor: '#4e73df',
                        borderWidth: 3
                    },
                    {
                        label: 'ベンチマーク (市場平均)',
                        data: benchmarkScores,
                        backgroundColor: 'transparent',
                        borderColor: '#858796',
                        borderDash: [5, 5],
                        pointRadius: 0,
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    r: {
                        min: 0,
                        max: 100,
                        beginAtZero: true,
                        ticks: { stepSize: 20, display: false },
                        grid: { color: colors.grid },
                        angleLines: { color: colors.grid },
                        pointLabels: { 
                            color: colors.text,
                            font: { size: 12, weight: 'bold' } 
                        }
                    }
                },
                plugins: {
                    legend: { 
                        position: 'bottom',
                        labels: { color: colors.text }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.dataset.label}: ${Math.round(context.raw)}点`,
                            footer: (context) => {
                                const item = context[0];
                                const descriptions = highlightRules?.radar_chart?.descriptions || {};
                                const desc = descriptions[item.label] || "";
                                if (desc.length > 30) {
                                    const lines = [];
                                    for (let i = 0; i < desc.length; i += 30) {
                                        lines.push(desc.substring(i, i + 30));
                                    }
                                    return "\n" + lines.join("\n");
                                }
                                return desc ? "\n" + desc : "";
                            }
                        }
                    }
                }
            }
        });
    }

    function calculateWeightedStats(holdings) {
        const totalMarketValue = holdings.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        if (totalMarketValue === 0) return null;

        const metrics = ['per', 'pbr', 'roe', 'yield', 'consecutive_increase_years', 'momentum'];
        const weightedSums = { per: 0, pbr: 0, roe: 0, yield: 0, consecutive_increase_years: 0, momentum: 0 };
        const weightsTotal = { per: 0, pbr: 0, roe: 0, yield: 0, consecutive_increase_years: 0, momentum: 0 };
        const assetMarketValues = {};

        holdings.forEach(item => {
            const mv = parseFloat(item.market_value) || 0;
            const code = item.code;
            if (mv > 0 && code) {
                assetMarketValues[code] = (assetMarketValues[code] || 0) + mv;
            }

            metrics.forEach(m => {
                let val = item[m];
                if (m === 'momentum' && item.score_details) {
                    const d = item.score_details;
                    val = (d.trend_short || 0) + (d.trend_medium || 0) + (d.trend_signal || 0) + (d.fibonacci || 0) + (d.rci || 0);
                }
                if (typeof val === 'string') {
                    val = parseFloat(val.replace(/,/g, '').replace('倍', '').replace('%', '').trim());
                }
                if (typeof val === 'number' && !isNaN(val) && isFinite(val) && mv > 0) {
                    weightedSums[m] += val * mv;
                    weightsTotal[m] += mv;
                }
            });
        });

        let hhi = 0;
        Object.values(assetMarketValues).forEach(mv => {
            const weightPct = (mv / totalMarketValue) * 100;
            hhi += weightPct * weightPct;
        });

        const sortedValues = Object.values(assetMarketValues).sort((a, b) => b - a);
        const top5Value = sortedValues.slice(0, 5).reduce((sum, v) => sum + v, 0);
        const top5Ratio = (top5Value / totalMarketValue) * 100;

        const styleBreakdown = calculateStyleBreakdown(holdings, totalMarketValue);
        const coverages = {};
        metrics.forEach(m => {
            coverages[m] = (weightsTotal[m] / totalMarketValue) * 100;
        });

        return {
            weighted_per: weightsTotal.per > 0 ? weightedSums.per / weightsTotal.per : null,
            weighted_pbr: weightsTotal.pbr > 0 ? weightedSums.pbr / weightsTotal.pbr : null,
            weighted_roe: weightsTotal.roe > 0 ? weightedSums.roe / weightsTotal.roe : null,
            weighted_yield: weightsTotal.yield > 0 ? weightedSums.yield / weightsTotal.yield : null,
            weighted_years: weightsTotal.consecutive_increase_years > 0 ? weightedSums.consecutive_increase_years / weightsTotal.consecutive_increase_years : null,
            weighted_momentum: weightsTotal.momentum > 0 ? weightedSums.momentum / weightsTotal.momentum : null,
            coverages: coverages,
            hhi: hhi,
            top5_ratio: top5Ratio,
            style_breakdown: styleBreakdown
        };
    }

    function calculateStyleBreakdown(holdings, totalMv) {
        if (totalMv <= 0) return null;

        const defensiveIndustries = ["食料品", "医薬品", "電気・ガス業", "陸運業", "情報・通信業"];
        const cyclicalIndustries = ["輸送用機器", "鉄鋼", "海運業", "卸売業", "鉱業", "機械", "化学", "非鉄金属", "ガラス・土石製品"];

        const breakdown = {
            cyclicality: { defensive: 0, cyclical: 0, other: 0 },
            style: { value: 0, growth: 0, blend: 0 },
            marketCap: { large: 0, midSmall: 0 }
        };
        let totalSafetyWeightedScore = 0;

        holdings.forEach(item => {
            const mv = parseFloat(item.market_value) || 0;
            if (mv <= 0) return;

            const industry = item.industry || "その他";
            if (defensiveIndustries.includes(industry)) breakdown.cyclicality.defensive += mv;
            else if (cyclicalIndustries.includes(industry)) breakdown.cyclicality.cyclical += mv;
            else breakdown.cyclicality.other += mv;

            let per = null, pbr = null, roe = null;
            const parseVal = (v) => {
                if (typeof v === 'string') return parseFloat(v.replace(/,/g, '').replace('倍', '').replace('%', '').trim());
                return (typeof v === 'number' && !isNaN(v)) ? v : null;
            };
            per = parseVal(item.per);
            pbr = parseVal(item.pbr);
            roe = parseVal(item.roe);

            if (per !== null && pbr !== null) {
                if (per < 15.0 && pbr < 1.0) breakdown.style.value += mv;
                else if (per > 25.0 || pbr > 2.5) breakdown.style.growth += mv;
                else breakdown.style.blend += mv;
            } else {
                breakdown.style.blend += mv;
            }

            let mcap = 0;
            const mcapVal = item.market_cap;
            if (typeof mcapVal === 'string') {
                const mcapStr = mcapVal.replace(/,/g, '');
                if (mcapStr.includes('兆')) mcap = parseFloat(mcapStr.split('兆')[0]) * 1000000000000;
                else if (mcapStr.includes('億')) mcap = parseFloat(mcapStr.split('億')[0]) * 100000000;
                else mcap = parseFloat(mcapStr);
            } else if (typeof mcapVal === 'number' && !isNaN(mcapVal)) {
                mcap = mcapVal;
            }
            if (mcap >= 1000000000000) breakdown.marketCap.large += mv;
            else breakdown.marketCap.midSmall += mv;

            let assetSafetyScore = 0;
            if (item.asset_type === 'investment_trust') assetSafetyScore = 100;
            else if (item.asset_type === 'us_stock') assetSafetyScore = 10;
            else if (item.asset_type === 'jp_stock') {
                let jpPoints = 0;
                if (defensiveIndustries.includes(industry)) jpPoints += 25;
                if (mcap >= 1000000000000) jpPoints += 25;
                else if (mcap >= 300000000000) jpPoints += 12.5;
                const incYears = parseInt(item.consecutive_increase_years || 0);
                if (incYears >= 3) jpPoints += 25;
                if (pbr !== null && pbr <= 1.2) jpPoints += 25;
                if (roe !== null && roe < 0) jpPoints *= 0.5;
                assetSafetyScore = jpPoints;
            }
            totalSafetyWeightedScore += assetSafetyScore * mv;
        });

        const toPct = (val) => (val / totalMv) * 100;
        return {
            cyclicality: {
                defensive: toPct(breakdown.cyclicality.defensive),
                cyclical: toPct(breakdown.cyclicality.cyclical),
                other: toPct(breakdown.cyclicality.other)
            },
            style: {
                value: toPct(breakdown.style.value),
                growth: toPct(breakdown.style.growth),
                blend: toPct(breakdown.style.blend)
            },
            marketCap: {
                large: toPct(breakdown.marketCap.large),
                midSmall: toPct(breakdown.marketCap.midSmall)
            },
            safetyScore: totalSafetyWeightedScore / totalMv
        };
    }

    function renderDNAAndRisk(stats) {
        const dnaContent = document.getElementById('dna-content');
        const riskContent = document.getElementById('risk-content');
        const personalityContent = document.getElementById('personality-content');

        if (!stats) {
            if (dnaContent) dnaContent.innerHTML = '<p>データがありません</p>';
            if (riskContent) riskContent.innerHTML = '<p>データがありません</p>';
            if (personalityContent) personalityContent.innerHTML = '<p>データがありません</p>';
            return;
        }

        const thresholds = highlightRules.radar_chart ? highlightRules.radar_chart.benchmarks : {};

        if (dnaContent) {
            if (allHoldingsData.length === 0 && !loadingIndicator.classList.contains('hidden')) return;

            const getColorClass = (val, threshold, type = 'lower_is_better') => {
                if (val === null || val === undefined) return '';
                if (type === 'lower_is_better') {
                    return val <= threshold ? 'profit' : (val <= threshold * 1.5 ? 'warning' : 'loss');
                } else {
                    return val >= threshold ? 'profit' : (val >= threshold * 0.7 ? 'warning' : 'loss');
                }
            };

            const perClass = getColorClass(stats.weighted_per, thresholds.valuation_per || 15.0, 'lower_is_better');
            const pbrClass = getColorClass(stats.weighted_pbr, thresholds.valuation_pbr || 1.2, 'lower_is_better');
            const roeClass = getColorClass(stats.weighted_roe, thresholds.profitability_roe || 9.0, 'higher_is_better');
            const yieldClass = getColorClass(stats.weighted_yield, thresholds.income_yield || 2.5, 'higher_is_better');

            const lowCoverageWarning = Object.entries(stats.coverages || {})
                .filter(([k, v]) => v < 70 && ['per', 'pbr', 'roe', 'yield'].includes(k))
                .map(([k, v]) => `${k.toUpperCase()}(${Math.round(v)}%)`)
                .join(', ');

            dnaContent.innerHTML = `
                <div class="dna-metrics">
                    <p title="利益に対して株価が割安かを示します（平均PER）">割安さ(利益): <span class="${perClass}">${formatNumber(stats.weighted_per, 2)}倍</span></p>
                    <p title="持っている資産に対して株価が割安かを示します（平均PBR）">割安さ(資産): <span class="${pbrClass}">${formatNumber(stats.weighted_pbr, 2)}倍</span></p>
                    <p title="預けたお金をどれだけ効率よく増やせているかを示します（平均ROE）">稼ぐ力(収益性): <span class="${roeClass}">${formatNumber(stats.weighted_roe, 2)}%</span></p>
                    <p title="投資額に対して、1年間でもらえる配当の割合です（平均配当利回り）">配当利回り: <span class="${yieldClass}">${formatNumber(stats.weighted_yield, 2)}%</span></p>
                </div>
                ${lowCoverageWarning ? `<div class="coverage-warning">⚠️ 一部の銘柄データが不明なため、上記数値は参考値です。(${lowCoverageWarning})</div>` : ''}
            `;
        }

        if (riskContent) {
            if (allHoldingsData.length === 0 && !loadingIndicator.classList.contains('hidden')) return;

            let hhiLevel = '分散良好';
            let hhiClass = 'profit';
            const hhiThreshold = thresholds.diversification_hhi || 1500;
            if (stats.hhi >= 2500) { hhiLevel = '集中リスクあり'; hhiClass = 'loss'; }
            else if (stats.hhi >= hhiThreshold) { hhiLevel = 'やや集中'; hhiClass = 'warning'; }
            const top5Threshold = thresholds.diversification_top5 || 40.0;
            const top5Class = stats.top5_ratio > top5Threshold ? 'warning' : 'profit';

            riskContent.innerHTML = `
                <div class="risk-metrics">
                    <p title="上位5つの銘柄で全体の何%を占めているか">銘柄の集中度(上位5選): <span class="${top5Class}">${formatNumber(stats.top5_ratio, 1)}%</span></p>
                    <p title="銘柄の分散具合を計算した数値(HHI)">カゴの分け具合: <span class="${hhiClass}">${hhiLevel} (${formatNumber(stats.hhi, 0)})</span></p>
                </div>
            `;
        }

        if (personalityContent) {
            if (allHoldingsData.length === 0 && !loadingIndicator.classList.contains('hidden')) return;

            const b = stats.style_breakdown;
            const cyclicalityLabel = b.cyclicality.defensive > b.cyclicality.cyclical ? '守りに強い' : '景気に敏感な';
            const styleLabel = b.style.value > b.style.growth ? '割安株中心' : '成長株中心';
            const capLabel = b.marketCap.large > 50 ? 'どっしりした大型株' : '身軽な中小型株';

            let advice = "";
            if (b.cyclicality.defensive > 60 && b.style.value > 50) advice = "不況に強く、割安な銘柄で固めた非常に堅実な構成です。";
            else if (b.style.growth > 50 && b.marketCap.midSmall > 50) advice = "将来の成長を期待する銘柄が多く、値動きが大きくなりやすい構成です。";
            else if (stats.hhi < 1000) advice = "非常に多くの銘柄に分散されており、リスクを抑えられています。";
            else if (stats.top5_ratio > 50) advice = "特定の一部の銘柄に資産が集中しています。注意が必要です。";
            else advice = "バランスの取れた構成です。";

            personalityContent.innerHTML = `
                <div class="personality-summary">
                    <strong>診断結果: ${capLabel}の${cyclicalityLabel}${styleLabel}</strong>
                    <div class="advice-box">${advice}</div>
                </div>
                <div class="personality-bars">
                    <div class="style-bar-group">
                        <div class="style-bar-label"><span>景気に敏感 ${formatNumber(b.cyclicality.cyclical, 0)}%</span><span>守りに強い ${formatNumber(b.cyclicality.defensive, 0)}%</span></div>
                        <div class="progress-stacked">
                            <div class="progress-bar cyclical" style="width: ${b.cyclicality.cyclical}%"></div>
                            <div class="progress-bar other" style="width: ${b.cyclicality.other}%"></div>
                            <div class="progress-bar defensive" style="width: ${b.cyclicality.defensive}%"></div>
                        </div>
                    </div>
                    <div class="style-bar-group">
                        <div class="style-bar-label"><span>割安(バリュー) ${formatNumber(b.style.value, 0)}%</span><span>成長(グロース) ${formatNumber(b.style.growth, 0)}%</span></div>
                        <div class="progress-stacked">
                            <div class="progress-bar value" style="width: ${b.style.value}%"></div>
                            <div class="progress-bar blend" style="width: ${b.style.blend}%"></div>
                            <div class="progress-bar growth" style="width: ${b.style.growth}%"></div>
                        </div>
                    </div>
                    <div class="style-bar-group">
                        <div class="style-bar-label"><span>大型株 ${formatNumber(b.marketCap.large, 0)}%</span><span>中小型株 ${formatNumber(b.marketCap.midSmall, 0)}%</span></div>
                        <div class="progress-stacked">
                            <div class="progress-bar large" style="width: ${b.marketCap.large}%"></div>
                            <div class="progress-bar midSmall" style="width: ${b.marketCap.midSmall}%"></div>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    function renderCharts(holdings) {
        if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) return;

        const industryBreakdown = {}, accountTypeBreakdown = {}, countryBreakdown = {}, securityCompanyBreakdown = {}, dividendIndustryBreakdown = {};
        holdings.forEach(item => {
            const marketValue = parseFloat(item.market_value) || 0;
            const annualDividend = parseFloat(item.estimated_annual_dividend) || 0;
            const industry = item.industry || 'その他';
            if (marketValue > 0) {
                industryBreakdown[industry] = (industryBreakdown[industry] || 0) + marketValue;
                const accountType = item.account_type || '不明';
                accountTypeBreakdown[accountType] = (accountTypeBreakdown[accountType] || 0) + marketValue;
                const securityCompany = item.security_company || '-';
                securityCompanyBreakdown[securityCompany] = (securityCompanyBreakdown[securityCompany] || 0) + marketValue;
                let country = item.asset_type === 'jp_stock' ? '日本' : (item.asset_type === 'us_stock' ? '米国' : '投資信託');
                countryBreakdown[country] = (countryBreakdown[country] || 0) + marketValue;
            }
            if (annualDividend > 0) dividendIndustryBreakdown[industry] = (dividendIndustryBreakdown[industry] || 0) + annualDividend;
        });

        const colors = getChartThemeColors();
        const chartOptions = {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right', labels: { color: colors.text } },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label || ''; if (label) label += ': ';
                            const total = context.dataset.data.reduce((sum, val) => sum + val, 0);
                            const percentage = total > 0 ? (context.raw / total * 100) : 0;
                            const formattedAmount = isAmountVisible ? `${formatNumber(context.raw, 0)}円` : `***円`;
                            return `${label}${formattedAmount} (${percentage.toFixed(2)}%)`;
                        }
                    }
                }
            }
        };

        const getChartData = (breakdown) => ({
            labels: Object.keys(breakdown),
            datasets: [{ data: Object.values(breakdown), backgroundColor: generateColors(Object.keys(breakdown).length), hoverOffset: 4 }]
        });

        const canvasList = {
            'industry-chart': industryBreakdown,
            'account-type-chart': accountTypeBreakdown,
            'security-company-chart': securityCompanyBreakdown,
            'country-chart': countryBreakdown,
            'dividend-industry-chart': dividendIndustryBreakdown
        };

        Object.entries(canvasList).forEach(([id, data]) => {
            const canvas = document.getElementById(id);
            if (canvas && Object.keys(data).length > 0) {
                const existing = Chart.getChart(canvas); if (existing) existing.destroy();
                new Chart(canvas, { type: 'pie', data: getChartData(data), options: chartOptions });
            }
        });
        
        renderMonthlyDividendChart(holdings);
        const activeBtn = document.querySelector('.chart-toggle-btn.active');
        updateChart(activeBtn ? activeBtn.dataset.chartType : 'industry');
    }

    function renderMonthlyDividendChart(holdings) {
        if (holdings.length === 0 && !loadingIndicator.classList.contains('hidden')) return;

        const monthlyData = new Array(12).fill(0);
        const months = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];

        holdings.forEach(item => {
            const annualDiv = parseFloat(item.estimated_annual_dividend) || 0;
            if (annualDiv <= 0) return;
            let baseMonth = null;
            if (item.settlement_month && typeof item.settlement_month === 'string') {
                const match = item.settlement_month.match(/(\d+)/); if (match) baseMonth = parseInt(match[1]);
            }
            if (baseMonth === null) return;
            const getMonthIdx = (m, shift) => (m + shift - 1) % 12;
            if (item.asset_type === 'jp_stock') {
                monthlyData[getMonthIdx(baseMonth, 3)] += annualDiv / 2; monthlyData[getMonthIdx(baseMonth, 9)] += annualDiv / 2;
            } else if (item.asset_type === 'us_stock') {
                for (let i=3; i<=12; i+=3) monthlyData[getMonthIdx(baseMonth, i)] += annualDiv / 4;
            } else monthlyData[getMonthIdx(baseMonth, 3)] += annualDiv;
        });

        const canvas = document.getElementById('monthly-dividend-chart');
        if (!canvas) return;
        const existingChart = Chart.getChart(canvas); if (existingChart) existingChart.destroy();
        const ctx = canvas.getContext('2d');
        const colors = getChartThemeColors();

        monthlyDividendChart = new Chart(ctx, {
            type: 'bar',
            data: { labels: months, datasets: [{ label: '予想受取額', data: monthlyData, backgroundColor: '#1cc88a', borderRadius: 4 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { labels: { color: colors.text } }, tooltip: { callbacks: { label: (context) => {
                    const formattedValue = isAmountVisible ? formatNumber(context.raw, 0) + '円' : '***円';
                    return (context.dataset.label || '') + ': ' + formattedValue;
                }}}},
                scales: {
                    x: { grid: { color: colors.grid }, ticks: { color: colors.muted } },
                    y: { beginAtZero: true, grid: { color: colors.grid }, ticks: { color: colors.muted, callback: (v) => isAmountVisible ? formatNumber(v, 0) + '円' : '***円' } }
                }
            }
        });
    }

    function updateChart(chartType) {
        document.querySelectorAll('.portfolio-chart .chart-container canvas').forEach(canvas => canvas.classList.add('hidden'));
        document.querySelectorAll('.chart-toggle-btn').forEach(btn => btn.classList.remove('active'));
        const activeBtn = document.querySelector(`.chart-toggle-btn[data-chart-type="${chartType}"]`);
        if (activeBtn) activeBtn.classList.add('active');
        const chartCanvas = document.getElementById(`${chartType}-chart`);
        if (chartCanvas) chartCanvas.classList.remove('hidden');
    }

    const formatNumber = (num, fractionDigits = 0) => {
        const parsedNum = parseFloat(num);
        if (isNaN(parsedNum)) return 'N/A';
        return parsedNum.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
    };

    function showAlert(message, type = 'danger') {
        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.textContent = message;
        alertContainer.appendChild(alert);
        requestAnimationFrame(() => alert.classList.add('show'));
        setTimeout(() => {
            alert.classList.remove('show'); alert.classList.add('hide');
            alert.addEventListener('transitionend', () => alert.remove());
        }, 5000);
    }

    function sortHoldings(data) {
        data.sort((a, b) => {
            let valA = a[currentSort.key], valB = b[currentSort.key];
            const parseValue = (v) => {
                if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '') return -Infinity;
                if (typeof v === 'object' && v !== null && v.retracement !== undefined) return v.retracement;
                if (typeof v === 'string') { const num = parseFloat(v.replace(/,/g, '')); return isNaN(num) ? v : num; }
                return v;
            };
            const parsedA = parseValue(valA), parsedB = parseValue(valB);
            if (typeof parsedA === 'number' && typeof parsedB === 'number') return currentSort.order === 'asc' ? parsedA - parsedB : parsedB - parsedA;
            return currentSort.order === 'asc' ? String(parsedA).localeCompare(String(parsedB)) : String(parsedB).localeCompare(String(parsedA));
        });
    }

    function updateSortHeaders() {
        document.querySelectorAll('#analysis-table .sortable').forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) header.classList.add('sort-active', `sort-${currentSort.order}`);
        });
    }

    function populateFilters() {
        const industries = [...new Set(allHoldingsData.map(item => item.industry || 'N/A'))].sort();
        industryFilterSelect.innerHTML = '<option value="">すべての業種</option>' + industries.map(ind => `<option value="${ind}">${ind}</option>`).join('');
        const accountTypes = [...new Set(allHoldingsData.map(item => item.account_type || 'N/A'))].sort();
        accountTypeFilterSelect.innerHTML = '<option value="">すべての口座種別</option>' + accountTypes.map(acc => `<option value="${acc}">${acc}</option>`).join('');
        const securityCompanies = [...new Set(allHoldingsData.map(item => item.security_company || '-'))].sort();
        securityCompanyFilterSelect.innerHTML = '<option value="">すべての証券会社</option>' + securityCompanies.map(sc => `<option value="${sc}">${sc}</option>`).join('');
    }

    function generateColors(numColors) {
        const baseColors = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796', '#5a5c69', '#6f42c1', '#fd7e14'];
        return Array.from({length: numColors}, (_, i) => baseColors[i % baseColors.length]);
    }

    analysisFilterInput.addEventListener('input', filterAndRender);
    industryFilterSelect.addEventListener('change', filterAndRender);
    accountTypeFilterSelect.addEventListener('change', filterAndRender);
    securityCompanyFilterSelect.addEventListener('change', filterAndRender);
    buySignalFilterSelect.addEventListener('change', filterAndRender);
    document.querySelector('#analysis-table thead').addEventListener('click', (event) => {
        const header = event.target.closest('.sortable'); if (!header) return;
        const key = header.dataset.key;
        if (currentSort.key === key) currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
        else { currentSort.key = key; currentSort.order = 'asc'; }
        filterAndRender();
    });
    toggleVisibilityCheckbox.addEventListener('change', (event) => {
        isAmountVisible = !event.target.checked;
        renderAnalysisTable(filteredHoldingsData);
        renderSummary(filteredHoldingsData);
        renderCharts(filteredHoldingsData);
        fetchAndRenderHistoryData();
    });
    downloadAnalysisCsvButton.addEventListener('click', () => { window.location.href = '/api/portfolio/analysis/csv'; });
    chartToggleBtns.forEach(btn => btn.addEventListener('click', () => updateChart(btn.dataset.chartType)));

    window.addEventListener('pagehide', () => { if (fetchController) fetchController.abort(); });

    function renderBuySignalBadge(signal, isDiamond = false) {
        if (!signal) return '';
        const reasons = signal.reasons.join('\n');
        const level = signal.level !== undefined ? signal.level : 1;
        const levelClass = `buy-signal-level-${level}`;
        const diamondClass = isDiamond ? 'buy-signal-diamond' : '';
        const isLongAdjustment = signal.label.includes('長期調整');
        let strengthClass = '';
        if (level >= 1) {
            if (isDiamond && level === 2 && isLongAdjustment) strengthClass = 'signal-strength-rainbow';
            else if (isDiamond && level === 2) strengthClass = 'signal-strength-gold';
            else if ((level === 2 && isLongAdjustment) || (isDiamond && level === 1 && isLongAdjustment)) strengthClass = 'signal-strength-silver';
        }
        let titleText = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${reasons}`;
        return `<span class="buy-signal-badge ${levelClass} ${diamondClass} ${strengthClass}" title="${titleText}"><span class="buy-signal-icon-inner">${signal.icon}</span>${signal.label}</span>`;
    }
    function renderSellSignalBadge(signal, isDiamond = false) {
        if (!signal) return '';
        const reasons = signal.reasons.join('\n');
        const levelClass = `sell-signal-level-${signal.level}`;
        const diamondClass = isDiamond ? 'buy-signal-diamond' : '';
        let titleText = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${reasons}`;
        return `<span class="sell-signal-badge ${levelClass} ${diamondClass}" title="${titleText}"><span class="buy-signal-icon-inner">${signal.icon}</span>${signal.label}</span>`;
    }

    fetchHighlightRules();
    fetchAndRenderAnalysisData();
});
