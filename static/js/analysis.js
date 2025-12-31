document.addEventListener('DOMContentLoaded', () => {
    // --- DOM要素の取得 ---
    const alertContainer = document.getElementById('alert-container');
    const portfolioSummary = document.querySelector('.portfolio-summary');
    const analysisTableBody = document.querySelector('#analysis-table tbody');
    const toggleVisibilityCheckbox = document.getElementById('toggle-visibility');
    const analysisFilterInput = document.getElementById('analysis-filter-input');
    const industryFilterSelect = document.getElementById('industry-filter');
    const accountTypeFilterSelect = document.getElementById('account-type-filter');
    const downloadAnalysisCsvButton = document.getElementById('download-analysis-csv-button');
    const chartToggleBtns = document.querySelectorAll('.chart-toggle-btn');

    // --- Chart.jsインスタンス ---
    let industryChart;
    let accountTypeChart;
    let countryChart;

    // --- グローバル変数 ---
    let allHoldingsData = [];
    let fullAnalysisData = {};
    let filteredHoldingsData = [];
    let currentSort = { key: 'market_value', order: 'desc' };
    let isAmountVisible = true;

    // --- 初期化処理 ---
    async function initialize() {
        try {
            const response = await fetch('/api/portfolio/analysis');
            if (!response.ok) {
                let errorDetail = 'Failed to fetch analysis data';
                try {
                    const errorData = await response.json();
                    errorDetail = errorData.detail || errorDetail;
                } catch (e) {
                    errorDetail = response.statusText;
                }
                const error = new Error(errorDetail);
                error.status = response.status;
                throw error;
            }
            const analysisData = await response.json();
            fullAnalysisData = analysisData;
            allHoldingsData = analysisData.holdings_list;

            isAmountVisible = !toggleVisibilityCheckbox.checked;

            populateFilters();
            filterAndRender();
        } catch (error) {
            console.error('Analysis initialization error:', error);
            showAlert(`分析データの取得に失敗しました。(${error.message})`, 'danger');
        }
    }

    // --- レンダリング関連 ---
    function filterAndRender() {
        const filterText = analysisFilterInput.value.toLowerCase();
        const selectedIndustry = industryFilterSelect.value;
        const selectedAccountType = accountTypeFilterSelect.value;

        filteredHoldingsData = allHoldingsData.filter(item => {
            const matchesText = String(item.code).toLowerCase().includes(filterText) ||
                                String(item.name || '').toLowerCase().includes(filterText);
            const matchesIndustry = !selectedIndustry || item.industry === selectedIndustry || (selectedIndustry === 'N/A' && !item.industry);
            const matchesAccountType = !selectedAccountType || item.account_type === selectedAccountType;
            return matchesText && matchesIndustry && matchesAccountType;
        });

        sortHoldings(filteredHoldingsData);
        renderAnalysisTable(filteredHoldingsData);
        renderSummary();
        renderCharts(filteredHoldingsData);
        updateSortHeaders();
    }

    function renderAnalysisTable(holdings) {
        analysisTableBody.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            analysisTableBody.innerHTML = `<tr><td colspan="13" style="text-align:center;">該当する保有銘柄はありません。</td></tr>`;
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
            // 'text-plus'と'text-minus'を元の'profit'と'loss'に戻す
            const profitLossClass = isNaN(profitLoss) ? '' : (profitLoss >= 0 ? 'profit' : 'loss');
            const profitLossRateClass = isNaN(profitLossRate) ? '' : (profitLossRate >= 0 ? 'profit' : 'loss');

            createCell(item.code);
            createCell(item.name);
            createCell(item.industry || 'N/A');
            createCell(item.asset_type === 'jp_stock' ? '国内株式' : (item.asset_type === 'investment_trust' ? '投資信託' : (item.asset_type === 'us_stock' ? '米国株式' : 'N/A')));
            createCell(item.account_type);
            // 数量、取得単価、年間配当にも masked-amount クラスを適用
            createCell(formatNumber(item.quantity, item.asset_type === 'investment_trust' ? 6 : 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.purchase_price, 2), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.price, 2));
            createCell(formatNumber(item.estimated_annual_dividend, 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.estimated_annual_dividend_after_tax, 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.market_value, 0), !isAmountVisible ? 'masked-amount' : '');
            createCell(formatNumber(item.profit_loss, 0), `${!isAmountVisible ? 'masked-amount' : ''} ${profitLossClass}`);
            createCell(formatNumber(item.profit_loss_rate, 2), `${!isAmountVisible ? 'masked-amount' : ''} ${profitLossRateClass}`);
        });
    }

    function renderSummary() {
        const totalMarketValue = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.market_value) || 0), 0);
        const totalProfitLoss = allHoldingsData.reduce((sum, item) => sum + (parseFloat(item.profit_loss) || 0), 0);
        const totalInvestment = totalMarketValue - totalProfitLoss;
        const totalProfitLossRate = totalInvestment !== 0 ? (totalProfitLoss / totalInvestment) * 100 : 0;
        
        const totalEstimatedAnnualDividend = fullAnalysisData.total_annual_dividend || 0;
        const totalEstimatedAnnualDividendAfterTax = fullAnalysisData.total_annual_dividend_after_tax || 0;

        const summaryProfitLossClass = totalProfitLoss >= 0 ? 'profit' : 'loss';
        const summaryProfitLossRateClass = totalProfitLossRate >= 0 ? 'profit' : 'loss';

        portfolioSummary.innerHTML = `
            <p>総評価額: <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalMarketValue, 0)}円</span></p>
            <p>総損益: <span class="${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossClass}">${formatNumber(totalProfitLoss, 0)}円</span></p>
            <p>総損益率: <span class="${!isAmountVisible ? 'masked-amount' : ''} ${summaryProfitLossRateClass}">${formatNumber(totalProfitLossRate, 2)}%</span></p>
            <p>年間配当合計: <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividend, 0)}円</span></p>
            <p>年間配当合計(税引後): <span class="${!isAmountVisible ? 'masked-amount' : ''}">${formatNumber(totalEstimatedAnnualDividendAfterTax, 0)}円</span></p>
        `;
    }

    function renderCharts(holdings) {
        const industryBreakdown = {};
        const accountTypeBreakdown = {};
        const countryBreakdown = {};

        holdings.forEach(item => {
            const marketValue = parseFloat(item.market_value) || 0;
            if (marketValue > 0) {
                const industry = item.industry || 'その他';
                industryBreakdown[industry] = (industryBreakdown[industry] || 0) + marketValue;

                const accountType = item.account_type || '不明';
                accountTypeBreakdown[accountType] = (accountTypeBreakdown[accountType] || 0) + marketValue;
                
                let country = 'その他';
                if (item.asset_type === 'jp_stock') country = '日本';
                else if (item.asset_type === 'us_stock') country = '米国';
                else if (item.asset_type === 'investment_trust') country = '投資信託';
                countryBreakdown[country] = (countryBreakdown[country] || 0) + marketValue;
            }
        });

        const chartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label || '';
                            if (label) label += ': ';
                            const total = context.dataset.data.reduce((sum, val) => sum + val, 0);
                            const percentage = total > 0 ? (context.raw / total * 100) : 0;
                            
                            // 金額を隠す機能に対応
                            const formattedAmount = isAmountVisible ? `${formatNumber(context.raw, 0)}円` : '***円';
                            label += `${formattedAmount} (${percentage.toFixed(2)}%)`;
                            return label;
                        }
                    }
                }
            }
        };

        const getChartData = (breakdown) => ({
            labels: Object.keys(breakdown),
            datasets: [{
                data: Object.values(breakdown),
                backgroundColor: generateColors(Object.keys(breakdown).length),
                hoverOffset: 4
            }]
        });

        if (industryChart) industryChart.destroy();
        if (Object.keys(industryBreakdown).length > 0) {
            document.getElementById('industry-chart').classList.remove('hidden');
            industryChart = new Chart(document.getElementById('industry-chart'), { type: 'pie', data: getChartData(industryBreakdown), options: chartOptions });
        } else {
            document.getElementById('industry-chart').classList.add('hidden');
        }

        if (accountTypeChart) accountTypeChart.destroy();
        if (Object.keys(accountTypeBreakdown).length > 0) {
            document.getElementById('account-type-chart').classList.remove('hidden');
            accountTypeChart = new Chart(document.getElementById('account-type-chart'), { type: 'pie', data: getChartData(accountTypeBreakdown), options: chartOptions });
        } else {
            document.getElementById('account-type-chart').classList.add('hidden');
        }

        if (countryChart) countryChart.destroy();
        if (Object.keys(countryBreakdown).length > 0) {
            document.getElementById('country-chart').classList.remove('hidden');
            countryChart = new Chart(document.getElementById('country-chart'), { type: 'pie', data: getChartData(countryBreakdown), options: chartOptions });
        } else {
            document.getElementById('country-chart').classList.add('hidden');
        }
        
        updateChart('industry');
    }

    function updateChart(chartType) {
        document.querySelectorAll('.chart-container canvas').forEach(canvas => canvas.classList.add('hidden'));
        document.querySelectorAll('.chart-toggle-btn').forEach(btn => btn.classList.remove('active'));

        const activeBtn = document.querySelector(`.chart-toggle-btn[data-chart-type="${chartType}"]`);
        if (activeBtn) activeBtn.classList.add('active');

        const chartCanvas = document.getElementById(`${chartType}-chart`);
        if (chartCanvas) chartCanvas.classList.remove('hidden');
    }

    // --- ヘルパー関数 ---
    const formatNumber = (num, fractionDigits = 0) => {
        const parsedNum = parseFloat(num);
        if (parsedNum === null || parsedNum === undefined || isNaN(parsedNum)) return 'N/A';
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
    }

    function generateColors(numColors) {
        const colors = [];
        const baseColors = [
            '#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', 
            '#858796', '#5a5c69', '#f8f9fc', '#6f42c1', '#fd7e14'
        ];
        for (let i = 0; i < numColors; i++) {
            colors.push(baseColors[i % baseColors.length]);
        }
        return colors;
    }

    // --- イベントリスナー ---
    analysisFilterInput.addEventListener('input', filterAndRender);
    industryFilterSelect.addEventListener('change', filterAndRender);
    accountTypeFilterSelect.addEventListener('change', filterAndRender);

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
        renderSummary();
    });

    downloadAnalysisCsvButton.addEventListener('click', () => {
        window.location.href = '/api/portfolio/analysis/csv';
    });

    chartToggleBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            updateChart(btn.dataset.chartType);
        });
    });

    // --- 初期実行 ---
    initialize();
});