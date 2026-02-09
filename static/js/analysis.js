// カスタムエラー
class HttpError extends Error {
    constructor(message, status) {
        super(message);
        this.name = 'HttpError';
        this.status = status;
    }
}

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
    const downloadAnalysisCsvButton = document.getElementById('download-analysis-csv-button');
    const chartToggleBtns = document.querySelectorAll('.chart-toggle-btn');
    const loadingIndicator = document.getElementById('loading-indicator');

    // --- Chart.jsインスタンス ---
    let industryChart, accountTypeChart, countryChart, securityCompanyChart, dividendIndustryChart;
    let assetHistoryChart, dividendHistoryChart;

    // --- グローバル変数 ---
    let allHoldingsData = [];
    let fullAnalysisData = {};
    let filteredHoldingsData = [];
    let currentSort = { key: 'market_value', order: 'desc' };
    let isAmountVisible = true;
    let retryTimer = null;
    let fetchController = null; // AbortControllerを保持

    // --- データ取得とレンダリング (最終修正) ---
    async function fetchAndRenderAnalysisData() {
        if (retryTimer) {
        clearInterval(retryTimer);
        retryTimer = null;
    }
        if (fetchController) {
            fetchController.abort(); // 既存のリクエストをキャンセル
        }
        fetchController = new AbortController();
        const signal = fetchController.signal;

        const cachedData = window.appState.getState('analysis');
        if (cachedData) {
            processAnalysisData(cachedData);
            fetchAndRenderHistoryData();
        }

        if (!window.appState.canFetch()) {
            const remainingTime = window.appState.getCooldownRemainingTime();
            if (remainingTime > 0) {
                scheduleRetry(remainingTime, cachedData);
            }
            return;
        }

        try {
            loadingIndicator.innerHTML = cachedData ? '最新データを取得中...' : 'データを取得中...';
            loadingIndicator.classList.remove('hidden');

            const response = await fetch('/api/portfolio/analysis', { signal });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ detail: response.statusText }));
                throw new HttpError(errorData.detail || `HTTP error! status: ${response.status}`, response.status);
            }

            const analysisData = await response.json();
            window.appState.updateState('analysis', analysisData);
            window.appState.updateTimestamp();
            processAnalysisData(analysisData);
            loadingIndicator.classList.add('hidden');

            // メインデータの更新が終わったら履歴データも取得
            fetchAndRenderHistoryData();

        } catch (error) {
            if (error.name === 'AbortError') {
                return;
            }
            
            if (error instanceof HttpError && error.status === 429) {
                const remainingTime = window.appState.getCooldownRemainingTime() || 10000;
                scheduleRetry(remainingTime, cachedData);
            } else {
                console.error('Analysis fetch error:', error);
                if (!cachedData) {
                    showAlert(`分析データの取得に失敗しました。(${error.message})`, 'danger');
                }
                loadingIndicator.classList.add('hidden');
            }
        }
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

    function scheduleRetry(delay, cachedData) {
    if (retryTimer) {
        clearInterval(retryTimer);
    }

    let remainingSeconds = Math.ceil(delay / 1000);

    if (!cachedData) {
        loadingIndicator.innerHTML = `データ更新中です... (あと ${remainingSeconds} 秒)`;
        loadingIndicator.classList.remove('hidden');
    }

    retryTimer = setInterval(() => {
        remainingSeconds--;
        if (remainingSeconds >= 0 && !cachedData) {
            loadingIndicator.innerHTML = `データ更新中です... (あと ${remainingSeconds} 秒)`;
        }
        
        if (remainingSeconds < 0) {
            clearInterval(retryTimer);
            retryTimer = null;
            setTimeout(() => fetchAndRenderAnalysisData(), 200);
        }
    }, 1000);
}

    function processAnalysisData(analysisData) {
        fullAnalysisData = analysisData;
        allHoldingsData = analysisData.holdings_list || [];
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

        filteredHoldingsData = allHoldingsData.filter(item => {
            const matchesText = String(item.code).toLowerCase().includes(filterText) ||
                                String(item.name || '').toLowerCase().includes(filterText);
            const matchesIndustry = !selectedIndustry || item.industry === selectedIndustry || (selectedIndustry === 'N/A' && !item.industry);
            const matchesAccountType = !selectedAccountType || item.account_type === selectedAccountType;
            const matchesSecurityCompany = !selectedSecurityCompany || (item.security_company || '-') === selectedSecurityCompany;
            return matchesText && matchesIndustry && matchesAccountType && matchesSecurityCompany;
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
            createCell(item.name);
            createCell(item.industry || 'N/A');
            createCell(item.asset_type === 'jp_stock' ? '国内株式' : (item.asset_type === 'investment_trust' ? '投資信託' : (item.asset_type === 'us_stock' ? '米国株式' : 'N/A')));
            createCell(item.security_company || '-'); 
            createCell(item.account_type);
            
            // フィボナッチの表示
            let fibText = '-';
            if (item.fibonacci && item.fibonacci.retracement !== undefined) {
                fibText = `${item.fibonacci.retracement.toFixed(1)}%`;
            }
            createCell(fibText);

            // RCIの表示
            let rciText = '-';
            if (item.rci_26 !== undefined && item.rci_26 !== null) {
                rciText = `${item.rci_26.toFixed(1)}%`;
            }
            createCell(rciText);

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

        portfolioSummary.innerHTML = `
            <h3>サマリー</h3>
            <p>総評価額: <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalMarketValue, 0)}円</span></p>
            <p>総損益: <span class="${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossClass}">${formatNumber(totalProfitLoss, 0)}円</span></p>
            <p>総損益率: <span class="${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossRateClass}">${formatNumber(totalProfitLossRate, 2)}%</span></p>
            <p>年間配当合計: <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividend, 0)}円</span></p>
            <p>年間配当合計(税引後): <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividendAfterTax, 0)}円</span></p>
            <hr>
            <p title="配当が出る銘柄のみを対象とした利回りです">配当利回り(現在値): <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(yieldOnCurrent, 2)}%</span></p>
            <p title="配当が出る銘柄のみを対象とした、投資額に対する利回りです">配当利回り(取得値): <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(yieldOnCost, 2)}%</span></p>
        `;
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
        
        const activeBtn = document.querySelector('.chart-toggle-btn.active');
        updateChart(activeBtn ? activeBtn.dataset.chartType : 'industry');
    }

    function updateChart(chartType) {
        document.querySelectorAll('.chart-container canvas').forEach(canvas => {
            if (!canvas.id.includes('history')) canvas.classList.add('hidden');
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
        if (retryTimer) clearInterval(retryTimer);
    });

    fetchAndRenderAnalysisData();
});