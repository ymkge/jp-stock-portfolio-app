document.addEventListener('DOMContentLoaded', () => {
    console.log('analysis.js loaded');

    // --- DOM要素の取得 ---
    const summarySection = document.querySelector('.portfolio-summary');
    const chartContainer = document.querySelector('.chart-container');
    const industryChartCanvas = document.getElementById('industry-chart');
    const accountTypeChartCanvas = document.getElementById('account-type-chart');
    const chartToggleButtons = document.querySelectorAll('.chart-toggle-btn');
    const downloadCsvButton = document.getElementById('download-analysis-csv-button');

    // --- グローバル変数 ---
    let industryChartInstance = null;
    let accountTypeChartInstance = null;
    let allHoldingsData = []; // 全ての保有口座情報
    let industryBreakdownData = {};
    let accountTypeBreakdownData = {};

    // --- ヘルパー関数 ---
    const formatNumber = (num, fractionDigits = 0) => {
        if (num === null || num === undefined) return 'N/A';
        return num.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
    };

    const formatProfit = (num) => {
        if (num === null || num === undefined) return 'N/A';
        const sign = num > 0 ? '+' : '';
        return sign + formatNumber(num);
    };

    const getProfitClass = (num) => {
        if (num === null || num === undefined) return '';
        if (num > 0) return 'text-plus';
        if (num < 0) return 'text-minus';
        return '';
    };

    // --- データ取得と描画 ---
    async function initialize() {
        try {
            const response = await fetch('/api/portfolio/analysis');
            if (!response.ok) {
                throw new Error('分析データの取得に失敗しました。');
            }
            const data = await response.json();
            
            allHoldingsData = data.holdings_list;
            industryBreakdownData = data.industry_breakdown;
            accountTypeBreakdownData = data.account_type_breakdown;

            renderSummary(allHoldingsData);
            renderChart('industry'); // 初期表示は業種別グラフ
            renderTable(allHoldingsData);

        } catch (error) {
            console.error('Error initializing analysis page:', error);
            summarySection.innerHTML = `<p style="color: red;">${error.message}</p>`;
        }
    }

    function renderSummary(holdings) {
        if (!holdings || holdings.length === 0) {
            summarySection.innerHTML = '<p>分析対象の保有銘柄がありません。</p>';
            return;
        }

        const totalInvestment = holdings.reduce((sum, h) => sum + (h.investment_amount || 0), 0);
        const totalMarketValue = holdings.reduce((sum, h) => sum + (h.market_value || 0), 0);
        const totalProfitLoss = totalMarketValue - totalInvestment;
        const totalProfitLossRate = totalInvestment !== 0 ? (totalProfitLoss / totalInvestment) * 100 : 0;
        const totalAnnualDividend = holdings.reduce((sum, h) => sum + (h.estimated_annual_dividend || 0), 0);

        summarySection.innerHTML = `
            <ul>
                <li><strong>口座別保有銘柄件数:</strong> ${holdings.length}</li>
                <li><strong>総投資額:</strong> ${formatNumber(totalInvestment)}円</li>
                <li><strong>総評価額:</strong> ${formatNumber(totalMarketValue)}円</li>
                <li class="${getProfitClass(totalProfitLoss)}">
                    <strong>総損益:</strong> ${formatProfit(totalProfitLoss)}円
                    (${totalProfitLossRate.toFixed(2)}%)
                </li>
                <li><strong>年間配当金（予想）:</strong> ${formatNumber(totalAnnualDividend)}円</li>
            </ul>
        `;
    }

    function renderChart(chartType) {
        // 既存のチャートを破棄
        if (industryChartInstance) industryChartInstance.destroy();
        if (accountTypeChartInstance) accountTypeChartInstance.destroy();

        // canvasの表示/非表示を切り替え
        industryChartCanvas.classList.toggle('hidden', chartType !== 'industry');
        accountTypeChartCanvas.classList.toggle('hidden', chartType !== 'account-type');

        let labels = [];
        let data = [];
        let title = '';
        let ctx = null;
        let chartInstance = null;

        if (chartType === 'industry') {
            labels = Object.keys(industryBreakdownData);
            data = Object.values(industryBreakdownData);
            title = '業種別ポートフォリオ構成';
            ctx = industryChartCanvas.getContext('2d');
            chartInstance = industryChartInstance;
        } else if (chartType === 'account-type') {
            labels = Object.keys(accountTypeBreakdownData);
            data = Object.values(accountTypeBreakdownData);
            title = '口座種別ポートフォリオ構成';
            ctx = accountTypeChartCanvas.getContext('2d');
            chartInstance = accountTypeChartInstance;
        } else {
            return;
        }

        if (!data || data.length === 0) {
            chartContainer.innerHTML = '<p>グラフを表示するデータがありません。</p>';
            return;
        }

        const backgroundColors = [
            '#332288', '#117733', '#44AA99', '#88CCEE', '#DDCC77', '#CC6677', '#AA4499', 
            '#882255', '#E51E1E', '#6699CC', '#F77F00', '#994F00', '#33FF00', '#00FFCC',
            '#0099FF', '#6600FF', '#CC00FF', '#FF00CC', '#FF0066', '#FF3300', '#FF9900',
            '#FFFF00', '#99FF00', '#00FF00', '#00FF99', '#00FFFF', '#0066FF', '#3300FF',
            '#9900FF', '#FF00FF'
        ];

        chartInstance = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: labels,
                datasets: [{
                    label: '評価額',
                    data: data,
                    backgroundColor: backgroundColors.slice(0, labels.length),
                    borderColor: '#fff',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: title,
                        font: { size: 16 }
                    },
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed !== null) {
                                    label += formatNumber(context.parsed) + '円';
                                }
                                return label;
                            }
                        }
                    }
                }
            }
        });

        if (chartType === 'industry') {
            industryChartInstance = chartInstance;
        } else {
            accountTypeChartInstance = chartInstance;
        }
    }

    function renderTable(holdings) {
    const table = document.getElementById('analysis-table');
    if (!table) return;

    const headers = [
        { key: 'code', name: '銘柄コード' }, { key: 'name', name: '銘柄名' },
        { key: 'account_type', name: '口座種別' }, { key: 'industry', name: '業種' },
        { key: 'quantity', name: '数量' }, { key: 'purchase_price', name: '取得単価' },
        { key: 'price', name: '現在株価' }, { key: 'market_value', name: '評価額' },
        { key: 'profit_loss', name: '損益' }, { key: 'profit_loss_rate', name: '損益率(%)' },
        { key: 'estimated_annual_dividend', name: '年間配当' }
    ];

    // ヘッダーのHTML文字列を生成
    const headerHtml = `
        <thead>
            <tr id="analysis-table-header-row">
                ${headers.map(h => `<th>${h.name}</th>`).join('')}
            </tr>
        </thead>
    `;

    // ボディのHTML文字列を生成
    let bodyHtml;
    if (!holdings || holdings.length === 0) {
        bodyHtml = `
            <tbody>
                <tr>
                    <td colspan="${headers.length}" style="text-align: center;">データがありません。</td>
                </tr>
            </tbody>
        `;
    } else {
        const rowsHtml = holdings.map(holding => `
            <tr>
                <td>${holding.code || 'N/A'}</td>
                <td>${holding.name || 'N/A'}</td>
                <td>${holding.account_type || 'N/A'}</td>
                <td>${holding.industry || 'N/A'}</td>
                <td>${formatNumber(holding.quantity)}</td>
                <td>${formatNumber(holding.purchase_price, 2)}</td>
                <td>${formatNumber(holding.price)}</td>
                <td>${formatNumber(holding.market_value)}</td>
                <td class="${getProfitClass(holding.profit_loss)}">${formatProfit(holding.profit_loss)}</td>
                <td class="${getProfitClass(holding.profit_loss_rate)}">${holding.profit_loss_rate !== null ? `${holding.profit_loss_rate.toFixed(2)}%` : 'N/A'}</td>
                <td>${formatNumber(holding.estimated_annual_dividend)}</td>
            </tr>
        `).join('');
        bodyHtml = `<tbody>${rowsHtml}</tbody>`;
    }

    // テーブル全体を一度に更新
    table.innerHTML = headerHtml + bodyHtml;
}

    // --- イベントリスナー ---
    downloadCsvButton.addEventListener('click', () => {
        window.location.href = '/api/portfolio/analysis/csv';
    });

    chartToggleButtons.forEach(button => {
        button.addEventListener('click', () => {
            chartToggleButtons.forEach(btn => btn.classList.remove('active'));
            button.classList.add('active');
            renderChart(button.dataset.chartType);
        });
    });

    // --- 初期実行 ---
    initialize();
});