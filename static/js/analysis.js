document.addEventListener('DOMContentLoaded', () => {
    console.log('analysis.js loaded');

    // --- DOM要素の取得 ---
    const summarySection = document.querySelector('.portfolio-summary');
    const chartContainer = document.querySelector('.chart-container');
    const industryChartCanvas = document.getElementById('industry-chart');
    const accountTypeChartCanvas = document.getElementById('account-type-chart');
    const chartToggleButtons = document.querySelectorAll('.chart-toggle-btn');
    const downloadCsvButton = document.getElementById('download-analysis-csv-button');
    const analysisTable = document.getElementById('analysis-table');
    const filterInput = document.getElementById('analysis-filter-input');
    const industryFilter = document.getElementById('industry-filter');
    const accountTypeFilter = document.getElementById('account-type-filter');
    const visibilityToggle = document.getElementById('toggle-visibility');

    // --- グローバル変数 ---
    let industryChartInstance = null;
    let accountTypeChartInstance = null;
    let allHoldingsData = []; // 全ての保有口座情報
    let industryBreakdownData = {};
    let accountTypeBreakdownData = {};
    let currentSort = { key: 'market_value', order: 'desc' }; // デフォルトソート

    // --- ヘルパー関数 ---
    const formatNumber = (num, fractionDigits = 0) => {
        if (num === null || num === undefined || isNaN(num)) return 'N/A';
        if (visibilityToggle.checked) return '***';
        return num.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
    };

    const formatProfit = (num) => {
        if (num === null || num === undefined || isNaN(num)) return 'N/A';
        if (visibilityToggle.checked) return '***';
        const sign = num > 0 ? '+' : '';
        return sign + num.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });
    };

    const getProfitClass = (num) => {
        if (visibilityToggle.checked || num === null || num === undefined || isNaN(num)) return '';
        if (num > 0) return 'text-plus';
        if (num < 0) return 'text-minus';
        return '';
    };

    // --- ソートとフィルタリング関連 ---
    function sortData(data) {
        data.sort((a, b) => {
            let valA = a[currentSort.key], valB = b[currentSort.key];
            const parseValue = (v) => {
                if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '' || v === '投資信託') return -Infinity; // 投資信託はソート対象外
                if (typeof v === 'string') {
                    const num = parseFloat(v.replace(/,/g, '').replace(/%|倍|円/g, ''));
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
        const tableHeaders = document.querySelectorAll('#analysis-table .sortable');
        tableHeaders.forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) {
                header.classList.add('sort-active', `sort-${currentSort.order}`);
            }
        });
    }

    // --- データ取得と描画 ---
    async function initialize() {
        try {
            visibilityToggle.checked = true;

            const response = await fetch('/api/portfolio/analysis');
            if (!response.ok) throw new Error('分析データの取得に失敗しました。');
            
            const data = await response.json();
            allHoldingsData = data.holdings_list;
            industryBreakdownData = data.industry_breakdown;
            accountTypeBreakdownData = data.account_type_breakdown;

            populateFilterDropdowns();
            renderSummary(allHoldingsData);
            renderChart('industry');
            filterAndRenderTable();

        } catch (error) {
            console.error('Error initializing analysis page:', error);
            summarySection.innerHTML = `<p style="color: red;">${error.message}</p>`;
        }
    }
    
    function populateFilterDropdowns() {
        // 既存のオプションをクリア
        industryFilter.innerHTML = '<option value="">すべての業種</option>';
        accountTypeFilter.innerHTML = '<option value="">すべての口座種別</option>';

        const industries = [...new Set(allHoldingsData.map(h => h.industry))].sort();
        const accountTypes = [...new Set(allHoldingsData.map(h => h.account_type))].sort();

        industries.forEach(industry => {
            const option = document.createElement('option');
            option.value = industry;
            option.textContent = industry;
            industryFilter.appendChild(option);
        });

        accountTypes.forEach(type => {
            const option = document.createElement('option');
            option.value = type;
            option.textContent = type;
            accountTypeFilter.appendChild(option);
        });
    }

    function filterAndRenderTable() {
        const filterText = filterInput.value.toLowerCase();
        const selectedIndustry = industryFilter.value;
        const selectedAccountType = accountTypeFilter.value;

        let filteredData = allHoldingsData.filter(holding => {
            const textMatch = filterText === '' ||
                String(holding.code).toLowerCase().includes(filterText) ||
                String(holding.name || '').toLowerCase().includes(filterText);
            
            const industryMatch = selectedIndustry === '' || holding.industry === selectedIndustry;
            const accountTypeMatch = selectedAccountType === '' || holding.account_type === selectedAccountType;

            return textMatch && industryMatch && accountTypeMatch;
        });
        
        sortData(filteredData);
        renderTable(filteredData);
        updateSortHeaders();
    }

    function renderSummary(holdings) {
        if (!holdings || holdings.length === 0) {
            summarySection.innerHTML = '<p>分析対象の保有資産がありません。</p>';
            return;
        }

        const totalInvestment = holdings.reduce((sum, h) => sum + (h.investment_amount || 0), 0);
        const totalMarketValue = holdings.reduce((sum, h) => sum + (h.market_value || 0), 0);
        const totalProfitLoss = totalMarketValue - totalInvestment;
        const totalProfitLossRate = totalInvestment !== 0 ? (totalProfitLoss / totalInvestment) * 100 : 0;
        const totalAnnualDividend = holdings.reduce((sum, h) => sum + (h.estimated_annual_dividend || 0), 0);

        const profitLossRateText = visibilityToggle.checked ? '***' : `(${totalProfitLossRate.toFixed(2)}%)`;

        summarySection.innerHTML = `
            <ul>
                <li><strong>保有資産件数:</strong> ${holdings.length}</li>
                <li><strong>総投資額:</strong> ${formatNumber(totalInvestment)}円</li>
                <li><strong>総評価額:</strong> ${formatNumber(totalMarketValue)}円</li>
                <li class="${getProfitClass(totalProfitLoss)}">
                    <strong>総損益:</strong> ${formatProfit(totalProfitLoss)}円
                    ${profitLossRateText}
                </li>
                <li><strong>年間配当金（予想）:</strong> ${formatNumber(totalAnnualDividend)}円</li>
            </ul>
        `;
    }

    function renderChart(chartType) {
        if (industryChartInstance) industryChartInstance.destroy();
        if (accountTypeChartInstance) accountTypeChartInstance.destroy();

        industryChartCanvas.classList.toggle('hidden', chartType !== 'industry');
        accountTypeChartCanvas.classList.toggle('hidden', chartType !== 'account-type');

        let labels, data, title, ctx;
        if (chartType === 'industry') {
            labels = Object.keys(industryBreakdownData);
            data = Object.values(industryBreakdownData);
            title = '業種別ポートフォリオ構成';
            ctx = industryChartCanvas.getContext('2d');
        } else {
            labels = Object.keys(accountTypeBreakdownData);
            data = Object.values(accountTypeBreakdownData);
            title = '口座種別ポートフォリオ構成';
            ctx = accountTypeChartCanvas.getContext('2d');
        }

        if (!data || data.length === 0) {
            chartContainer.innerHTML = '<p>グラフを表示するデータがありません。</p>';
            return;
        }

        const backgroundColors = ['#332288', '#117733', '#44AA99', '#88CCEE', '#DDCC77', '#CC6677', '#AA4499', '#882255', '#E51E1E', '#6699CC', '#F77F00', '#994F00', '#33FF00', '#00FFCC', '#0099FF', '#6600FF', '#CC00FF', '#FF00CC', '#FF0066', '#FF3300', '#FF9900', '#FFFF00', '#99FF00', '#00FF00', '#00FF99', '#00FFFF', '#0066FF', '#3300FF', '#9900FF', '#FF00FF'];

        const chartInstance = new Chart(ctx, {
            type: 'pie',
            data: { labels, datasets: [{ label: '評価額', data, backgroundColor: backgroundColors.slice(0, labels.length), borderColor: '#fff', borderWidth: 1 }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    title: { display: true, text: title, font: { size: 16 } },
                    legend: { position: 'top' },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                if (visibilityToggle.checked) return `${context.label}: ***`;
                                let label = context.label || '';
                                if (label) label += ': ';
                                if (context.parsed !== null) label += formatNumber(context.parsed) + '円';
                                return label;
                            }
                        }
                    }
                }
            }
        });

        if (chartType === 'industry') industryChartInstance = chartInstance;
        else accountTypeChartInstance = chartInstance;
    }

    function renderTable(holdings) {
        const tableBody = document.querySelector('#analysis-table tbody');
        tableBody.innerHTML = ''; // 既存のtbodyをクリア

        if (!holdings || holdings.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="10" style="text-align: center;">データがありません。</td></tr>`;
            return;
        }

        const rowsHtml = holdings.map(holding => {
            const profitLossRateText = visibilityToggle.checked ? '***' : (holding.profit_loss_rate !== null && !isNaN(holding.profit_loss_rate) ? `${holding.profit_loss_rate.toFixed(2)}%` : 'N/A');
            const assetTypeName = holding.asset_type === 'jp_stock' ? '国内株式' : (holding.asset_type === 'investment_trust' ? '投資信託' : 'N/A');
            
            const isFund = holding.asset_type === 'investment_trust';
            const quantityDigits = isFund ? 6 : 0;

            return `
                <tr>
                    <td>${holding.code || 'N/A'}</td>
                    <td>${holding.name || 'N/A'}</td>
                    <td>${holding.asset_type === 'investment_trust' ? '-' : (holding.industry || 'N/A')}</td>
                    <td>${assetTypeName}</td>
                    <td>${holding.account_type || 'N/A'}</td>
                    <td>${formatNumber(holding.quantity, quantityDigits)}</td>
                    <td>${formatNumber(holding.purchase_price, 2)}</td>
                    <td>${formatNumber(holding.price)}</td>
                    <td>${formatNumber(holding.market_value)}</td>
                    <td class="${getProfitClass(holding.profit_loss)}">${formatProfit(holding.profit_loss)}</td>
                    <td class="${getProfitClass(holding.profit_loss_rate)}">${profitLossRateText}</td>
                </tr>
            `;
        }).join('');
        tableBody.innerHTML = rowsHtml;
    }

    // --- イベントリスナー ---
    downloadCsvButton.addEventListener('click', () => { window.location.href = '/api/portfolio/analysis/csv'; });

    chartToggleButtons.forEach(button => {
        button.addEventListener('click', () => {
            chartToggleButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            renderChart(button.dataset.chartType);
        });
    });

    analysisTable.addEventListener('click', (event) => {
        const header = event.target.closest('.sortable');
        if (header) {
            const key = header.dataset.key;
            if (currentSort.key === key) {
                currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.key = key;
                currentSort.order = 'asc';
            }
            filterAndRenderTable();
        }
    });

    filterInput.addEventListener('input', filterAndRenderTable);
    industryFilter.addEventListener('change', filterAndRenderTable);
    accountTypeFilter.addEventListener('change', filterAndRenderTable);

    visibilityToggle.addEventListener('change', () => {
        renderSummary(allHoldingsData);
        renderChart(document.querySelector('.chart-toggle-btn.active').dataset.chartType);
        filterAndRenderTable();
    });

    // --- 初期実行 ---
    initialize();
});