document.addEventListener('DOMContentLoaded', () => {
    // --- DOM要素の取得 ---
    const addAssetForm = document.getElementById('add-asset-form');
    const assetCodeInput = document.getElementById('asset-code-input');
    const downloadCsvButton = document.getElementById('download-csv-button');
    const refreshAllButton = document.getElementById('refresh-all-button');
    const alertContainer = document.getElementById('alert-container');
    const deleteSelectedStocksButton = document.getElementById('delete-selected-stocks-button');
    const recentStocksList = document.getElementById('recent-stocks-list');
    const updateReportContainer = document.getElementById('update-report-container');
    const filterInput = document.getElementById('filter-input');
    const showOnlyManagedAssetsCheckbox = document.getElementById('show-only-managed-assets-checkbox');
    const showOnlyAttentionAssetsCheckbox = document.getElementById('show-only-attention-assets-checkbox');
    const showOnlyOpportunityAssetsCheckbox = document.getElementById('show-only-opportunity-assets-checkbox');
    const showOnlyOverheatedAssetsCheckbox = document.getElementById('show-only-overheated-assets-checkbox');
    const tabNav = document.querySelector('.tab-nav');
    const darkModeToggle = document.getElementById('dark-mode-toggle');

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
        });
    }

    initTheme();

    // --- スケルトンUI表示 ---
    function showSkeletons() {
        // 1. 市場サマリー
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

        // 2. テーブル (各タブの tbody に 5行のスケルトン)
        const assetTypes = ['jp_stock', 'investment_trust', 'us_stock'];
        const colCounts = { jp_stock: 17, investment_trust: 8, us_stock: 11 };
        
        assetTypes.forEach(type => {
            const tbody = document.querySelector(`#portfolio-table-${type} tbody`);
            if (tbody) {
                tbody.innerHTML = Array(5).fill(0).map(() => `
                    <tr class="skeleton-row">
                        ${Array(colCounts[type]).fill(0).map(() => `<td><div class="skeleton skeleton-cell"></div></td>`).join('')}
                    </tr>
                `).join('');
            }
        });
    }

    // --- モーダル関連DOM要素 ---
    const modalOverlay = document.getElementById('modal-overlay');
    const modalTitle = document.getElementById('modal-title');
    const holdingsListContainer = document.getElementById('holdings-list-container');
    const addNewHoldingBtn = document.getElementById('add-new-holding-btn');
    const holdingFormContainer = document.getElementById('holding-form-container');
    const holdingForm = document.getElementById('holding-form');
    const holdingFormTitle = document.getElementById('holding-form-title');
    const holdingIdInput = document.getElementById('holding-id-input');
    const accountTypeSelect = document.getElementById('account-type-select');
    const purchasePriceInput = document.getElementById('purchase-price-input');
    const quantityInput = document.getElementById('quantity-input');
    const holdingFormCancelBtn = document.getElementById('holding-form-cancel-btn');
    const modalCloseBtn = document.getElementById('modal-close-btn');
    const securityCompanySelect = document.getElementById('security-company-select');
    const memoInput = document.getElementById('memo-input');

    // --- グローバル変数 ---
    let allAssetsData = [];
    let accountTypes = [];
    let securityCompanies = [];
    let highlightRules = {};
    let currentSort = { key: 'code', order: 'asc' };
    let currentManagingCode = null;
    let activeTab = 'jp_stock';
    const ASSETS_STORAGE_KEY = 'jpStockPortfolioAssets';
    let fetchController = null;

    // --- データ取得とレンダリング ---
    async function fetchAndRenderAllData(force = false) {
        if (fetchController) {
            fetchController.abort();
        }
        fetchController = new AbortController();
        const signal = fetchController.signal;

        const cachedState = window.appState.getState('portfolio');
        if (cachedState) {
            allAssetsData = Array.isArray(cachedState) ? cachedState : (cachedState.data || []);
            if (cachedState.metadata) {
                renderUpdateReport(cachedState.metadata);
            }
            filterAndRender();
        } else {
            showSkeletons();
        }

        if (!force && !window.appState.canFetch()) {
            return;
        }

        refreshAllButton.disabled = true;
        refreshAllButton.textContent = '更新中...';
        
        try {
            const apiFetch = (url) => fetch(url, { signal }).then(handleApiResponse);

            const [assetsResponse, rules, recent, accTypes, secCompanies] = await Promise.all([
                apiFetch('/api/stocks'),
                apiFetch('/api/highlight-rules'),
                apiFetch('/api/recent-stocks'),
                apiFetch('/api/account-types'),
                apiFetch('/api/security-companies')
            ]);

            allAssetsData = Array.isArray(assetsResponse) ? assetsResponse : (assetsResponse.data || []);
            highlightRules = rules;
            accountTypes = accTypes;
            securityCompanies = secCompanies;

            window.appState.updateState('portfolio', assetsResponse);
            window.appState.updateTimestamp();
            saveAssetsToStorage(); 
            
            if (assetsResponse.metadata) {
                renderUpdateReport(assetsResponse.metadata);
            }

            renderRecentStocksList(recent);
            filterAndRender();
            if (force) {
                showAlert('ポートフォリオを更新しました。', 'success');
            }

        } catch (error) {
            if (error.name === 'AbortError') return;
            console.error('Data fetch error:', error);
            if (error instanceof window.appState.HttpError && error.status === 429) {
                console.log('Backend is currently throttling or updating. Using cached data.');
            } else {
                showAlert(`データ更新に失敗しました: ${error.message}`, 'danger', true);
                if (!allAssetsData || allAssetsData.length === 0) {
                    loadAssetsFromStorage();
                }
            }
        } finally {
            refreshAllButton.disabled = false;
            refreshAllButton.textContent = '全件更新';
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

        if (metadata.market_indices) {
            renderMarketSummary(metadata.market_indices);
        }
    }

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
                        <div class="market-index-price numeric">${price}</div>
                        <div class="market-index-changes">
                            <div class="market-index-row">
                                <span class="change-label">前日比:</span>
                                <span class="${changeClass} numeric">${change} (${formatPercent(changePercent)})</span>
                            </div>
                            <div class="market-index-row">
                                <span class="change-label">前週比:</span>
                                <span class="${wowClass} numeric">${formatPercent(wow)}</span>
                            </div>
                            <div class="market-index-row">
                                <span class="change-label">前月比:</span>
                                <span class="${momClass} numeric">${formatPercent(mom)}</span>
                            </div>
                        </div>
                    </div>
                </a>
            `;
        });
        container.innerHTML = html;
        container.classList.remove('hidden');
    }

    async function handleApiResponse(response) {
        if (!response.ok) {
            let errorDetail = `HTTP error! status: ${response.status}`;
            try {
                const errorData = await response.json();
                errorDetail = errorData.detail || errorDetail;
            } catch (e) {}
            throw new window.appState.HttpError(errorDetail, response.status);
        }
        return response.json();
    }

    function saveAssetsToStorage() {
        localStorage.setItem(ASSETS_STORAGE_KEY, JSON.stringify(allAssetsData));
    }

    function loadAssetsFromStorage() {
        const storedAssets = localStorage.getItem(ASSETS_STORAGE_KEY);
        if (storedAssets) {
            try {
                const parsed = JSON.parse(storedAssets);
                allAssetsData = Array.isArray(parsed) ? parsed : (parsed.data || []);
                filterAndRender();
            } catch (e) {
                console.error('Error parsing stored assets:', e);
            }
        }
    }

    function filterAndRender() {
        const filterText = filterInput.value.toLowerCase();
        const showOnlyManaged = showOnlyManagedAssetsCheckbox.checked;
        const showStrictDip = showOnlyAttentionAssetsCheckbox.checked;
        const showStrictLow = showOnlyOpportunityAssetsCheckbox.checked;
        const showOverheated = showOnlyOverheatedAssetsCheckbox.checked;
        
        let filteredAssets = allAssetsData.filter(asset => asset.asset_type === activeTab);

        if (showOnlyManaged) filteredAssets = filteredAssets.filter(asset => asset.holdings && asset.holdings.length > 0);
        if (showStrictDip) filteredAssets = filteredAssets.filter(asset => (asset.is_diamond === true || (asset.buy_signal && asset.buy_signal.is_diamond === true)) && asset.buy_signal && asset.buy_signal.level >= 1);
        if (showStrictLow) filteredAssets = filteredAssets.filter(asset => (asset.is_diamond === true || (asset.buy_signal && asset.buy_signal.is_diamond === true)) && asset.sell_signal && asset.sell_signal.level === 3);
        if (showOverheated) filteredAssets = filteredAssets.filter(asset => asset.sell_signal && (asset.sell_signal.level === 1 || asset.sell_signal.level === 2));

        if (filterText) {
            filteredAssets = filteredAssets.filter(asset =>
                String(asset.code).toLowerCase().includes(filterText) ||
                String(asset.name || '').toLowerCase().includes(filterText)
            );
        }
        sortAssets(filteredAssets);
        if (activeTab === 'jp_stock') renderStockTable(filteredAssets);
        else if (activeTab === 'investment_trust') renderFundTable(filteredAssets);
        else if (activeTab === 'us_stock') renderUSTable(filteredAssets);
        updateSortHeaders();
        updateDeleteSelectedButtonState();
    }

    function renderStockTable(stocks) {
        const tableBody = document.querySelector('#portfolio-table-jp_stock tbody');
        if (stocks.length === 0 && refreshAllButton.disabled) {
            const html = Array(5).fill(0).map(() => `<tr class="skeleton-row">${Array(17).fill(0).map(() => `<td><div class="skeleton skeleton-cell"></div></td>`).join('')}</tr>`).join('');
            tableBody.innerHTML = html;
            return;
        }
        tableBody.innerHTML = '';
        if (!stocks || stocks.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="17" style="text-align:center;">登録されている銘柄はありません。</td></tr>`;
            return;
        }
        stocks.forEach(jpStock => {
            const row = tableBody.insertRow();
            row.dataset.code = jpStock.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell(); cell.innerHTML = html;
                if (html === 'N/A' || html === '--' || html === '-') cell.className = (className ? className + ' ' : '') + 'na-value';
                else if (className) cell.className = className;
                return cell;
            };
            const createCellWithTooltip = (html, className = '', tooltipText = '', externalLink = '') => {
                const cell = createCell(html, className); if (tooltipText) cell.title = tooltipText;
                if (externalLink) { cell.style.cursor = 'pointer'; cell.addEventListener('click', () => window.open(externalLink, '_blank')); }
                return cell;
            };
            if (jpStock.error) {
                row.className = 'error-row'; row.title = jpStock.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${jpStock.code}" disabled>`);
                createCell(jpStock.code, 'numeric'); createCell(jpStock.error, 'error-message').colSpan = 14;
                createCell(`<button class="manage-btn" data-code="${jpStock.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${jpStock.code}">`);
            createCell(jpStock.code, 'numeric');
            const baseUrl = `https://finance.yahoo.co.jp/quote/${jpStock.code}.T`;
            let nameHtml = `<div class="d-flex flex-wrap align-items-center gap-1"><a href="${baseUrl}" target="_blank" class="fw-bold me-1">${jpStock.name}</a><div class="quick-links d-inline-flex gap-1"><a href="${baseUrl}/disclosure" target="_blank" class="badge bg-light text-dark border text-decoration-none" title="適時開示" style="font-size: 0.65rem; padding: 0.15rem 0.3rem;">開示</a><a href="${baseUrl}/performance" target="_blank" class="badge bg-light text-dark border text-decoration-none" title="業績詳細" style="font-size: 0.65rem; padding: 0.15rem 0.3rem;">業績</a></div>`;
            const isDiamond = jpStock.is_diamond || (jpStock.buy_signal && jpStock.buy_signal.is_diamond);
            if (jpStock.buy_signal) nameHtml += renderBuySignalBadge(jpStock.buy_signal, isDiamond);
            if (jpStock.sell_signal) nameHtml += renderSellSignalBadge(jpStock.sell_signal, isDiamond);
            createCell(nameHtml + `</div>`);
            createCell(jpStock.industry || 'N/A');
            createCell(renderScoreAsStars(jpStock.score, jpStock.score_details, jpStock.asset_type));
            createCell(jpStock.price, 'numeric');
            createCell(`${jpStock.change} (${(jpStock.change_percent && jpStock.change_percent !== 'N/A') ? jpStock.change_percent + '%' : 'N/A'})`, 'numeric');
            createCell(formatMarketCap(jpStock.market_cap), 'numeric');
            createCell(jpStock.per, 'numeric ' + getHighlightClass('per', jpStock.per, jpStock.asset_type));
            createCell(jpStock.pbr, 'numeric ' + getHighlightClass('pbr', jpStock.pbr, jpStock.asset_type));
            createCell(jpStock.roe, 'numeric ' + getHighlightClass('roe', jpStock.roe, jpStock.asset_type));
            createCell(jpStock.yield, 'numeric ' + getHighlightClass('yield', jpStock.yield, jpStock.asset_type));
            createCell((jpStock.fibonacci && jpStock.fibonacci.retracement !== undefined) ? `${jpStock.fibonacci.retracement.toFixed(1)}%` : '-', 'numeric');
            createCell((jpStock.rci_26 !== undefined && jpStock.rci_26 !== null) ? `${jpStock.rci_26.toFixed(1)}%` : '-', 'numeric');
            createCellWithTooltip(jpStock.consecutive_increase_years > 0 ? `<span class="increase-badge">${jpStock.consecutive_increase_years}年連続</span>` : '-', 'badge-cell', formatDividendHistory(jpStock.dividend_history), `${baseUrl}/dividend`);
            createCell(jpStock.settlement_month || 'N/A', 'numeric');
            const manageBtn = document.createElement('button'); manageBtn.textContent = '管理'; manageBtn.className = 'manage-btn'; manageBtn.dataset.code = jpStock.code;
            row.insertCell().appendChild(manageBtn);
        });
    }

    function renderFundTable(funds) {
        const tableBody = document.querySelector('#portfolio-table-investment_trust tbody');
        if (funds.length === 0 && refreshAllButton.disabled) {
            const html = Array(5).fill(0).map(() => `<tr class="skeleton-row">${Array(8).fill(0).map(() => `<td><div class="skeleton skeleton-cell"></div></td>`).join('')}</tr>`).join('');
            tableBody.innerHTML = html;
            return;
        }
        tableBody.innerHTML = '';
        if (!funds || funds.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;">登録されている投資信託はありません。</td></tr>`;
            return;
        }
        funds.forEach(fund => {
            const row = tableBody.insertRow();
            row.dataset.code = fund.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell(); cell.innerHTML = html;
                if (html === 'N/A' || html === '--' || html === '-') cell.className = (className ? className + ' ' : '') + 'na-value';
                else if (className) cell.className = className;
                return cell;
            };
            if (fund.error) {
                row.className = 'error-row'; row.title = fund.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${fund.code}" disabled>`);
                createCell(fund.code, 'numeric'); createCell(fund.error, 'error-message').colSpan = 5;
                createCell(`<button class="manage-btn" data-code="${fund.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${fund.code}">`);
            createCell(fund.code, 'numeric'); createCell(`<a href="https://finance.yahoo.co.jp/quote/${fund.code}" target="_blank">${fund.name}</a>`);
            createCell(fund.price, 'numeric');
            createCell(`${fund.change} (${(fund.change_percent && fund.change_percent !== 'N/A') ? fund.change_percent + '%' : 'N/A'})`, 'numeric');
            createCell(fund.net_assets, 'numeric'); createCell(fund.trust_fee, 'numeric');
            const manageBtn = document.createElement('button'); manageBtn.textContent = '管理'; manageBtn.className = 'manage-btn'; manageBtn.dataset.code = fund.code;
            row.insertCell().appendChild(manageBtn);
        });
    }

    function renderUSTable(usStocks) {
        const tableBody = document.querySelector('#portfolio-table-us_stock tbody');
        if (usStocks.length === 0 && refreshAllButton.disabled) {
            const html = Array(5).fill(0).map(() => `<tr class="skeleton-row">${Array(11).fill(0).map(() => `<td><div class="skeleton skeleton-cell"></div></td>`).join('')}</tr>`).join('');
            tableBody.innerHTML = html;
            return;
        }
        tableBody.innerHTML = '';
        if (!usStocks || usStocks.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="10" style="text-align:center;">登録されている米国株式はありません。</td></tr>`;
            return;
        }
        usStocks.forEach(usStock => {
            const row = tableBody.insertRow();
            row.dataset.code = usStock.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell(); cell.innerHTML = html;
                if (html === 'N/A' || html === '--' || html === '-') cell.className = (className ? className + ' ' : '') + 'na-value';
                else if (className) cell.className = className;
                return cell;
            };
            if (usStock.error) {
                row.className = 'error-row'; row.title = usStock.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${usStock.code}" disabled>`);
                createCell(usStock.code, 'numeric'); createCell(usStock.error, 'error-message').colSpan = 7;
                createCell(`<button class="manage-btn" data-code="${usStock.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${usStock.code}">`);
            createCell(usStock.code, 'numeric'); createCell(`<a href="https://finance.yahoo.co.jp/quote/${usStock.code}" target="_blank">${usStock.name}</a>`);
            createCell(usStock.market || 'N/A'); createCell(usStock.price, 'numeric');
            createCell(`${usStock.change} (${(usStock.change_percent && usStock.change_percent !== 'N/A') ? usStock.change_percent + '%' : 'N/A'})`, 'numeric');
            createCell(formatMarketCap(usStock.market_cap), 'numeric');
            createCell(usStock.per, 'numeric ' + getHighlightClass('per', usStock.per, usStock.asset_type));
            createCell(usStock.yield, 'numeric ' + getHighlightClass('yield', usStock.yield, usStock.asset_type));
            createCell(usStock.settlement_month || 'N/A', 'numeric');
            const manageBtn = document.createElement('button'); manageBtn.textContent = '管理'; manageBtn.className = 'manage-btn'; manageBtn.dataset.code = usStock.code;
            row.insertCell().appendChild(manageBtn);
        });
    }

    function showAlert(message, type = 'danger', isHtml = false) {
        const alert = document.createElement('div'); alert.className = `alert alert-${type}`;
        if (isHtml) alert.innerHTML = message; else alert.textContent = message;
        alertContainer.appendChild(alert);
        requestAnimationFrame(() => alert.classList.add('show'));
        setTimeout(() => {
            alert.classList.remove('show'); alert.classList.add('hide');
            alert.addEventListener('transitionend', () => alert.remove());
        }, 10000);
    }

    const formatNumber = (num, fractionDigits = 0) => {
        const parsedNum = parseFloat(num);
        if (isNaN(parsedNum)) return 'N/A';
        return parsedNum.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
    };

    function sortAssets(data) {
        data.sort((a, b) => {
            let valA = a[currentSort.key], valB = b[currentSort.key];
            const parseValue = (v) => {
                if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '') return -Infinity;
                if (typeof v === 'object' && v !== null && v.retracement !== undefined) return v.retracement;
                if (typeof v === 'string') { const num = parseFloat(v.replace(/,/g, '').replace(/%|倍|円/g, '')); return isNaN(num) ? v : num; }
                return v;
            };
            const parsedA = parseValue(valA), parsedB = parseValue(valB);
            if (typeof parsedA === 'number' && typeof parsedB === 'number') return currentSort.order === 'asc' ? parsedA - parsedB : parsedB - parsedA;
            return currentSort.order === 'asc' ? String(parsedA).localeCompare(String(parsedB)) : String(parsedB).localeCompare(String(parsedA));
        });
    }
    function updateSortHeaders() {
        document.querySelectorAll(`.tab-content.active .sortable`).forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) header.classList.add('sort-active', `sort-${currentSort.order}`);
        });
    }

    function updateDeleteSelectedButtonState() {
        deleteSelectedStocksButton.disabled = document.querySelectorAll(`#${activeTab} .asset-checkbox:checked`).length === 0;
    }
    function formatMarketCap(value) {
        if (value === 'N/A' || !value || value === '--') return 'N/A';
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
        if (isNaN(num)) return 'N/A';
        if (num >= 1e12) return `${(num / 1e12).toFixed(2)}兆円`;
        if (num >= 1e8) return `${(num / 1e8).toFixed(2)}億円`;
        return `${num.toLocaleString()}円`;
    }
    function formatDividendHistory(history) {
        if (!history || Object.keys(history).length === 0) return 'N/A';
        return Object.keys(history).sort((a, b) => b - a).map(year => `${year}年: ${history[year]}円`).join(' | ');
    }
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
        if (signal.level === 2) {
            themeClass = 'theme-sell-lv2';
        } else if (signal.level === 1) {
            themeClass = 'theme-sell-lv1';
        } else {
            themeClass = 'theme-sell-lv3';
        }

        const title = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${signal.reasons.join('\n')}`;
        // 売却時はisDiamond属性があったとしても、アイコンに含める程度に留め、背景色はthemeClassに委ねる
        const label = (isDiamond ? '💎 ' : '') + signal.label;
        return `<span class="signal-badge-base ${themeClass}" title="${title}"><span class="signal-badge-text"><span class="buy-signal-icon-inner">${signal.icon}</span>${label}</span></span>`;
    }

    function renderScoreAsStars(score, details, assetType) {
        if (assetType !== 'jp_stock' || score === undefined || score === null) return 'N/A';
        if (score === -1) return `<span class="score-na" title="評価指標なし">N/A</span>`;
        const trendScore = (details.trend_short || 0) + (details.trend_medium || 0) + (details.trend_signal || 0) + (details.fibonacci || 0) + (details.rci || 0);
        const fundamentalScore = score - trendScore;
        let html = '';
        for (let i = 0; i < 16; i++) {
            if (i === 8) html += '<br>';
            const cls = i < fundamentalScore ? 'score-fundamental' : (i < score ? 'score-trend' : 'score-empty');
            html += `<span class="${cls}">${i < score ? '★' : '☆'}</span>`;
        }
        const tooltip = `合計: ${score}/15 (PER: ${details.per||0}, PBR: ${details.pbr||0}, ROE: ${details.roe||0}, 利回り: ${details.yield||0}, 連続増配: ${details.consecutive_increase||0}, テクニカル: ${trendScore})`;
        const warning = details.is_reliable === false ? `<span class="score-unreliable-icon" title="不完全: ${details.missing_items.join(', ')}">⚠️</span>` : '';
        return `<span class="score-container" title="${tooltip}">${html}</span>${warning}`;
    }
    function getHighlightClass(key, value, assetType) {
        if (assetType !== 'jp_stock') return '';
        const rules = highlightRules[key]; if (!rules || !value || value === 'N/A') return '';
        const num = parseFloat(String(value).replace(/[^0-9.-]/g, '')); if (isNaN(num)) return '';
        if (key === 'yield' || key === 'roe') { if (num >= rules.undervalued) return 'undervalued'; }
        else { if (num <= rules.undervalued) return 'undervalued'; if (num >= rules.overvalued) return 'overvalued'; }
        return '';
    }
    function renderRecentStocksList(codes) {
        if (!recentStocksList) return;
        recentStocksList.innerHTML = codes.length ? '' : '<li>最近追加した資産はありません。</li>';
        codes.forEach(code => {
            const li = document.createElement('li'); li.className = 'recent-stock-item'; li.textContent = code;
            li.addEventListener('click', () => { assetCodeInput.value = code; });
            recentStocksList.appendChild(li);
        });
    }

    function openManagementModal(code) {
        currentManagingCode = code;
        const asset = allAssetsData.find(s => s.code === code); if (!asset) return;
        modalTitle.textContent = `保有情報管理 (${asset.code} ${asset.name})`;
        renderHoldingsList(asset.holdings, asset.asset_type); hideHoldingForm();
        modalOverlay.classList.remove('hidden');
    }
    function renderHoldingsList(holdings, assetType) {
        holdingsListContainer.innerHTML = '';
        if (!holdings || holdings.length === 0) { holdingsListContainer.innerHTML = '<p>保有情報なし</p>'; return; }
        holdings.forEach(h => {
            const item = document.createElement('div'); item.className = 'holding-item';
            item.innerHTML = `<div class="holding-info"><span class="account-type">${h.account_type}</span><span>取得単価: ${formatNumber(h.purchase_price, 2)}円</span><span>数量: ${formatNumber(h.quantity, assetType === 'investment_trust' ? 6 : 0)}</span></div><div class="holding-actions"><button class="btn-sm btn-edit" data-holding-id="${h.id}">編集</button><button class="btn-sm btn-delete-holding" data-holding-id="${h.id}">削除</button></div>`;
            holdingsListContainer.appendChild(item);
        });
    }
    function showHoldingForm(holding = null) {
        holdingForm.reset();
        accountTypeSelect.innerHTML = accountTypes.map(t => `<option value="${t}">${t}</option>`).join('');
        securityCompanySelect.innerHTML = '<option value="">(未選択)</option>' + securityCompanies.map(c => `<option value="${c}">${c}</option>`).join('');
        if (holding) {
            holdingFormTitle.textContent = '保有情報の編集'; holdingIdInput.value = holding.id; accountTypeSelect.value = holding.account_type;
            purchasePriceInput.value = holding.purchase_price; quantityInput.value = holding.quantity; securityCompanySelect.value = holding.security_company || ""; memoInput.value = holding.memo || "";
        } else { holdingFormTitle.textContent = '保有情報の新規追加'; holdingIdInput.value = ''; }
        holdingFormContainer.classList.remove('hidden');
    }
    function hideHoldingForm() { holdingFormContainer.classList.add('hidden'); }
    async function handleHoldingFormSubmit(e) {
        e.preventDefault();
        const data = { account_type: accountTypeSelect.value, purchase_price: parseFloat(purchasePriceInput.value), quantity: parseFloat(quantityInput.value), security_company: securityCompanySelect.value || null, memo: memoInput.value || null };
        const url = holdingIdInput.value ? `/api/holdings/${holdingIdInput.value}` : `/api/stocks/${currentManagingCode}/holdings`;
        try {
            const res = await fetch(url, { method: holdingIdInput.value ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
            if (!res.ok) throw new Error('保存失敗');
            showAlert('保有情報を保存しました。', 'success'); window.appState.clearState(); await fetchAndRenderAllData(true);
            const asset = allAssetsData.find(a => a.code === currentManagingCode); if (asset) renderHoldingsList(asset.holdings, asset.asset_type);
            hideHoldingForm();
        } catch (err) { showAlert(err.message, 'danger'); }
    }
    async function handleHoldingDelete(id) {
        if (!confirm('削除しますか？')) return;
        try {
            const res = await fetch(`/api/holdings/${id}`, { method: 'DELETE' }); if (!res.ok) throw new Error('削除失敗');
            showAlert('削除しました。', 'success'); window.appState.clearState(); await fetchAndRenderAllData(true);
            const asset = allAssetsData.find(a => a.code === currentManagingCode); if (asset) renderHoldingsList(asset.holdings, asset.asset_type);
        } catch (err) { showAlert(err.message, 'danger'); }
    }
    function closeModal() { modalOverlay.classList.add('hidden'); currentManagingCode = null; }

    // --- イベントリスナー ---
    addAssetForm.addEventListener('submit', async (e) => {
        e.preventDefault(); const code = assetCodeInput.value.trim(); if (!code) return;
        try {
            const res = await fetch('/api/stocks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
            const d = await res.json(); showAlert(d.message, d.status === 'success' ? 'success' : (d.status === 'exists' ? 'warning' : 'danger'));
            if (d.status === 'success') { window.appState.clearState(); await fetchAndRenderAllData(true); }
            assetCodeInput.value = '';
        } catch (err) { showAlert('追加エラー', 'danger'); }
    });

    document.querySelectorAll('.portfolio-table tbody').forEach(tbody => tbody.addEventListener('click', (e) => { if (e.target.classList.contains('manage-btn')) openManagementModal(e.target.dataset.code); }));
    document.querySelectorAll('.portfolio-table thead').forEach(thead => thead.addEventListener('click', (e) => {
        const h = e.target.closest('.sortable'); if (!h) return;
        if (currentSort.key === h.dataset.key) currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
        else { currentSort.key = h.dataset.key; currentSort.order = 'asc'; }
        filterAndRender();
    }));

    tabNav.addEventListener('click', (e) => {
        if (e.target.classList.contains('tab-link')) {
            activeTab = e.target.dataset.tab;
            document.querySelector('.tab-link.active').classList.remove('active'); e.target.classList.add('active');
            document.querySelector('.tab-content.active').classList.remove('active'); document.getElementById(activeTab).classList.add('active');
            filterAndRender();
        }
    });

    downloadCsvButton.addEventListener('click', () => { window.location.href = '/api/stocks/csv'; });
    filterInput.addEventListener('input', filterAndRender);
    [showOnlyManagedAssetsCheckbox, showOnlyAttentionAssetsCheckbox, showOnlyOpportunityAssetsCheckbox, showOnlyOverheatedAssetsCheckbox].forEach(c => c.addEventListener('input', filterAndRender));
    
    document.querySelectorAll('.select-all-assets').forEach(checkbox => checkbox.addEventListener('change', (e) => {
        document.querySelectorAll(`#portfolio-table-${e.target.dataset.assetType} .asset-checkbox:not(:disabled)`).forEach(cb => cb.checked = e.target.checked);
        updateDeleteSelectedButtonState();
    }));

    document.querySelectorAll('.portfolio-table tbody').forEach(tbody => tbody.addEventListener('change', (e) => {
        if (e.target.classList.contains('asset-checkbox')) {
            const tableId = e.target.closest('.portfolio-table').id;
            const all = document.querySelectorAll(`#${tableId} .asset-checkbox:not(:disabled)`);
            const checked = document.querySelectorAll(`#${tableId} .asset-checkbox:checked:not(:disabled)`);
            document.querySelector(`.select-all-assets[data-asset-type="${activeTab}"]`).checked = all.length > 0 && all.length === checked.length;
            updateDeleteSelectedButtonState();
        }
    }));

    deleteSelectedStocksButton.addEventListener('click', async () => {
        const codes = Array.from(document.querySelectorAll(`#${activeTab} .asset-checkbox:checked`)).map(cb => cb.dataset.code);
        if (codes.length === 0 || !confirm(`${codes.length}件削除しますか？`)) return;
        try {
            const res = await fetch('/api/stocks/bulk-delete', { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ codes }) });
            if (!res.ok) throw new Error('削除失敗');
            showAlert('削除しました', 'success'); window.appState.clearState(); await fetchAndRenderAllData(true);
        } catch (err) { showAlert(err.message, 'danger'); }
    });

    refreshAllButton.addEventListener('click', () => fetchAndRenderAllData(true));
    addNewHoldingBtn.addEventListener('click', () => showHoldingForm());
    holdingForm.addEventListener('submit', handleHoldingFormSubmit);
    holdingFormCancelBtn.addEventListener('click', hideHoldingForm);
    holdingsListContainer.addEventListener('click', (e) => {
        if (e.target.classList.contains('btn-edit')) {
            const h = allAssetsData.find(s => s.code === currentManagingCode).holdings.find(h => h.id === e.target.dataset.holdingId);
            showHoldingForm(h);
        } else if (e.target.classList.contains('btn-delete-holding')) handleHoldingDelete(e.target.dataset.holdingId);
    });
    modalCloseBtn.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (e) => { if (e.target === modalOverlay) closeModal(); });
    window.addEventListener('pagehide', () => { if (fetchController) fetchController.abort(); });

    // --- 初期実行 ---
    const initialCachedState = window.appState.getState('portfolio');
    if (initialCachedState) {
        allAssetsData = Array.isArray(initialCachedState) ? initialCachedState : (initialCachedState.data || []);
        if (initialCachedState.metadata) renderUpdateReport(initialCachedState.metadata);
        filterAndRender();
    } else { loadAssetsFromStorage(); }
    fetchAndRenderAllData(false);
});
