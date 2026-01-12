document.addEventListener('DOMContentLoaded', () => {
    // --- DOM要素の取得 ---
    const addAssetForm = document.getElementById('add-asset-form');
    const assetCodeInput = document.getElementById('asset-code-input');
    const downloadCsvButton = document.getElementById('download-csv-button');
    const refreshAllButton = document.getElementById('refresh-all-button');
    const alertContainer = document.getElementById('alert-container');
    const deleteSelectedStocksButton = document.getElementById('delete-selected-stocks-button');
    const recentStocksList = document.getElementById('recent-stocks-list');
    const filterInput = document.getElementById('filter-input');
    const showOnlyManagedAssetsCheckbox = document.getElementById('show-only-managed-assets-checkbox');
    const tabNav = document.querySelector('.tab-nav');

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

    // --- グローバル変数 ---
    let allAssetsData = [];
    let accountTypes = [];
    let highlightRules = {};
    let currentSort = { key: 'code', order: 'asc' };
    let currentManagingCode = null;
    let activeTab = 'jp_stock';
    const ASSETS_STORAGE_KEY = 'jpStockPortfolioAssets';
    let fetchController = null; // AbortControllerを保持

    // --- データ取得とレンダリング ---
    async function fetchAndRenderAllData(force = false) {
        if (fetchController) {
            fetchController.abort(); // 既存のリクエストをキャンセル
        }
        fetchController = new AbortController();
        const signal = fetchController.signal;

        if (!force && !window.appState.canFetch()) {
            const cachedData = window.appState.getState('portfolio');
            if (cachedData) {
                allAssetsData = cachedData;
                filterAndRender();
            }
            return;
        }

        refreshAllButton.disabled = true;
        refreshAllButton.textContent = '更新中...';

        try {
            const apiFetch = (url) => fetch(url, { signal }).then(handleApiResponse);

            const [assets, rules, recent, accTypes] = await Promise.all([
                apiFetch('/api/stocks'),
                apiFetch('/api/highlight-rules'),
                apiFetch('/api/recent-stocks'),
                apiFetch('/api/account-types')
            ]);

            allAssetsData = assets;
            highlightRules = rules;
            accountTypes = accTypes;

            window.appState.updateState('portfolio', allAssetsData);
            window.appState.updateTimestamp();
            saveAssetsToStorage(); 
            
            renderRecentStocksList(recent);
            filterAndRender();
            if (force) {
                showAlert('ポートフォリオを更新しました。', 'success');
            }

        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Main page fetch aborted.');
            } else {
                console.error('Data fetch error:', error);
                showAlert(`データ更新に失敗しました: ${error.message}`, 'danger');
                loadAssetsFromStorage();
            }
        } finally {
            refreshAllButton.disabled = false;
            refreshAllButton.textContent = '全件更新';
        }
    }
    
    async function handleApiResponse(response) {
        if (!response.ok) {
            let errorDetail = `HTTP error! status: ${response.status}`;
            try {
                const errorData = await response.json();
                errorDetail = errorData.detail || errorDetail;
            } catch (e) {
                // JSONのパースに失敗した場合
            }
            throw new Error(errorDetail);
        }
        return response.json();
    }


    // --- ストレージ関連 ---
    function saveAssetsToStorage() {
        localStorage.setItem(ASSETS_STORAGE_KEY, JSON.stringify(allAssetsData));
    }

    function loadAssetsFromStorage() {
        const storedAssets = localStorage.getItem(ASSETS_STORAGE_KEY);
        if (storedAssets) {
            allAssetsData = JSON.parse(storedAssets);
            filterAndRender();
        }
    }

    // --- レンダリング関連 ---
    function filterAndRender() {
        const filterText = filterInput.value.toLowerCase();
        const showOnlyManaged = showOnlyManagedAssetsCheckbox.checked;
        let filteredAssets = allAssetsData.filter(asset => asset.asset_type === activeTab);

        if (showOnlyManaged) {
            filteredAssets = filteredAssets.filter(asset => asset.holdings && asset.holdings.length > 0);
        }

        if (filterText) {
            filteredAssets = filteredAssets.filter(asset =>
                String(asset.code).toLowerCase().includes(filterText) ||
                String(asset.name || '').toLowerCase().includes(filterText)
            );
        }
        sortAssets(filteredAssets);
        if (activeTab === 'jp_stock') {
            renderStockTable(filteredAssets);
        } else if (activeTab === 'investment_trust') {
            renderFundTable(filteredAssets);
        } else if (activeTab === 'us_stock') {
            renderUSTable(filteredAssets);
        }
        updateSortHeaders();
        updateDeleteSelectedButtonState();
    }

    function renderStockTable(stocks) {
        const tableBody = document.querySelector('#portfolio-table-jp_stock tbody');
        tableBody.innerHTML = '';
        if (!stocks || stocks.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="15" style="text-align:center;">登録されている銘柄はありません。</td></tr>`;
            return;
        }
        stocks.forEach(jpStock => {
            const row = tableBody.insertRow();
            row.dataset.code = jpStock.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell();
                cell.innerHTML = html;
                if (className) cell.className = className;
                return cell;
            };
            const createCellWithTooltip = (html, className = '', tooltipText = '', externalLink = '') => {
                const cell = createCell(html, className);
                if (tooltipText) cell.title = tooltipText;
                if (externalLink) {
                    cell.style.cursor = 'pointer';
                    cell.addEventListener('click', () => window.open(externalLink, '_blank'));
                }
                return cell;
            };

            if (jpStock.error) {
                row.className = 'error-row';
                row.title = jpStock.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${jpStock.code}" disabled>`);
                createCell(jpStock.code);
                const errorCell = createCell(jpStock.error, 'error-message');
                errorCell.colSpan = 12; // colspanを調整
                createCell(`<button class="manage-btn" data-code="${jpStock.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${jpStock.code}">`);
            createCell(jpStock.code);
            createCell(`<a href="https://finance.yahoo.co.jp/quote/${jpStock.code}.T" target="_blank">${jpStock.name}</a>`);
            createCell(jpStock.industry || 'N/A');
            createCell(renderScoreAsStars(jpStock.score, jpStock.score_details, jpStock.asset_type));
            createCell(jpStock.price);
            createCell(`${jpStock.change} (${jpStock.change_percent || 'N/A'})`);
            createCell(formatMarketCap(jpStock.market_cap));
            createCell(jpStock.per, getHighlightClass('per', jpStock.per, jpStock.asset_type));
            createCell(jpStock.pbr, getHighlightClass('pbr', jpStock.pbr, jpStock.asset_type));
            createCell(jpStock.roe, getHighlightClass('roe', jpStock.roe, jpStock.asset_type));
            createCell(jpStock.yield, getHighlightClass('yield', jpStock.yield, jpStock.asset_type));
            
            const tooltipContent = formatDividendHistory(jpStock.dividend_history);
            const externalLink = `https://finance.yahoo.co.jp/quote/${jpStock.code}.T/dividend`;
            createCellWithTooltip(jpStock.consecutive_increase_years > 0 ? `<span class="increase-badge">${jpStock.consecutive_increase_years}年連続</span>` : '-', 'badge-cell', tooltipContent, externalLink);
            
            createCell(jpStock.settlement_month || 'N/A');

            const manageCell = document.createElement('td');
            const manageButton = document.createElement('button');
            manageButton.textContent = '管理';
            manageButton.className = 'manage-btn';
            manageButton.dataset.code = jpStock.code;
            manageCell.appendChild(manageButton);
            row.appendChild(manageCell);
        });
    }

    function renderFundTable(funds) {
        const tableBody = document.querySelector('#portfolio-table-investment_trust tbody');
        tableBody.innerHTML = '';
        if (!funds || funds.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;">登録されている投資信託はありません。</td></tr>`;
            return;
        }
        funds.forEach(fund => {
            const row = tableBody.insertRow();
            row.dataset.code = fund.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell();
                cell.innerHTML = html;
                if (className) cell.className = className;
                return cell;
            };
            if (fund.error) {
                row.className = 'error-row';
                row.title = fund.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${fund.code}" disabled>`);
                createCell(fund.code);
                const errorCell = createCell(fund.error, 'error-message');
                errorCell.colSpan = 5;
                createCell(`<button class="manage-btn" data-code="${fund.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${fund.code}">`);
            createCell(fund.code);
            createCell(`<a href="https://finance.yahoo.co.jp/quote/${fund.code}" target="_blank">${fund.name}</a>`);
            createCell(fund.price);
            createCell(`${fund.change} (${fund.change_percent || 'N/A'})`);
            createCell(fund.net_assets);
            createCell(fund.trust_fee);
            const manageCell = document.createElement('td');
            const manageButton = document.createElement('button');
            manageButton.textContent = '管理';
            manageButton.className = 'manage-btn';
            manageButton.dataset.code = fund.code;
            manageCell.appendChild(manageButton);
            row.appendChild(manageCell);
        });
    }

    function renderUSTable(usStocks) {
        const tableBody = document.querySelector('#portfolio-table-us_stock tbody');
        tableBody.innerHTML = '';
        if (!usStocks || usStocks.length === 0) {
            tableBody.innerHTML = `<tr><td colspan="10" style="text-align:center;">登録されている米国株式はありません。</td></tr>`;
            return;
        }
        usStocks.forEach(usStock => {
            const row = tableBody.insertRow();
            row.dataset.code = usStock.code;
            const createCell = (html, className = '') => {
                const cell = row.insertCell();
                cell.innerHTML = html;
                if (className) cell.className = className;
                return cell;
            };
            if (usStock.error) {
                row.className = 'error-row';
                row.title = usStock.error;
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${usStock.code}" disabled>`);
                createCell(usStock.code);
                const errorCell = createCell(usStock.error, 'error-message');
                errorCell.colSpan = 7;
                createCell(`<button class="manage-btn" data-code="${usStock.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${usStock.code}">`);
            createCell(usStock.code);
            createCell(`<a href="https://finance.yahoo.co.jp/quote/${usStock.code}" target="_blank">${usStock.name}</a>`);
            createCell(usStock.market || 'N/A');
            createCell(usStock.price);
            createCell(`${usStock.change} (${usStock.change_percent || 'N/A'})`);
            createCell(formatMarketCap(usStock.market_cap));
            createCell(usStock.per, getHighlightClass('per', usStock.per, usStock.asset_type));
            createCell(usStock.yield, getHighlightClass('yield', usStock.yield, usStock.asset_type));
            createCell(usStock.settlement_month || 'N/A');

            const manageCell = document.createElement('td');
            const manageButton = document.createElement('button');
            manageButton.textContent = '管理';
            manageButton.className = 'manage-btn';
            manageButton.dataset.code = usStock.code;
            manageCell.appendChild(manageButton);
            row.appendChild(manageCell);
        });
    }

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

    const formatNumber = (num, fractionDigits = 0) => {
        const parsedNum = parseFloat(num);
        if (parsedNum === null || parsedNum === undefined || isNaN(parsedNum)) return 'N/A';
        return parsedNum.toLocaleString(undefined, { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits });
    };

    function sortAssets(data) {
        data.sort((a, b) => {
            let valA = a[currentSort.key], valB = b[currentSort.key];
            const parseValue = (v) => {
                if (v === undefined || v === null || v === 'N/A' || v === '--' || v === '') return -Infinity;
                if (typeof v === 'string') {
                    const num = parseFloat(v.replace(/,/g, '').replace(/%|倍|円/g, ''));
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
        document.querySelectorAll(`.tab-content.active .sortable`).forEach(header => {
            header.classList.remove('sort-active', 'sort-asc', 'sort-desc');
            if (header.dataset.key === currentSort.key) {
                header.classList.add('sort-active', `sort-${currentSort.order}`);
            }
        });
    }

    function updateDeleteSelectedButtonState() {
        const checkedCount = document.querySelectorAll(`#${activeTab} .asset-checkbox:checked`).length;
        deleteSelectedStocksButton.disabled = checkedCount === 0;
    }
    function formatMarketCap(value) {
        if (value === 'N/A' || value === null || value === undefined || value === '--') return 'N/A';
        const num = typeof value === 'string' ? parseFloat(value.replace(/,/g, '')) : value;
        if (isNaN(num)) return 'N/A';
        const trillion = 1e12, oku = 1e8;
        if (num >= trillion) return `${(num / trillion).toFixed(2)}兆円`;
        if (num >= oku) return `${(num / oku).toFixed(2)}億円`;
        return `${num.toLocaleString()}円`;
    }
    function formatDividendHistory(history) {
        if (!history || Object.keys(history).length === 0) return 'N/A';
        return Object.keys(history).sort((a, b) => b - a).map(year => `${year}年: ${history[year]}円`).join(' | ');
    }
    function renderScoreAsStars(score, details, assetType) {
        if (assetType !== 'jp_stock') return 'N/A';
        if (score === -1) return `<span class="score-na" title="評価指標なし">N/A</span>`;
        if (score === undefined || score === null) return 'N/A';
        let stars = '★'.repeat(Math.min(score, 5)) + '☆'.repeat(5 - Math.min(score, 5));
        stars += '<br>' + '★'.repeat(Math.max(0, score - 5)) + '☆'.repeat(5 - Math.max(0, score - 5));
        const tooltip = `合計: ${score}/10 (PER: ${details.per||0}/2, PBR: ${details.pbr||0}/2, ROE: ${details.roe||0}/2, 利回り: ${details.yield||0}/2, 連続増配: ${details.consecutive_increase||0}/2)`;
        return `<span class="score" title="${tooltip}">${stars}</span>`;
    }
    function getHighlightClass(key, value, assetType) {
        if (assetType !== 'jp_stock') return '';
        const rules = highlightRules[key];
        if (!rules || value === 'N/A' || value === null || value === undefined || value === '--') return '';
        const numericValue = parseFloat(String(value).replace(/[^0-9.-]/g, ''));
        if (isNaN(numericValue)) return '';
        if (key === 'yield' || key === 'roe') {
            if (rules.undervalued !== undefined && numericValue >= rules.undervalued) return 'undervalued';
        } else {
            if (rules.undervalued !== undefined && numericValue <= rules.undervalued) return 'undervalued';
            if (rules.overvalued !== undefined && numericValue >= rules.overvalued) return 'overvalued';
        }
        return '';
    }
    function renderRecentStocksList(codes) {
        if (!recentStocksList) return;
        recentStocksList.innerHTML = codes.length ? '' : '<li>最近追加した資産はありません。</li>';
        codes.forEach(code => {
            const li = document.createElement('li');
            li.className = 'recent-stock-item';
            li.textContent = code;
            li.addEventListener('click', () => { assetCodeInput.value = code; });
            recentStocksList.appendChild(li);
        });
    }

    // --- モーダル関連 ---
    function openManagementModal(code) {
        currentManagingCode = code;
        const asset = allAssetsData.find(s => s.code === code);
        if (!asset) return;
        modalTitle.textContent = `保有情報管理 (${asset.code} ${asset.name})`;
        renderHoldingsList(asset.holdings, asset.asset_type);
        hideHoldingForm();
        modalOverlay.classList.remove('hidden');
    }
    function renderHoldingsList(holdings, assetType) {
        const isFund = assetType === 'investment_trust';
        const quantityDigits = isFund ? 6 : 0;

        holdingsListContainer.innerHTML = '';
        if (!holdings || holdings.length === 0) {
            holdingsListContainer.innerHTML = '<p>この資産の保有情報はありません。</p>';
            return;
        }
        holdings.forEach(h => {
            const item = document.createElement('div');
            item.className = 'holding-item';
            item.innerHTML = `
                <div class="holding-info">
                    <span class="account-type">${h.account_type}</span>
                    <span>取得単価: ${formatNumber(h.purchase_price, 2)}円</span>
                    <span>数量: ${formatNumber(h.quantity, quantityDigits)}</span>
                </div>
                <div class="holding-actions">
                    <button class="btn-sm btn-edit" data-holding-id="${h.id}">編集</button>
                    <button class="btn-sm btn-delete-holding" data-holding-id="${h.id}">削除</button>
                </div>
            `;
            holdingsListContainer.appendChild(item);
        });
    }
    function showHoldingForm(holding = null) {
        holdingForm.reset();
        accountTypeSelect.innerHTML = accountTypes.map(t => `<option value="${t}">${t}</option>`).join('');
        if (holding) {
            holdingFormTitle.textContent = '保有情報の編集';
            holdingIdInput.value = holding.id;
            accountTypeSelect.value = holding.account_type;
            purchasePriceInput.value = holding.purchase_price;
            quantityInput.value = holding.quantity;
        } else {
            holdingFormTitle.textContent = '保有情報の新規追加';
            holdingIdInput.value = '';
        }
        holdingFormContainer.classList.remove('hidden');
    }
    function hideHoldingForm() { holdingFormContainer.classList.add('hidden'); }
    async function handleHoldingFormSubmit(event) {
        event.preventDefault();
        const holdingId = holdingIdInput.value;
        const data = {
            account_type: accountTypeSelect.value,
            purchase_price: parseFloat(purchasePriceInput.value),
            quantity: parseFloat(quantityInput.value)
        };
        const url = holdingId ? `/api/holdings/${holdingId}` : `/api/stocks/${currentManagingCode}/holdings`;
        const method = holdingId ? 'PUT' : 'POST';
        try {
            const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
            if (!response.ok) throw new Error((await response.json()).detail || '保存失敗');
            showAlert('保有情報を保存しました。', 'success');
            
            window.appState.clearState();
            
            // After clearing state, force a re-fetch.
            await fetchAndRenderAllData(true);
            
            // Find the updated asset in the newly fetched data
            const updatedAsset = allAssetsData.find(a => a.code === currentManagingCode);
            if (updatedAsset) {
                renderHoldingsList(updatedAsset.holdings, updatedAsset.asset_type);
            }
            hideHoldingForm();
        } catch (error) { showAlert(error.message, 'danger'); }
    }
    async function handleHoldingDelete(holdingId) {
        if (!confirm('この保有情報を削除しますか？')) return;
        try {
            const response = await fetch(`/api/holdings/${holdingId}`, { method: 'DELETE' });
            if (!response.ok) throw new Error('削除失敗');
            showAlert('保有情報を削除しました。', 'success');

            window.appState.clearState();
            
            // After clearing state, force a re-fetch.
            await fetchAndRenderAllData(true);

            // Find the updated asset in the newly fetched data
            const updatedAsset = allAssetsData.find(a => a.code === currentManagingCode);
            if (updatedAsset) {
                renderHoldingsList(updatedAsset.holdings, updatedAsset.asset_type);
            }
        } catch (error) { showAlert(error.message, 'danger'); }
    }
    function closeModal() { modalOverlay.classList.add('hidden'); currentManagingCode = null; }

    // --- イベントリスナー ---
    addAssetForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const code = assetCodeInput.value.trim();
        if (!code) return;
        try {
            const response = await fetch('/api/stocks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code }),
            });
            const data = await response.json();
            showAlert(data.message, data.status === 'success' ? 'success' : (data.status === 'exists' ? 'warning' : 'danger'));
            
            if (data.status === 'success') {
                window.appState.clearState();
                await fetchAndRenderAllData(true); // Force re-fetch
            }
            assetCodeInput.value = '';
        } catch (error) { showAlert('資産の追加中にエラーが発生しました。', 'danger'); }
    });

    document.querySelectorAll('.portfolio-table tbody').forEach(tbody => {
        tbody.addEventListener('click', (event) => {
            if (event.target.classList.contains('manage-btn')) {
                openManagementModal(event.target.dataset.code);
            }
        });
    });

    document.querySelectorAll('.portfolio-table thead').forEach(thead => {
        thead.addEventListener('click', (event) => {
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
    });

    tabNav.addEventListener('click', (event) => {
        if (event.target.classList.contains('tab-link')) {
            activeTab = event.target.dataset.tab;
            document.querySelector('.tab-link.active').classList.remove('active');
            event.target.classList.add('active');
            document.querySelector('.tab-content.active').classList.remove('active');
            document.getElementById(activeTab).classList.add('active');
            filterAndRender();
        }
    });

    downloadCsvButton.addEventListener('click', () => { window.location.href = '/api/stocks/csv'; });
    filterInput.addEventListener('input', filterAndRender);
    showOnlyManagedAssetsCheckbox.addEventListener('input', filterAndRender);
    
    document.querySelectorAll('.select-all-assets').forEach(checkbox => {
        checkbox.addEventListener('change', (event) => {
            const assetType = event.target.dataset.assetType;
            document.querySelectorAll(`#portfolio-table-${assetType} .asset-checkbox:not(:disabled)`).forEach(cb => {
                cb.checked = event.target.checked;
            });
            updateDeleteSelectedButtonState();
        });
    });

    document.querySelectorAll('.portfolio-table tbody').forEach(tbody => {
        tbody.addEventListener('change', (event) => {
            if (event.target.classList.contains('asset-checkbox')) {
                const tableId = event.target.closest('.portfolio-table').id;
                const all = document.querySelectorAll(`#${tableId} .asset-checkbox:not(:disabled)`);
                const checked = document.querySelectorAll(`#${tableId} .asset-checkbox:checked:not(:disabled)`);
                const selectAllCheckbox = document.querySelector(`.select-all-assets[data-asset-type="${activeTab}"]`);
                selectAllCheckbox.checked = all.length > 0 && all.length === checked.length;
                updateDeleteSelectedButtonState();
            }
        });
    });

    deleteSelectedStocksButton.addEventListener('click', async () => {
        const codesToDelete = Array.from(document.querySelectorAll(`#${activeTab} .asset-checkbox:checked`)).map(cb => cb.dataset.code);
        if (codesToDelete.length === 0 || !confirm(`選択された ${codesToDelete.length} 件の資産を削除しますか？`)) return;
        try {
            const response = await fetch('/api/stocks/bulk-delete', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ codes: codesToDelete }),
            });
            if (!response.ok) throw new Error((await response.json()).detail || '一括削除失敗');
            showAlert(`${codesToDelete.length} 件の銘柄情報を削除しました。`, 'success');
            
            window.appState.clearState();
            await fetchAndRenderAllData(true); // Force re-fetch
        } catch (error) { showAlert(error.message, 'danger'); }
    });

    refreshAllButton.addEventListener('click', () => fetchAndRenderAllData(true));

    // モーダルイベント
    addNewHoldingBtn.addEventListener('click', () => showHoldingForm());
    holdingForm.addEventListener('submit', handleHoldingFormSubmit);
    holdingFormCancelBtn.addEventListener('click', hideHoldingForm);
    holdingsListContainer.addEventListener('click', (event) => {
        const target = event.target;
        if (target.classList.contains('btn-edit')) {
            const holdingId = target.dataset.holdingId;
            const asset = allAssetsData.find(s => s.code === currentManagingCode);
            const holding = asset.holdings.find(h => h.id === holdingId);
            showHoldingForm(holding);
        } else if (target.classList.contains('btn-delete-holding')) {
            handleHoldingDelete(target.dataset.holdingId);
        }
    });
    modalCloseBtn.addEventListener('click', closeModal);
    modalOverlay.addEventListener('click', (event) => { if (event.target === modalOverlay) closeModal(); });

    // ページを離れるときにfetchをキャンセル
    window.addEventListener('pagehide', () => {
        if (fetchController) {
            fetchController.abort();
        }
    });

    // --- 初期実行 ---
    const cachedData = window.appState.getState('portfolio');
    if (cachedData) {
        allAssetsData = cachedData;
        filterAndRender();
    } else {
        loadAssetsFromStorage();
    }
    fetchAndRenderAllData(false);
});
