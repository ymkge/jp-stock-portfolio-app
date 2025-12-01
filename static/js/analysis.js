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
    let countryChart; // 国別ポートフォリオグラフ用

    // --- グローバル変数 ---
    let allHoldingsData = []; // 全保有銘柄データ
    let filteredHoldingsData = []; // フィルタリング後の保有銘柄データ
    let analysisData = {
        holdings_list: [],
        industry_breakdown: {},
        account_type_breakdown: {},
        country_breakdown: {} // 国別内訳を追加
    };
    let currentSort = { key: 'code', order: 'asc' };
    let isAmountVisible = true; // 金額表示のON/OFF
    const COOLDOWN_MINUTES = 10;
    const COOLDOWN_STORAGE_KEY = 'fullUpdateCooldownEnd'; // main.jsと共有

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
            analysisData = await response.json();
            allHoldingsData = analysisData.holdings_list;

            populateFilters();
            filterAndRender();
            renderSummary();
            renderCharts();
        } catch (error) {
            console.error('Analysis initialization error:', error);
            if (error.status === 429) {
                showAlert('クールダウン中です。表示されているのは前回のデータです。', 'info');
            } else {
                showAlert(`分析データの取得に失敗しました。(${error.message})`, 'danger');
            }
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
            const matchesIndustry = !selectedIndustry || item.industry === selectedIndustry;
            const matchesAccountType = !selectedAccountType || item.account_type === selectedAccountType;
            return matchesText && matchesIndustry && matchesAccountType;
        });

        sortHoldings(filteredHoldingsData);
        renderAnalysisTable(filteredHoldingsData);
        updateSortHeaders();
    }

    function renderAnalysisTable(holdings) {
        analysisTableBody.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            analysisTableBody.innerHTML = `<tr><td colspan="12" style="text-align:center;">該当する保有銘柄はありません。</td></tr>`;
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

            createCell(item.code);
            createCell(item.name);
            createCell(item.market || 'N/A'); // 市場列
            createCell(item.industry || 'N/A');
            createCell(item.asset_type === 'jp_stock' ? '国内株式' : (item.asset_type === 'investment_trust' ? '投資信託' : (item.asset_type === 'us_stock' ? '米国株式' : 'N/A')));
            createCell(item.account_type);
            createCell(formatNumber(item.quantity, item.asset_type === 'investment_trust' ? 6 : 0));
            createCell(formatNumber(item.purchase_price, 2));
            createCell(formatNumber(item.price, 2));
            createCell(formatNumber(item.market_value, 0), isAmountVisible ? '' : 'masked-amount');
            createCell(formatNumber(item.profit_loss, 0), isAmountVisible ? (item.profit_loss >= 0 ? 'profit' : 'loss') : 'masked-amount');
            createCell(formatNumber(item.profit_loss_rate, 2), isAmountVisible ? (item.profit_loss_rate >= 0 ? 'profit' : 'loss') : 'masked-amount');
        });
        applyVisibilityToggle();
    }

    function renderSummary() {
        const totalMarketValue = allHoldingsData.reduce((sum, item) => sum + (item.market_value || 0), 0);
        const totalProfitLoss = allHoldingsData.reduce((sum, item) => sum + (item.profit_loss || 0), 0);
        const totalInvestment = allHoldingsData.reduce((sum, item) => sum + (item.investment_amount || 0), 0);
        const totalProfitLossRate = totalInvestment !== 0 ? (totalProfitLoss / totalInvestment) * 100 : 0;

        portfolioSummary.innerHTML = `
            <p>総評価額: <span class="${isAmountVisible ? '' : 'masked-amount'}">${formatNumber(totalMarketValue, 0)}円</span></p>
            <p>総損益: <span class="${isAmountVisible ? (totalProfitLoss >= 0 ? 'profit' : 'loss') : 'masked-amount'}">${formatNumber(totalProfitLoss, 0)}円</span></p>
            <p>総損益率: <span class="${isAmountVisible ? (totalProfitLossRate >= 0 ? 'profit' : 'loss') : 'masked-amount'}">${formatNumber(totalProfitLossRate, 2)}%</span></p>
        `;
        applyVisibilityToggle();
    }

    function renderCharts() {
        const chartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed !== null) {
                                label += formatNumber(context.parsed, 0) + '円 (' + context.dataset.data[context.dataIndex].toFixed(2) + '%)';
                            }
                            return label;
                        }
                    }
                }
            }
        };

        const getChartData = (breakdown) => {
            const labels = Object.keys(breakdown);
            const values = Object.values(breakdown);
            const total = values.reduce((sum, val) => sum + val, 0);
            const percentages = values.map(val => total > 0 ? (val / total * 100) : 0);

            return {
                labels: labels,
                datasets: [{
                    data: percentages,
                    backgroundColor: generateColors(labels.length),
                    hoverOffset: 4
                }]
            };
        };

        // 業種別グラフ
        if (industryChart) industryChart.destroy();
        industryChart = new Chart(document.getElementById('industry-chart'), {
            type: 'pie',
            data: getChartData(analysisData.industry_breakdown),
            options: chartOptions
        });

        // 口座種別グラフ
        if (accountTypeChart) accountTypeChart.destroy();
        accountTypeChart = new Chart(document.getElementById('account-type-chart'), {
            type: 'pie',
            data: getChartData(analysisData.account_type_breakdown),
            options: chartOptions
        });

        // 国別グラフ
        if (countryChart) countryChart.destroy();
        countryChart = new Chart(document.getElementById('country-chart'), {
            type: 'pie',
            data: getChartData(analysisData.country_breakdown),
            options: chartOptions
        });

        // 初期表示は業種別
        document.getElementById('industry-chart').classList.remove('hidden');
        document.getElementById('account-type-chart').classList.add('hidden');
        document.getElementById('country-chart').classList.add('hidden');
    }

    function updateChart(chartType) {
        document.querySelectorAll('.chart-container canvas').forEach(canvas => canvas.classList.add('hidden'));
        document.querySelectorAll('.chart-toggle-btn').forEach(btn => btn.classList.remove('active'));

        document.querySelector(`.chart-toggle-btn[data-chart-type="${chartType}"]`).classList.add('active');

        if (chartType === 'industry') {
            document.getElementById('industry-chart').classList.remove('hidden');
            industryChart.update();
        } else if (chartType === 'account-type') {
            document.getElementById('account-type-chart').classList.remove('hidden');
            accountTypeChart.update();
        } else if (chartType === 'country') { // 国別グラフの表示
            document.getElementById('country-chart').classList.remove('hidden');
            countryChart.update();
        }
    }

    // --- ヘルパー関数 ---
    const formatNumber = (num, fractionDigits = 0) => {
        if (num === null || num === undefined || isNaN(num)) return 'N/A';
        return num.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
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
                    const num = parseFloat(v.replace(/,/g, '').replace(/%|円/g, ''));
                    return isNaN(num) ? v : num;
                }
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
        const hueStep = 360 / numColors;
        for (let i = 0; i < numColors; i++) {
            const hue = i * hueStep;
            colors.push(`hsl(${hue}, 70%, 60%)`);
        }
        return colors;
    }
    function applyVisibilityToggle() {
        document.querySelectorAll('.masked-amount').forEach(el => {
            if (isAmountVisible) {
                el.classList.remove('masked-amount');
            } else {
                el.classList.add('masked-amount');
            }
        });
        // サマリーの金額表示も更新
        renderSummary();
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
        applyVisibilityToggle();
        renderAnalysisTable(filteredHoldingsData); // テーブルも再描画してクラスを適用
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