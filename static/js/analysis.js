document.addEventListener('DOMContentLoaded', () => {
    console.log('analysis.js loaded');

    const summarySection = document.querySelector('.portfolio-summary');
    const tableHeader = document.querySelector('#analysis-table thead tr');
    const tableBody = document.querySelector('#analysis-table tbody');
    const downloadCsvButton = document.getElementById('download-analysis-csv-button');

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

    function renderTable(stocks) {
        // ヘッダーの描画
        tableHeader.innerHTML = ''; // クリア
        const headers = [
            { key: 'code', name: '銘柄コード' },
            { key: 'name', name: '銘柄名' },
            { key: 'industry', name: '業種' },
            { key: 'quantity', name: '数量' },
            { key: 'purchase_price', name: '取得単価' },
            { key: 'price', name: '現在株価' },
            { key: 'market_value', name: '評価額' },
            { key: 'profit_loss', name: '損益' },
            { key: 'profit_loss_rate', name: '損益率(%)' },
            { key_display: 'estimated_annual_dividend', name: '年間配当' }
        ];
        headers.forEach(h => {
            const th = document.createElement('th');
            th.textContent = h.name;
            tableHeader.appendChild(th);
        });

        // ボディの描画
        tableBody.innerHTML = ''; // クリア
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