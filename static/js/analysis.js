document.addEventListener('DOMContentLoaded', () => {
    console.log('analysis.js loaded');

    const summarySection = document.querySelector('.portfolio-summary');
    const chartContainer = document.querySelector('.chart-container');
    const chartCanvas = document.getElementById('industry-chart');
    const tableHeader = document.querySelector('#analysis-table thead tr');
    const tableBody = document.querySelector('#analysis-table tbody');
    const downloadCsvButton = document.getElementById('download-analysis-csv-button');

    let industryChart = null; // チャートのインスタンスを保持

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
            
            renderSummary(data.managed_stocks);
            renderChart(data.industry_breakdown);
            renderTable(data.managed_stocks);

        } catch (error) {
            console.error('Error initializing analysis page:', error);
            summarySection.innerHTML = `<p style="color: red;">${error.message}</p>`;
        }
    }

    function renderSummary(stocks) {
        if (!stocks || stocks.length === 0) {
            summarySection.innerHTML = '<p>分析対象の保有銘柄がありません。</p>';
            return;
        }

        const totalInvestment = stocks.reduce((sum, s) => sum + (s.investment_amount || 0), 0);
        const totalMarketValue = stocks.reduce((sum, s) => sum + (s.market_value || 0), 0);
        const totalProfitLoss = totalMarketValue - totalInvestment;
        const totalProfitLossRate = totalInvestment !== 0 ? (totalProfitLoss / totalInvestment) * 100 : 0;
        const totalAnnualDividend = stocks.reduce((sum, s) => sum + (s.estimated_annual_dividend || 0), 0);

        summarySection.innerHTML = `
            <ul>
                <li><strong>銘柄数:</strong> ${stocks.length}</li>
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

    function renderChart(industryData) {
        if (industryChart) {
            industryChart.destroy(); // 既存のチャートを破棄
        }
        if (!industryData || Object.keys(industryData).length === 0) {
            chartContainer.innerHTML = '<p>グラフを表示するデータがありません。</p>';
            return;
        }

        const labels = Object.keys(industryData);
        const data = Object.values(industryData);

        const ctx = chartCanvas.getContext('2d');
        industryChart = new Chart(ctx, {
            type: 'pie', // 円グラフ
            data: {
                labels: labels,
                datasets: [{
                    label: '評価額',
                    data: data,
                    backgroundColor: [ // 色の配列
                        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40',
                        '#E7E9ED', '#8A2BE2', '#5F9EA0', '#D2691E', '#FF7F50', '#6495ED'
                    ],
                    borderColor: '#fff',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
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
    }

    function renderTable(stocks) {
        tableHeader.innerHTML = '';
        const headers = [
            { key: 'code', name: '銘柄コード' }, { key: 'name', name: '銘柄名' },
            { key: 'industry', name: '業種' }, { key: 'quantity', name: '数量' },
            { key: 'purchase_price', name: '取得単価' }, { key: 'price', name: '現在株価' },
            { key: 'market_value', name: '評価額' }, { key: 'profit_loss', name: '損益' },
            { key: 'profit_loss_rate', name: '損益率(%)' }, { key: 'estimated_annual_dividend', name: '年間配当' }
        ];
        headers.forEach(h => {
            const th = document.createElement('th');
            th.textContent = h.name;
            tableHeader.appendChild(th);
        });

        tableBody.innerHTML = '';
        if (!stocks || stocks.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="${headers.length}" style="text-align:center;">データがありません。</td></tr>`;
            return;
        }

        stocks.forEach(stock => {
            const row = tableBody.insertRow();
            const createTextCell = (text, className = '') => {
                const cell = row.insertCell();
                cell.textContent = text;
                if (className) cell.className = className;
                return cell;
            };
            createTextCell(stock.code);
            createTextCell(stock.name);
            createTextCell(stock.industry);
            createTextCell(formatNumber(stock.quantity));
            createTextCell(formatNumber(stock.purchase_price, 2));
            createTextCell(formatNumber(stock.price));
            createTextCell(formatNumber(stock.market_value));
            createTextCell(formatProfit(stock.profit_loss), getProfitClass(stock.profit_loss));
            createTextCell(stock.profit_loss_rate !== null ? `${stock.profit_loss_rate.toFixed(2)}%` : 'N/A', getProfitClass(stock.profit_loss_rate));
            createTextCell(formatNumber(stock.estimated_annual_dividend));
        });
    }

    // --- イベントリスナー ---
    downloadCsvButton.addEventListener('click', () => {
        window.location.href = '/api/portfolio/analysis/csv';
    });

    // --- 初期実行 ---
    initialize();
});
