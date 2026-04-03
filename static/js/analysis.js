// static/js/analysis.js

document.addEventListener('DOMContentLoaded', () => {
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

    // --- Chart.jsインスタンス ---
    let industryChart, accountTypeChart, countryChart, securityCompanyChart, dividendIndustryChart;
    let assetHistoryChart, dividendHistoryChart, monthlyDividendChart, radarChart;

    // --- グローバル変数 ---
    let allHoldingsData = [];
    let fullAnalysisData = {};
    let highlightRules = null;
    let filteredHoldingsData = [];
    let currentSort = { key: 'market_value', order: 'desc' };
    let isAmountVisible = true;
    let fetchController = null; // AbortControllerを保持

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
            // 429 (Too Many Requests) の場合は、バックエンドのスマートキャッシュによる一時的な制限の可能性があるため、
            // 警告は出さずに既存のキャッシュ表示を維持する（既に processAnalysisData 済み）
            if (error instanceof window.appState.HttpError && error.status === 429) {
                console.log('Backend is currently throttling or updating. Using cached data.');
            } else if (!cachedData) {
                showAlert(`分析データの取得に失敗しました。(${error.message})`, 'danger');
            }
            loadingIndicator.classList.add('hidden');
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
                if (val === '--' || val === 'N/A') return '--';
                if (typeof val === 'number') {
                    const sign = val > 0 ? '+' : '';
                    return `${sign}${val.toFixed(2)}%`;
                }
                return `${val}%`;
            };

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
                                <span class="${getChangeClass(change)}">${change} (${formatPercent(changePercent)})</span>
                            </div>
                            <div class="market-index-row">
                                <span class="change-label">前週比:</span>
                                <span class="${getChangeClass(wow)}">${formatPercent(wow)}</span>
                            </div>
                            <div class="market-index-row">
                                <span class="change-label">前月比:</span>
                                <span class="${getChangeClass(mom)}">${formatPercent(mom)}</span>
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

        const labels = historyData.map(d => d.snapshot_month);
        const marketValues = historyData.map(d => d.total_market_value);
        const profitLosses = historyData.map(d => d.total_profit_loss);
        const originalInvestments = marketValues.map((mv, i) => mv - profitLosses[i]);
        const dividends = historyData.map(d => d.total_dividend);

        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
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
                y: {
                    beginAtZero: true,
                    ticks: {
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
            if (assetHistoryChart) assetHistoryChart.destroy();
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
            if (dividendHistoryChart) dividendHistoryChart.destroy();
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

        // 防衛的処理: 
        // 1. analysisData 自体が {"data": { holdings_list: ... }, "metadata": ...} のようにラップされている場合
        // 2. analysisData 直下に holdings_list がある場合
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
        analysisTableBody.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            if (loadingIndicator.classList.contains('hidden')) {
                analysisTableBody.innerHTML = `<tr><td colspan="16" style="text-align:center;">該当する保有銘柄はありません。</td></tr>`;
            }
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
            let nameHtml = item.name;
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
        // フィルタ適用時は不正確になるため、全データ(allHoldingsData)の合計値を基準にする。
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

        // フィルタ適用中かどうかの判定
        const isFiltered = holdings.length !== allHoldingsData.length;
        const momSuffixMV = !isFiltered ? formatDiff(calcDiff(currentTotalMV, prev ? prev.total_market_value : 0)) : '';
        const momSuffixPL = !isFiltered ? formatDiff(calcDiff(currentTotalPL, prev ? prev.total_profit_loss : 0)) : '';
        const momSuffixDiv = !isFiltered ? formatDiff(calcDiff(currentTotalDiv, prev ? prev.total_dividend : 0)) : '';

        // --- サマリー表示の更新 ---
        const summaryContent = document.getElementById('summary-content');
        if (summaryContent) {
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

        // --- ポートフォリオDNAとリスク分析の計算と表示 ---
        const stats = calculateWeightedStats(holdings);
        renderDNAAndRisk(stats);
        renderRadarChart(stats);
    }

    function renderRadarChart(stats) {
        if (!stats || !highlightRules || !highlightRules.radar_chart) return;

        const canvas = document.getElementById('radar-chart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (radarChart) radarChart.destroy();

        const config = highlightRules.radar_chart;
        const bm = config.benchmarks;

        // 正規化ロジック (0-100点)
        const normalize = (val, min, max, reverse = false) => {
            if (val === null || val === undefined) return 0;
            let score = ((val - min) / (max - min)) * 100;
            if (reverse) score = 100 - score;
            return Math.min(Math.max(score, 0), 100);
        };

        const safeGet = (obj, path, def = 0) => {
            return path.split('.').reduce((acc, part) => acc && acc[part], obj) || def;
        };

        // 各軸のスコアリング (7軸)
        const scores = [
            // 1. 割安性 (PER + PBR の平均)
            (normalize(stats.weighted_per, 10, 40, true) + normalize(stats.weighted_pbr, 0.7, 2.5, true)) / 2,
            // 2. 収益性 (ROE 20%以上で100点)
            normalize(stats.weighted_roe, 0, 20),
            // 3. インカム (利回り 5%以上で100点)
            normalize(stats.weighted_yield, 0, 5),
            // 4. クオリティ (増配10年以上で100点)
            normalize(stats.weighted_years, 0, 10),
            // 5. モメンタム (トレンド星数: 5個で100点)
            normalize(stats.weighted_momentum, 0, 5),
            // 6. 分散度 (Top5占有率 + HHI の平均)
            (normalize(stats.top5_ratio, 20, 60, true) + normalize(stats.hhi, 1000, 3000, true)) / 2,
            // 7. 安全性 (統合スコア × 分散ペナルティ)
            Math.min(100, (safeGet(stats, 'style_breakdown.safetyScore', 0) * (stats.hhi > 2500 ? 0.9 : 1.0)))
        ];

        // ベンチマーク（市場平均）のスコアリング
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
                        grid: { color: '#e3e6f0' },
                        angleLines: { color: '#e3e6f0' },
                        pointLabels: { font: { size: 12, weight: 'bold' } }
                    }
                },
                plugins: {
                    legend: { position: 'bottom' },
                    tooltip: {
                        callbacks: {
                            label: (context) => `${context.dataset.label}: ${Math.round(context.raw)}点`
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
                
                // モメンタム（テクニカル星数）の集計
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

        // HHI
        let hhi = 0;
        Object.values(assetMarketValues).forEach(mv => {
            const weightPct = (mv / totalMarketValue) * 100;
            hhi += weightPct * weightPct;
        });

        // Top 5
        const sortedValues = Object.values(assetMarketValues).sort((a, b) => b - a);
        const top5Value = sortedValues.slice(0, 5).reduce((sum, v) => sum + v, 0);
        const top5Ratio = (top5Value / totalMarketValue) * 100;

        // スタイル分析の計算
        const styleBreakdown = calculateStyleBreakdown(holdings, totalMarketValue);

        return {
            weighted_per: weightsTotal.per > 0 ? weightedSums.per / weightsTotal.per : null,
            weighted_pbr: weightsTotal.pbr > 0 ? weightedSums.pbr / weightsTotal.pbr : null,
            weighted_roe: weightsTotal.roe > 0 ? weightedSums.roe / weightsTotal.roe : null,
            weighted_yield: weightsTotal.yield > 0 ? weightedSums.yield / weightsTotal.yield : null,
            weighted_years: weightsTotal.consecutive_increase_years > 0 ? weightedSums.consecutive_increase_years / weightsTotal.consecutive_increase_years : null,
            weighted_momentum: weightsTotal.momentum > 0 ? weightedSums.momentum / weightsTotal.momentum : null,
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

            // --- 1. 景気特性 ---
            const industry = item.industry || "その他";
            if (defensiveIndustries.includes(industry)) breakdown.cyclicality.defensive += mv;
            else if (cyclicalIndustries.includes(industry)) breakdown.cyclicality.cyclical += mv;
            else breakdown.cyclicality.other += mv;

            // --- 2. バリュー/グロース ---
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

            // --- 3. 時価総額区分 (大型: 1兆円以上) ---
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

            // --- 4. 安全性スコアの計算 (統合版ロジック) ---
            let assetSafetyScore = 0;
            if (item.asset_type === 'investment_trust') {
                // 投資信託（インデックス等）は高い安全性を付与
                assetSafetyScore = 100;
            } else if (item.asset_type === 'us_stock') {
                // 米国個別株はユーザーポリシーによりリスク資産（10点）として扱う
                assetSafetyScore = 10;
            } else if (item.asset_type === 'jp_stock') {
                // 国内個別株は多角的に判定
                let jpPoints = 0;
                if (defensiveIndustries.includes(industry)) jpPoints += 25; // 業種
                if (mcap >= 1000000000000) jpPoints += 25; // 大型
                else if (mcap >= 300000000000) jpPoints += 12.5; // 中堅も半分評価
                
                const incYears = parseInt(item.consecutive_increase_years || 0);
                if (incYears >= 3) jpPoints += 25; // 連続増配

                if (pbr !== null && pbr <= 1.2) jpPoints += 25; // 低PBR（資産の安全性）

                // 収益性補正（赤字ならスコア半減）
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

        if (dnaContent) {
            dnaContent.innerHTML = `
                <p title="時価評価額で加重平均したPERです">平均PER: <span>${formatNumber(stats.weighted_per, 2)}倍</span></p>
                <p title="時価評価額で加重平均したPBRです">平均PBR: <span>${formatNumber(stats.weighted_pbr, 2)}倍</span></p>
                <p title="時価評価額で加重平均したROEです">平均ROE: <span>${formatNumber(stats.weighted_roe, 2)}%</span></p>
                <p title="ポートフォリオ全体の時価に対する予想配当利回りです">平均利回り: <span>${formatNumber(stats.weighted_yield, 2)}%</span></p>
            `;
        }

        if (riskContent) {
            let hhiLevel = '良好';
            let hhiClass = 'profit';
            if (stats.hhi >= 2500) {
                hhiLevel = '集中リスクあり';
                hhiClass = 'loss';
            } else if (stats.hhi >= 1500) {
                hhiLevel = 'やや集中';
                hhiClass = '';
            }

            riskContent.innerHTML = `
                <p title="上位5銘柄が占める割合です。40%を超えると集中度が高めです。">上位5銘柄占有率: <span>${formatNumber(stats.top5_ratio, 2)}%</span></p>
                <p title="銘柄の集中度を計る指標(HHI)。1,500未満が分散良好、2,500以上が集中リスクの目安です。">
                    分散度(HHI): <span class="${hhiClass}">${formatNumber(stats.hhi, 0)} (${hhiLevel})</span>
                </p>
            `;
        }

        if (personalityContent) {
            const b = stats.style_breakdown;
            const cyclicalityLabel = b.cyclicality.defensive > b.cyclicality.cyclical ? 'ディフェンシブ寄り' : '景気敏感寄り';
            const styleLabel = b.style.value > b.style.growth ? 'バリュー寄り' : 'グロース寄り';
            const capLabel = b.marketCap.large > 50 ? '大型株中心' : '中小型株中心';

            personalityContent.innerHTML = `
                <div class="personality-summary">
                    <strong>診断結果: ${capLabel}の${cyclicalityLabel}${styleLabel}</strong>
                </div>
                <div class="personality-bars">
                    <div class="style-bar-group">
                        <div class="style-bar-label"><span>景気敏感 ${formatNumber(b.cyclicality.cyclical, 0)}%</span><span>ディフェンシブ ${formatNumber(b.cyclicality.defensive, 0)}%</span></div>
                        <div class="progress-stacked">
                            <div class="progress-bar cyclical" style="width: ${b.cyclicality.cyclical}%"></div>
                            <div class="progress-bar other" style="width: ${b.cyclicality.other}%"></div>
                            <div class="progress-bar defensive" style="width: ${b.cyclicality.defensive}%"></div>
                        </div>
                    </div>
                    <div class="style-bar-group">
                        <div class="style-bar-label"><span>バリュー ${formatNumber(b.style.value, 0)}%</span><span>グロース ${formatNumber(b.style.growth, 0)}%</span></div>
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
                let country = 'その他';
                if (item.asset_type === 'jp_stock') country = '日本';
                else if (item.asset_type === 'us_stock') country = '米国';
                else if (item.asset_type === 'investment_trust') country = '投資信託';
                countryBreakdown[country] = (countryBreakdown[country] || 0) + marketValue;
            }

            if (annualDividend > 0) {
                dividendIndustryBreakdown[industry] = (dividendIndustryBreakdown[industry] || 0) + annualDividend;
            }
        });

        const chartOptions = {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label || '';
                            if (label) label += ': ';
                            const total = context.dataset.data.reduce((sum, val) => sum + val, 0);
                            const percentage = total > 0 ? (context.raw / total * 100) : 0;
                            const unit = '円';
                            const formattedAmount = isAmountVisible ? `${formatNumber(context.raw, 0)}${unit}` : `***${unit}`;
                            label += `${formattedAmount} (${percentage.toFixed(2)}%)`;
                            return label;
                        }
                    }
                }
            }
        };

        const getChartData = (breakdown) => ({
            labels: Object.keys(breakdown),
            datasets: [{ data: Object.values(breakdown), backgroundColor: generateColors(Object.keys(breakdown).length), hoverOffset: 4 }]
        });

        if (industryChart) industryChart.destroy();
        if (Object.keys(industryBreakdown).length > 0) {
            const canvas = document.getElementById('industry-chart');
            if (canvas) industryChart = new Chart(canvas, { type: 'pie', data: getChartData(industryBreakdown), options: chartOptions });
        }

        if (accountTypeChart) accountTypeChart.destroy();
        if (Object.keys(accountTypeBreakdown).length > 0) {
            const canvas = document.getElementById('account-type-chart');
            if (canvas) accountTypeChart = new Chart(canvas, { type: 'pie', data: getChartData(accountTypeBreakdown), options: chartOptions });
        }

        if (securityCompanyChart) securityCompanyChart.destroy();
        if (Object.keys(securityCompanyBreakdown).length > 0) {
            const canvas = document.getElementById('security-company-chart');
            if (canvas) securityCompanyChart = new Chart(canvas, { type: 'pie', data: getChartData(securityCompanyBreakdown), options: chartOptions });
        }

        if (countryChart) countryChart.destroy();
        if (Object.keys(countryBreakdown).length > 0) {
            const canvas = document.getElementById('country-chart');
            if (canvas) countryChart = new Chart(canvas, { type: 'pie', data: getChartData(countryBreakdown), options: chartOptions });
        }

        if (dividendIndustryChart) dividendIndustryChart.destroy();
        if (Object.keys(dividendIndustryBreakdown).length > 0) {
            const canvas = document.getElementById('dividend-industry-chart');
            if (canvas) dividendIndustryChart = new Chart(canvas, { type: 'pie', data: getChartData(dividendIndustryBreakdown), options: chartOptions });
        }
        
        // 月別配当分布グラフの描画
        renderMonthlyDividendChart(holdings);

        const activeBtn = document.querySelector('.chart-toggle-btn.active');
        updateChart(activeBtn ? activeBtn.dataset.chartType : 'industry');
    }

    function renderMonthlyDividendChart(holdings) {
        const monthlyData = new Array(12).fill(0);
        const months = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"];

        holdings.forEach(item => {
            const annualDiv = parseFloat(item.estimated_annual_dividend) || 0;
            if (annualDiv <= 0) return;

            // 決算月の取得 (数値化)
            let baseMonth = null;
            if (item.settlement_month && typeof item.settlement_month === 'string') {
                const match = item.settlement_month.match(/(\d+)/);
                if (match) baseMonth = parseInt(match[1]);
            }

            if (baseMonth === null) return;

            // 月を配列のインデックス(0-11)に変換するためのヘルパー
            const getMonthIdx = (m, shift) => (m + shift - 1) % 12;

            if (item.asset_type === 'jp_stock') {
                // 国内株: 3ヶ月後(期末) と 9ヶ月後(中間) に 50% ずつ
                monthlyData[getMonthIdx(baseMonth, 3)] += annualDiv / 2;
                monthlyData[getMonthIdx(baseMonth, 9)] += annualDiv / 2;
            } else if (item.asset_type === 'us_stock') {
                // 米国株: 3ヶ月おきに 25% ずつ
                monthlyData[getMonthIdx(baseMonth, 3)] += annualDiv / 4;
                monthlyData[getMonthIdx(baseMonth, 6)] += annualDiv / 4;
                monthlyData[getMonthIdx(baseMonth, 9)] += annualDiv / 4;
                monthlyData[getMonthIdx(baseMonth, 12)] += annualDiv / 4;
            } else {
                // その他: 3ヶ月後に 100% (暫定)
                monthlyData[getMonthIdx(baseMonth, 3)] += annualDiv;
            }
        });

        const canvas = document.getElementById('monthly-dividend-chart');
        if (!canvas) return;

        if (monthlyDividendChart) monthlyDividendChart.destroy();
        const ctx = canvas.getContext('2d');

        monthlyDividendChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: months,
                datasets: [{
                    label: '予想受取額',
                    data: monthlyData,
                    backgroundColor: '#1cc88a',
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    tooltip: {
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
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return isAmountVisible ? formatNumber(value, 0) + '円' : '***円';
                            }
                        }
                    }
                }
            }
        });
    }

    function updateChart(chartType) {
        // ポートフォリオ構成セクション内のキャンバスのみを対象にする
        document.querySelectorAll('.portfolio-chart .chart-container canvas').forEach(canvas => {
            canvas.classList.add('hidden');
        });
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
            alert.classList.remove('show');
            alert.classList.add('hide');
            alert.addEventListener('transitionend', () => alert.remove());
        }, 5000);
    }

    function sortHoldings(data) {
        data.sort((a, b) => {
            let valA = a[currentSort.key], valB = b[currentSort.key];
            const parseValue = (v) => {
                if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '') return -Infinity;
                // フィボナッチなどのオブジェクト対応
                if (typeof v === 'object' && v !== null && v.retracement !== undefined) {
                    return v.retracement;
                }
                if (typeof v === 'string') {
                    const num = parseFloat(v.replace(/,/g, ''));
                    return isNaN(num) ? v : num;
                }
                return v;
            };
            const parsedA = parseValue(valA), parsedB = parseValue(valB);
            if (typeof parsedA === 'number' && typeof parsedB === 'number') {
                return currentSort.order === 'asc' ? parsedA - parsedB : parsedB - parsedA;
            }
            return currentSort.order === 'asc' ? String(parsedA).localeCompare(String(parsedB)) : String(parsedB).localeCompare(String(parsedA));
        });
    }

    function updateSortHeaders() {
        document.querySelectorAll('#analysis-table .sortable').forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) {
                header.classList.add('sort-active', `sort-${currentSort.order}`);
            }
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
        const header = event.target.closest('.sortable');
        if (!header) return;
        const key = header.dataset.key;
        if (currentSort.key === key) {
            currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
        } else {
            currentSort.key = key;
            currentSort.order = 'asc';
        }
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
    chartToggleBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            updateChart(btn.dataset.chartType);
        });
    });

    window.addEventListener('pagehide', () => {
        if (fetchController) fetchController.abort();
    });

    function renderBuySignalBadge(signal, isDiamond = false) {
        if (!signal) return '';
        const reasons = signal.reasons.join('\n');
        const level = signal.level !== undefined ? signal.level : 1;
        const levelClass = `buy-signal-level-${level}`;
        const diamondClass = isDiamond ? 'buy-signal-diamond' : '';
        const isLongAdjustment = signal.label.includes('長期調整');

        // シグナル強度の判定 (Level 1, 2のみ)
        let strengthClass = '';
        if (level >= 1) {
            if (isDiamond && level === 2 && isLongAdjustment) {
                strengthClass = 'signal-strength-rainbow';
            } else if (isDiamond && level === 2) {
                strengthClass = 'signal-strength-gold';
            } else if ((level === 2 && isLongAdjustment) || (isDiamond && level === 1 && isLongAdjustment)) {
                strengthClass = 'signal-strength-silver';
            }
        }

        // ツールチップの構築
        let titleText = '';
        if (signal.recommended_action) {
            titleText += `【推奨アクション】\n${signal.recommended_action}\n\n`;
        }
        if (signal.current_status) {
            titleText += `【現在の状態】\n${signal.current_status}\n\n`;
        }
        titleText += `【判定理由】\n${reasons}`;

        return `
            <span class="buy-signal-badge ${levelClass} ${diamondClass} ${strengthClass}" title="${titleText}">
                <span class="buy-signal-icon-inner">${signal.icon}</span>
                ${signal.label}
            </span>
        `;
    }
    function renderSellSignalBadge(signal, isDiamond = false) {
        if (!signal) return '';
        const reasons = signal.reasons.join('\n');
        const levelClass = `sell-signal-level-${signal.level}`;
        const diamondClass = isDiamond ? 'buy-signal-diamond' : '';

        // ツールチップの構築
        let titleText = '';
        if (signal.recommended_action) {
            titleText += `【推奨アクション】\n${signal.recommended_action}\n\n`;
        }
        if (signal.current_status) {
            titleText += `【現在の状態】\n${signal.current_status}\n\n`;
        }
        titleText += `【判定理由】\n${reasons}`;

        return `
            <span class="sell-signal-badge ${levelClass} ${diamondClass}" title="${titleText}">
                <span class="buy-signal-icon-inner">${signal.icon}</span>
                ${signal.label}
            </span>
        `;
    }

    fetchHighlightRules();
    fetchAndRenderAnalysisData();
});
