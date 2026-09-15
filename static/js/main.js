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
    const signalFilter = document.getElementById('signal-filter');
    const payoutRatioFilter = document.getElementById('payout-ratio-filter');
    const industryFilter = document.getElementById('industry-filter');
    const recentStocksToggleBtn = document.getElementById('recent-stocks-toggle-btn');
    const tabNav = document.querySelector('.tab-nav');
    const darkModeToggle = document.getElementById('dark-mode-toggle');

    let currentFilteredAssets = [];

    // --- 最近の銘柄ドロップダウン制御 ---
    if (recentStocksToggleBtn) {
        recentStocksToggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            recentStocksList.classList.toggle('hidden');
        });
        document.addEventListener('click', () => {
            recentStocksList.classList.add('hidden');
        });
    }

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
            updateIndustryFilterOptions();
            filterAndRender();
        } else {
            showSkeletons();
        }

        if (!force && !window.appState.canFetch()) {
            await checkAndShowSplitAlerts(); // 早期リターン時もアラート情報は最新を取得する (新規)
            return;
        }

        let isExplicitCancel = false;
        if (force) {
            isUpdating = true;
            refreshAllButton.disabled = false;
            refreshAllButton.textContent = '⏹️ 更新中止 (クリックでストップ)';
            refreshAllButton.classList.add('btn-updating-cancel');
        } else {
            refreshAllButton.disabled = true;
            refreshAllButton.textContent = '更新中...';
        }
        
        try {
            const apiFetch = (url) => fetch(url, { signal }).then(handleApiResponse);
            const stocksUrl = force ? '/api/stocks?force=true' : '/api/stocks';

            const [assetsResponse, rules, recent, accTypes, secCompanies] = await Promise.all([
                apiFetch(stocksUrl),
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
            
            updateIndustryFilterOptions(); // 業種リストを更新
            if (assetsResponse.metadata) {
                renderUpdateReport(assetsResponse.metadata);
            }

            renderRecentStocksList(recent);
            filterAndRender();
            if (force) {
                showAlert('ポートフォリオを更新しました。', 'success');
            }

        } catch (error) {
            if (error.name === 'AbortError') {
                if (force) {
                    showAlert('全件更新を中止しました。', 'info');
                }
                return;
            }
            console.error('Data fetch error:', error);
            if (error instanceof window.appState.HttpError && error.status === 429) {
                console.log('Backend is currently throttling or updating. Using cached data.');
            } else {
                showAlert(`データ更新に失敗しました: ${error.message}`, 'danger', true);
                if (!allAssetsData || allAssetsData.length === 0) {
                    loadAssetsFromStorage();
                }
            }
            await checkAndShowSplitAlerts(); // 株式分割アラートの確認 (新規)
        } finally {
            isUpdating = false;
            refreshAllButton.classList.remove('btn-updating-cancel');
            if (cooldownTimer === null) {
                refreshAllButton.disabled = false;
                refreshAllButton.textContent = '全件更新';
            }
        }
    }
    
    let cooldownTimer = null;
    let isSyncing = false;

    function renderUpdateReport(metadata) {
        if (!updateReportContainer || !metadata) return;
        if (isSyncing) {
            updateReportContainer.classList.add('hidden');
            return;
        }

        const timeStr = new Date(metadata.fetched_at).toLocaleString();
        const successClass = metadata.fail_count > 0 ? 'loss' : 'profit';
        
        let throttlingHint = '';
        if (metadata.circuit_breaker_triggered) {
            throttlingHint = `
                <div class="throttling-hint mt-2 p-2 border border-danger rounded bg-danger-subtle text-danger" style="font-size: 0.85rem;">
                    <i class="fas fa-exclamation-triangle me-1"></i>
                    <strong>アクセス制限(403)を検知しました。</strong><br>
                    連続アクセスによるサーバー負荷を避けるため、更新を中断しました。15分ほど待機してから再度お試しください。
                </div>
            `;
            startCooldown(15 * 60); // 15分
        }

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
                ${throttlingHint}
            </div>
        `;
        updateReportContainer.classList.remove('hidden');

        if (metadata.market_indices) {
            renderMarketSummary(metadata.market_indices);
        }
    }

    function startCooldown(seconds) {
        if (cooldownTimer) clearInterval(cooldownTimer);
        
        refreshAllButton.disabled = true;
        let remaining = seconds;
        
        const updateBtnText = () => {
            const mins = Math.floor(remaining / 60);
            const secs = remaining % 60;
            refreshAllButton.textContent = `待機中 (${mins}:${secs.toString().padStart(2, '0')})`;
        };
        
        updateBtnText();
        
        cooldownTimer = setInterval(() => {
            remaining--;
            if (remaining <= 0) {
                clearInterval(cooldownTimer);
                cooldownTimer = null;
                refreshAllButton.disabled = false;
                refreshAllButton.textContent = '全件更新';
            } else {
                updateBtnText();
            }
        }, 1000);
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
            const wowDate = idx.wow_date || '';
            const momDate = idx.mom_date || '';

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

            let changesRowHtml = '';
            if (idx.is_fx || idx.code === 'USDJPY=X') {
                const high = idx.high || '--';
                const low = idx.low || '--';
                const high52 = idx.high_52w || '--';
                const low52 = idx.low_52w || '--';
                const peakDiff = idx.peak_diff_percent ? ` (${idx.peak_diff_percent})` : '';

                changesRowHtml = `
                    <div class="market-index-row" style="border-top: 1px dashed var(--border-color); justify-content: center;" title="当日安値: ${low}円 〜 高値: ${high}円\n52週安値: ${low52}円 〜 高値: ${high52}円${peakDiff}">
                        <span style="color: var(--text-muted); font-size: 0.72rem; line-height: 1.5;">
                            52週: <strong style="color: var(--text-color);">${low52}~${high52}円</strong>${peakDiff}
                        </span>
                    </div>
                `;
            } else if (idx.is_future) {
                changesRowHtml = `
                    <div class="market-index-row" style="border-top: 1px dashed var(--border-color); justify-content: center;">
                        <span style="color: var(--text-muted); font-style: italic; font-size: 0.72rem; line-height: 1.5;">
                            ※ 当日推移のみ表示
                        </span>
                    </div>
                `;
            } else {
                changesRowHtml = `
                    <div class="market-index-row">
                        <div class="market-index-item">
                            <span class="change-label">前週比:</span>
                            <span class="${wowClass} numeric" title="${wowDate ? '比較対象: ' + wowDate : ''}">${formatPercent(wow)}</span>
                        </div>
                        <div class="market-index-item">
                            <span class="change-label">前月比:</span>
                            <span class="${momClass} numeric" title="${momDate ? '比較対象: ' + momDate : ''}">${formatPercent(mom)}</span>
                        </div>
                    </div>
                `;
            }

            const cardTitle = (idx.is_fx || idx.code === 'USDJPY=X')
                ? `当日安値: ${idx.low || '--'}円 〜 高値: ${idx.high || '--'}円\n52週安値: ${idx.low_52w || '--'}円 〜 高値: ${idx.high_52w || '--'}円${idx.peak_diff_percent ? '\n直近最高値比: ' + idx.peak_diff_percent : ''}`
                : '';

            html += `
                <a href="https://finance.yahoo.co.jp/quote/${idx.code}" target="_blank" class="market-index-link" title="${cardTitle}">
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
                            ${changesRowHtml}
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
                updateIndustryFilterOptions();
                filterAndRender();
            } catch (e) {
                console.error('Error parsing stored assets:', e);
            }
        }
    }

    function updateIndustryFilterOptions(searchText = '') {
        if (!industryFilter) return;
        
        // 現在の選択値を保持
        const currentValue = industryFilter.value;
        
        // 国内株式から一意な業種リストを抽出（N/A等を除外）
        const allIndustries = [...new Set(allAssetsData
            .filter(a => a.asset_type === 'jp_stock' && a.industry)
            .map(a => {
                const ind = a.industry;
                if (ind === 'N/A' || ind === '--' || ind === '-') return null;
                return ind;
            })
            .filter(ind => ind !== null)
        )].sort();

        // 検索テキストによる部分一致フィルタリング
        const filteredIndustries = searchText 
            ? allIndustries.filter(ind => ind.toLowerCase().includes(searchText.toLowerCase()))
            : allIndustries;

        let options = '<option value="">すべての業種</option>';
        filteredIndustries.forEach(ind => {
            options += `<option value="${ind}">${ind}</option>`;
        });
        
        // 検索テキストがない、または「その他」に部分一致する場合は「その他」を選択肢の最後に追加
        if (!searchText || 'その他'.includes(searchText) || '不明'.includes(searchText.toLowerCase()) || 'n/a'.includes(searchText.toLowerCase())) {
            options += '<option value="その他">その他（不明・N/A）</option>';
        }
        
        industryFilter.innerHTML = options;
        
        // 【デグレ防止】以前の選択値が新しいリストにも存在すれば復元
        const hasCurrentValue = [...industryFilter.options].some(opt => opt.value === currentValue);
        if (hasCurrentValue) {
            industryFilter.value = currentValue;
        } else if (currentValue && currentValue !== "") {
            // 現在選択されている値が検索フィルタで隠れても、選択状態が解除されないように一時的に残す
            if (currentValue !== "その他") {
                options = `<option value="${currentValue}">${currentValue} (選択中)</option>` + options;
                industryFilter.innerHTML = options;
            }
            industryFilter.value = currentValue;
        } else {
            industryFilter.value = "";
        }
    }

    function filterAndRender() {
        const filterText = filterInput.value.toLowerCase();
        const showOnlyManaged = showOnlyManagedAssetsCheckbox.checked;
        const selectedSignal = signalFilter.value;
        const selectedIndustry = industryFilter.value;
        const selectedPayoutRatio = payoutRatioFilter ? payoutRatioFilter.value : '';
        
        let filteredAssets = allAssetsData.filter(asset => asset.asset_type === activeTab);

        if (showOnlyManaged) filteredAssets = filteredAssets.filter(asset => asset.holdings && asset.holdings.length > 0);
        
        // 業種フィルタの適用 (国内株タブのみ)
        if (activeTab === 'jp_stock' && selectedIndustry) {
            if (selectedIndustry === "その他") {
                filteredAssets = filteredAssets.filter(asset => 
                    !asset.industry || asset.industry === 'N/A' || asset.industry === '--' || asset.industry === '-' || asset.industry === 'その他'
                );
            } else {
                filteredAssets = filteredAssets.filter(asset => asset.industry === selectedIndustry);
            }
        }

        // 配当性向フィルタの適用 (国内株および米国株タブ)
        if ((activeTab === 'jp_stock' || activeTab === 'us_stock') && selectedPayoutRatio) {
            filteredAssets = filteredAssets.filter(asset => {
                if (asset.payout_ratio === undefined || asset.payout_ratio === null || asset.payout_ratio === 'N/A' || asset.payout_ratio === '--' || asset.payout_ratio === '-') {
                    return false;
                }
                const rawStr = String(asset.payout_ratio).replace(/%/g, '').trim();
                const val = parseFloat(rawStr);
                if (isNaN(val)) return false;

                if (selectedPayoutRatio === '20-60') {
                    return val >= 20.0 && val <= 60.0;
                } else if (selectedPayoutRatio === 'under-20') {
                    return val < 20.0;
                } else if (selectedPayoutRatio === 'over-60') {
                    return val > 60.0;
                }
                return true;
            });
        }

        // シグナルフィルタの適用 (国内株タブのみ)
        if (activeTab === 'jp_stock' && selectedSignal) {
            if (selectedSignal === 'strict-dip') {
                filteredAssets = filteredAssets.filter(asset => (asset.is_diamond === true || (asset.buy_signal && asset.buy_signal.is_diamond === true)) && asset.buy_signal && asset.buy_signal.level >= 1);
            } else if (selectedSignal === 'strict-low') {
                filteredAssets = filteredAssets.filter(asset => {
                    const isDiamond = asset.is_diamond === true || (asset.buy_signal && asset.buy_signal.is_diamond === true);
                    const ma75 = asset.moving_average_75 || asset.ma75;
                    const isLongTermDiscount = asset.is_long_term_discount === true ||
                                               (asset.raw_sell_signal && asset.raw_sell_signal.level === 3) ||
                                               (asset.sell_signal && asset.sell_signal.level === 3) ||
                                               (asset.price > 0 && ma75 && asset.price < ma75);
                    const isFallingKnife = (asset.sell_signal && asset.sell_signal.level === 4) ||
                                          (asset.raw_sell_signal && asset.raw_sell_signal.level === 4);
                    return isDiamond && isLongTermDiscount && !isFallingKnife;
                });
            } else if (selectedSignal === 'overheated') {
                filteredAssets = filteredAssets.filter(asset => {
                    if (!asset.sell_signal) return false;
                    const level = asset.sell_signal.level;
                    if (level === 1 || level === 2 || level === 4) return true;
                    if (level === 3) {
                        const isDiamond = asset.is_diamond === true || (asset.buy_signal && asset.buy_signal.is_diamond === true);
                        return !isDiamond;
                    }
                    return false;
                });
            }
        }

        if (filterText) {
            const keywords = filterText.split(/[\s,，]+/).filter(k => k !== "");
            if (keywords.length > 0) {
                filteredAssets = filteredAssets.filter(asset =>
                    keywords.some(keyword =>
                        String(asset.code).toLowerCase().includes(keyword) ||
                        String(asset.name || '').toLowerCase().includes(keyword)
                    )
                );
            }
        }
        currentFilteredAssets = filteredAssets;
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
                const displayError = jpStock.error_message || jpStock.error;
                row.className = 'error-row'; 
                // HTMLタグを除去したプレーンテキストをtitleに設定
                row.title = displayError.replace(/<br>/g, '\n').replace(/<[^>]*>?/gm, '');
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${jpStock.code}" disabled>`);
                createCell(jpStock.code, 'numeric'); 
                // セル内はHTMLを許可して詳細表示
                createCell(displayError, 'error-message').colSpan = 14;
                createCell(`<button class="manage-btn" data-code="${jpStock.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${jpStock.code}">`);
            
            // 株式分割バッジの付与 (新規 - onclickによる確実な呼び出し)
            let codeHtml = jpStock.code;
            if (jpStock.split_alert) {
                codeHtml += ` <span class="split-badge confirmed" style="cursor:pointer;" onclick="window.showSplitModal('${jpStock.code}')" title="株式分割が検知されました。クリックして保有情報を調整します。">✂️</span>`;
            } else if (jpStock.potential_split) {
                codeHtml += ` <span class="split-badge potential" title="最新価格が直近終値と大きく乖離しています（比率: ${jpStock.potential_split_ratio}）。株式分割が発生した可能性があります。手動で履歴同期を実行してください。">⚠️</span>`;
            }
            createCell(codeHtml, 'numeric');
            
            const symbol = jpStock.code.includes('.') ? jpStock.code : `${jpStock.code}.T`;
            const baseUrl = `https://finance.yahoo.co.jp/quote/${symbol}`;
            let nameHtml = `<div class="d-flex flex-wrap align-items-center gap-1"><a href="${baseUrl}" target="_blank" class="fw-bold me-1">${jpStock.name}</a><div class="quick-links d-inline-flex gap-1"><a href="${baseUrl}/disclosure" target="_blank" class="badge bg-light text-dark border text-decoration-none" title="適時開示" style="font-size: 0.65rem; padding: 0.15rem 0.3rem;">開示</a><a href="${baseUrl}/performance" target="_blank" class="badge bg-light text-dark border text-decoration-none" title="業績詳細" style="font-size: 0.65rem; padding: 0.15rem 0.3rem;">業績</a></div>`;
            const isDiamond = jpStock.is_diamond || (jpStock.buy_signal && jpStock.buy_signal.is_diamond);
            if (jpStock.buy_signal) nameHtml += renderBuySignalBadge(jpStock.buy_signal, isDiamond);
            if (jpStock.sell_signal) nameHtml += renderSellSignalBadge(jpStock.sell_signal, isDiamond);
            if (jpStock.exhaustion_signal) nameHtml += renderExhaustionSignalBadge(jpStock.exhaustion_signal);
            if (jpStock.fx_sensitivity) nameHtml += renderFxSensitivityBadge(jpStock.fx_sensitivity);
            if (jpStock.profit_taking_badge || jpStock.profit_taking_signal) nameHtml += renderProfitTakingBadge(jpStock);
            nameHtml += `<button class="btn-llm-diagnose" data-code="${jpStock.code}" data-asset-type="${jpStock.asset_type || 'jp_stock'}" title="${jpStock.name} (${jpStock.code}) の投資方針適合度をAI診断">🤖 AI診断</button>`;
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
            
            // フィボナッチ (ツールチップで詳細情報を表示)
            const fib = jpStock.fibonacci;
            if (fib && fib.retracement !== undefined) {
                let fibVal = `${fib.retracement.toFixed(1)}%`;
                const isConvergence = jpStock.score_details && jpStock.score_details.is_fib_convergence;
                if (isConvergence) {
                    fibVal = `<span class="fib-convergence-badge">Wフィボ</span> ${fibVal}`;
                }
                const hCount = jpStock.history_count || fib.period || '不明';
                let fibTooltip = `算出期間: ${hCount}日\n直近高値: ${fib.high?.toLocaleString() || '-'}円\n直近安値: ${fib.low?.toLocaleString() || '-'}円`;
                if (isConvergence) {
                    fibTooltip = `【Wフィボ】短期と長期の押し目水準が一致する強いサポート帯です。\n` + fibTooltip;
                }
                createCellWithTooltip(fibVal, (isConvergence ? 'badge-cell' : 'numeric'), fibTooltip);
            } else {
                createCell('-', 'numeric');
            }
            
            createCell((jpStock.rci_26 !== undefined && jpStock.rci_26 !== null) ? `${jpStock.rci_26.toFixed(1)}%` : '-', 'numeric');
            createCellWithTooltip(jpStock.consecutive_increase_years > 0 ? `<span class="increase-badge">${jpStock.consecutive_increase_years}年連続</span>` : '-', 'badge-cell', formatDividendHistory(jpStock.dividend_history), `${baseUrl}/dividend`);
            
            // 配当性向のセル描画 (ツールチップで過去の履歴を表示)
            if (jpStock.payout_ratio !== undefined && jpStock.payout_ratio !== null && jpStock.payout_ratio !== 'N/A') {
                const payoutVal = `${parseFloat(jpStock.payout_ratio).toFixed(1)}%`;
                const payoutClass = 'numeric ' + getHighlightClass('payout_ratio', jpStock.payout_ratio, jpStock.asset_type);
                const payoutHistoryTooltip = formatPayoutRatioHistory(jpStock.payout_ratio_history);
                if (payoutHistoryTooltip) {
                    createCellWithTooltip(payoutVal, payoutClass, payoutHistoryTooltip, `${baseUrl}/dividend`);
                } else {
                    createCell(payoutVal, payoutClass);
                }
            } else {
                createCell('-', 'numeric na-value');
            }

            // DOEのセル描画
            if (jpStock.doe !== undefined && jpStock.doe !== null && jpStock.doe !== 'N/A') {
                const doeVal = `${parseFloat(jpStock.doe).toFixed(2)}%`;
                const doeClass = 'numeric ' + getHighlightClass('doe', jpStock.doe, jpStock.asset_type);
                const bpsVal = jpStock.bps && jpStock.bps !== 'N/A' ? parseFloat(jpStock.bps).toLocaleString() : 'N/A';
                createCellWithTooltip(doeVal, doeClass, `BPS（実績）: ${bpsVal}円\n算出式: 予想配当金 / BPS`);
            } else {
                createCell('-', 'numeric na-value');
            }

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
                const displayError = fund.error_message || fund.error;
                row.className = 'error-row';
                row.title = displayError.replace(/<br>/g, '\n').replace(/<[^>]*>?/gm, '');
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${fund.code}" disabled>`);
                createCell(fund.code, 'numeric');
                createCell(displayError, 'error-message').colSpan = 5;
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
            tableBody.innerHTML = `<tr><td colspan="11" style="text-align:center;">登録されている米国株式はありません。</td></tr>`;
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
                const displayError = usStock.error_message || usStock.error;
                row.className = 'error-row';
                row.title = displayError.replace(/<br>/g, '\n').replace(/<[^>]*>?/gm, '');
                createCell(`<input type="checkbox" class="asset-checkbox" data-code="${usStock.code}" disabled>`);
                createCell(usStock.code, 'numeric');
                createCell(displayError, 'error-message').colSpan = 9;
                createCell(`<button class="manage-btn" data-code="${usStock.code}" disabled>管理</button>`);
                return;
            }
            createCell(`<input type="checkbox" class="asset-checkbox" data-code="${usStock.code}">`);
            createCell(usStock.code, 'numeric'); createCell(`<a href="https://finance.yahoo.co.jp/quote/${usStock.code}" target="_blank">${usStock.name}</a> <button class="btn-llm-diagnose" data-code="${usStock.code}" data-asset-type="us_stock" title="${usStock.name} のAI適合診断">🤖 AI診断</button>`);
            createCell(usStock.market || 'N/A'); createCell(usStock.price, 'numeric');
            createCell(`${usStock.change} (${(usStock.change_percent && usStock.change_percent !== 'N/A') ? usStock.change_percent + '%' : 'N/A'})`, 'numeric');
            createCell(formatMarketCap(usStock.market_cap), 'numeric');
            createCell(usStock.per, 'numeric ' + getHighlightClass('per', usStock.per, usStock.asset_type));
            createCell(usStock.yield, 'numeric ' + getHighlightClass('yield', usStock.yield, usStock.asset_type));
            
            // 配当性向のセル描画
            if (usStock.payout_ratio !== undefined && usStock.payout_ratio !== null && usStock.payout_ratio !== 'N/A') {
                const payoutVal = `${parseFloat(usStock.payout_ratio).toFixed(1)}%`;
                const payoutClass = 'numeric ' + getHighlightClass('payout_ratio', usStock.payout_ratio, usStock.asset_type);
                createCell(payoutVal, payoutClass);
            } else {
                createCell('-', 'numeric na-value');
            }
            
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
    function formatPayoutRatioHistory(historyList) {
        if (!historyList || historyList.length === 0) return '';
        return '配当性向の推移:\n' + historyList.map(item => {
            const date = item.settlementDateFormatted || item.settlementDate || '不明';
            const ratio = item.payoutRatioFormattedWithUnit || (item.payoutRatioValue !== undefined ? item.payoutRatioValue + '%' : 'N/A');
            return `・${date}: ${ratio}`;
        }).join('\n');
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

        const reliabilityNote = signal.is_unreliable ? `\n\n【注意】時系列データが不足しています。` : '';
        const title = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${signal.reasons.join('\n')}` + reliabilityNote;
        return `<span class="signal-badge-base ${themeClass}" title="${title}"><span class="signal-badge-text"><span class="buy-signal-icon-inner">${signal.icon}</span>${signal.label}</span></span>`;
    }

    function renderSellSignalBadge(signal, isDiamond = false) {
        if (!signal) return '';
        
        // 売却はダイヤモンド属性に関わらず警告色を100%優先
        let themeClass = '';
        if (signal.level === 4) {
            themeClass = 'theme-sell-lv4';
        } else if (signal.level === 2) {
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

    function renderFxSensitivityBadge(fxSensitivity) {
        if (!fxSensitivity || !fxSensitivity.type || fxSensitivity.type === 'neutral') return '';
        const badgeClass = fxSensitivity.type === 'export_risk' ? 'badge-fx-export' : 'badge-fx-domestic';
        const title = fxSensitivity.description || '';
        return `<span class="signal-badge-base ${badgeClass}" title="${title}"><span class="signal-badge-text">${fxSensitivity.icon} ${fxSensitivity.label}</span></span>`;
    }

    function renderExhaustionSignalBadge(signal) {
        if (!signal) return '';
        let themeClass = signal.type === 'sell_the_fact' ? 'theme-exhaustion-warn' : 'theme-exhaustion-rebound';
        const title = (signal.recommended_action ? `【推奨アクション】\n${signal.recommended_action}\n\n` : '') + (signal.current_status ? `【現在の状態】\n${signal.current_status}\n\n` : '') + `【判定理由】\n${signal.reasons.join('\n')}`;
        return `<span class="signal-badge-base ${themeClass}" title="${title}"><span class="signal-badge-text"><span class="buy-signal-icon-inner">${signal.icon}</span>${signal.label}</span></span>`;
    }

    function renderProfitTakingBadge(item) {
        let ptSignal = item.profit_taking_badge || item.profit_taking_signal;
        if (!ptSignal && item.holdings && item.holdings.length > 0) {
            for (const h of item.holdings) {
                if (h.profit_taking_badge) {
                    if (!ptSignal || h.profit_taking_badge.level > ptSignal.level) {
                        ptSignal = h.profit_taking_badge;
                    }
                }
            }
        }
        if (!ptSignal || !ptSignal.level) return '';

        const badgeStyle = `background-color: ${ptSignal.color || '#eab308'}; color: #ffffff; font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 2px; box-shadow: 0 1px 2px rgba(0,0,0,0.15);`;
        const ratioText = (typeof isAmountVisible !== 'undefined' && !isAmountVisible) ? '***年分' : (ptSignal.dividend_years_ratio !== undefined ? `${ptSignal.dividend_years_ratio}年分` : '');
        const ratioStr = ratioText ? `（配当${ratioText}）` : '';
        const titleText = `【売り時・利確検討】\n${ptSignal.full_label || ptSignal.label} ${ratioStr}\n${ptSignal.recommended_action || ''}`;
        
        return `<span class="badge profit-taking-badge" style="${badgeStyle}" title="${titleText}">${ptSignal.full_label || ptSignal.label}</span>`;
    }

    function renderScoreAsStars(score, details, assetType) {
        if (assetType !== 'jp_stock' || score === undefined || score === null) return 'N/A';
        if (score === -1) return `<span class="score-na" title="評価指標なし">N/A</span>`;
        const trendScore = (details.trend_short || 0) + (details.trend_medium || 0) + (details.trend_long || 0) + (details.trend_signal || 0) + (details.fibonacci || 0) + (details.rci || 0) + (details.range_yearly || 0);
        const fundamentalScore = score - trendScore;
        let html = '';
        for (let i = 0; i < 16; i++) {
            if (i === 8) html += '<br>';
            const cls = i < fundamentalScore ? 'score-fundamental' : (i < score ? 'score-trend' : 'score-empty');
            html += `<span class="${cls}">${i < score ? '★' : '☆'}</span>`;
        }
        const tooltip = `合計: ${score} (PER: ${details.per||0}, PBR: ${details.pbr||0}, ROE: ${details.roe||0}, 利回り: ${details.yield||0}, 増配: ${details.consecutive_increase||0}, 配当性向: ${details.payout_ratio||0}, 短中トレンド: ${(details.trend_short||0)+(details.trend_medium||0)+(details.trend_signal||0)}, 200日線: ${details.trend_long||0}, 年間位置: ${details.range_yearly||0})`;
        const warning = details.is_reliable === false ? `<span class="score-unreliable-icon" title="不完全: ${details.missing_items.join(', ')}">⚠️</span>` : '';
        return `<span class="score-container" title="${tooltip}">${html}</span>${warning}`;
    }
    function getHighlightClass(key, value, assetType) {
        if (assetType !== 'jp_stock' && assetType !== 'us_stock') return '';
        const rules = highlightRules[key]; if (!rules || !value || value === 'N/A') return '';
        const num = parseFloat(String(value).replace(/[^0-9.-]/g, '')); if (isNaN(num)) return '';
        if (key === 'payout_ratio') {
            if (num > 0 && num <= rules.safe_max) return 'undervalued';
            if (num > rules.safe_max) return 'overvalued';
        } else if (key === 'doe') {
            if (assetType !== 'jp_stock') return '';
            if (num >= rules.good_min) return 'undervalued';
        } else {
            if (assetType !== 'jp_stock') return '';
            if (key === 'yield' || key === 'roe') { if (num >= rules.undervalued) return 'undervalued'; }
            else { if (num <= rules.undervalued) return 'undervalued'; if (num >= rules.overvalued) return 'overvalued'; }
        }
        return '';
    }
    function renderRecentStocksList(codes) {
        if (!recentStocksList) return;
        recentStocksList.innerHTML = '';
        if (codes.length === 0) {
            recentStocksList.innerHTML = '<li style="padding: 8px 15px; font-size: 0.9rem;">最近追加した資産はありません。</li>';
            return;
        }

        // 1. 一括フィルタボタンを先頭に追加
        const bulkFilterLi = document.createElement('li');
        bulkFilterLi.className = 'recent-stock-item bulk-filter-item';
        bulkFilterLi.innerHTML = '<strong>🔍 最近の銘柄を一括フィルタ</strong>';
        bulkFilterLi.addEventListener('click', (e) => {
            e.stopPropagation();
            filterInput.value = codes.join(' ');
            filterAndRender();
            recentStocksList.classList.add('hidden');
        });
        recentStocksList.appendChild(bulkFilterLi);

        // 2. 区切り線
        const divider = document.createElement('li');
        divider.className = 'dropdown-divider';
        recentStocksList.appendChild(divider);

        // 3. 各銘柄コードのレンダリング
        codes.forEach(code => {
            const li = document.createElement('li');
            li.className = 'recent-stock-item stock-item-with-actions';
            
            const codeSpan = document.createElement('span');
            codeSpan.textContent = code;
            codeSpan.className = 'stock-code-label';
            li.appendChild(codeSpan);

            const actionsDiv = document.createElement('span');
            actionsDiv.className = 'recent-stock-actions';

            // フィルタ個別適用ボタン
            const filterBtn = document.createElement('button');
            filterBtn.className = 'btn-sm btn-icon';
            filterBtn.title = '検索窓に適用';
            filterBtn.innerHTML = '🔍';
            filterBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const currentVal = filterInput.value.trim();
                if (currentVal) {
                    const currentCodes = currentVal.split(/[\s,，]+/);
                    if (!currentCodes.includes(code)) {
                        filterInput.value = currentVal + ' ' + code;
                    }
                } else {
                    filterInput.value = code;
                }
                filterAndRender();
                recentStocksList.classList.add('hidden');
            });
            actionsDiv.appendChild(filterBtn);

            // 追加フォーム適用ボタン
            const addFormBtn = document.createElement('button');
            addFormBtn.className = 'btn-sm btn-icon';
            addFormBtn.title = '追加フォームに入力';
            addFormBtn.innerHTML = '➕';
            addFormBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                assetCodeInput.value = code;
                recentStocksList.classList.add('hidden');
            });
            actionsDiv.appendChild(addFormBtn);

            li.appendChild(actionsDiv);

            // 従来のクリック挙動（デグレ防止用: 項目自体をクリックした場合は従来通り追加フォームに入力）
            li.addEventListener('click', () => {
                assetCodeInput.value = code;
                recentStocksList.classList.add('hidden');
            });

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
            showAlert('保有情報を保存しました。', 'success'); window.appState.clearState(); await fetchAndRenderAllData(false);
            const asset = allAssetsData.find(a => a.code === currentManagingCode); if (asset) renderHoldingsList(asset.holdings, asset.asset_type);
            hideHoldingForm();
        } catch (err) { showAlert(err.message, 'danger'); }
    }
    async function handleHoldingDelete(id) {
        if (!confirm('削除しますか？')) return;
        try {
            const res = await fetch(`/api/holdings/${id}`, { method: 'DELETE' }); if (!res.ok) throw new Error('削除失敗');
            showAlert('削除しました。', 'success'); window.appState.clearState(); await fetchAndRenderAllData(false);
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
            if (d.status === 'success') { window.appState.clearState(); await fetchAndRenderAllData(false); }
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

    downloadCsvButton.addEventListener('click', async () => {
        if (!currentFilteredAssets || currentFilteredAssets.length === 0) {
            alert('該当する銘柄が存在しません。');
            return;
        }

        const targetCodes = currentFilteredAssets.map(a => a.code);
        try {
            const response = await fetch('/api/stocks/csv', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ codes: targetCodes })
            });

            if (!response.ok) {
                throw new Error(`サーバーエラー: ${response.status}`);
            }

            const blob = await response.blob();
            const disposition = response.headers.get('Content-Disposition');
            let filename = `portfolio_${new Date().toISOString().replace(/[:.]/g, '').slice(0, 15)}.csv`;

            if (disposition && disposition.includes('filename=')) {
                const matches = disposition.match(/filename=["']?([^"';]+)["']?/);
                if (matches && matches[1]) {
                    filename = matches[1];
                }
            }

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            console.error('CSVダウンロードエラー:', err);
            alert(`CSVのダウンロードに失敗しました: ${err.message}`);
        }
    });
    // --- プリセットフィルタ制御 ---
    const QUICK_PRESETS = {
        'quick-dip-payout': {
            signal: 'strict-dip',
            payoutRatio: '20-60',
            targetTab: 'jp_stock'
        },
        'quick-bargain': {
            signal: 'strict-low',
            targetTab: 'jp_stock'
        },
        'quick-managed': {
            showOnlyManaged: true
        }
    };

    let activePresetId = null;

    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function getCustomPresets() {
        try {
            const data = localStorage.getItem('custom_filter_presets_v1');
            return data ? JSON.parse(data) : [];
        } catch (e) {
            console.error('カスタムプリセット読込エラー:', e);
            return [];
        }
    }

    function saveCustomPresets(presets) {
        try {
            localStorage.setItem('custom_filter_presets_v1', JSON.stringify(presets));
        } catch (e) {
            console.error('カスタムプリセット保存エラー:', e);
        }
    }

    function renderCustomPresets() {
        const container = document.getElementById('custom-presets-container');
        if (!container) return;
        const customPresets = getCustomPresets();
        container.innerHTML = customPresets.map(preset => `
            <div class="preset-badge-wrapper">
                <button type="button" class="preset-badge custom-preset ${activePresetId === preset.id ? 'active' : ''}" data-preset-id="${preset.id}" title="${escapeHtml(preset.name)}">
                    ⭐ ${escapeHtml(preset.name)}
                </button>
                <button type="button" class="preset-delete-btn" data-delete-id="${preset.id}" title="このプリセットを削除">&times;</button>
            </div>
        `).join('');
    }

    function updatePresetActiveStates(forcedId = undefined) {
        if (forcedId !== undefined) {
            activePresetId = forcedId;
        } else {
            // 現在の入力状態から一致するプリセットがあるかチェック
            const currentSignal = signalFilter ? signalFilter.value : '';
            const currentPayout = payoutRatioFilter ? payoutRatioFilter.value : '';
            const currentManaged = showOnlyManagedAssetsCheckbox ? showOnlyManagedAssetsCheckbox.checked : false;
            const currentFilterText = filterInput ? filterInput.value.trim() : '';
            const currentIndustry = industryFilter ? industryFilter.value : '';

            let matchedId = null;

            // クイックプリセットチェック
            for (const [id, target] of Object.entries(QUICK_PRESETS)) {
                const matchSignal = (target.signal || '') === currentSignal;
                const matchPayout = (target.payoutRatio || '') === currentPayout;
                const matchManaged = !!target.showOnlyManaged === currentManaged;
                const noText = !currentFilterText;
                const noInd = !currentIndustry;

                if (matchSignal && matchPayout && matchManaged && noText && noInd) {
                    matchedId = id;
                    break;
                }
            }

            // カスタムプリセットチェック
            if (!matchedId) {
                const customPresets = getCustomPresets();
                for (const p of customPresets) {
                    const f = p.filter || {};
                    if ((f.signal || '') === currentSignal &&
                        (f.payoutRatio || '') === currentPayout &&
                        !!f.showOnlyManaged === currentManaged &&
                        (f.filterText || '') === currentFilterText &&
                        (f.industry || '') === currentIndustry) {
                        matchedId = p.id;
                        break;
                    }
                }
            }

            activePresetId = matchedId;
        }

        // DOMの活性/非活性クラスの更新
        document.querySelectorAll('.preset-badge').forEach(badge => {
            if (badge.dataset.presetId === activePresetId) {
                badge.classList.add('active');
            } else {
                badge.classList.remove('active');
            }
        });
    }

    function applyPreset(presetId) {
        // すでにアクティブな場合はトグル解除（リセット）
        if (activePresetId === presetId) {
            clearAllFilters();
            return;
        }

        let targetFilter = null;
        let targetTab = null;

        if (QUICK_PRESETS[presetId]) {
            targetFilter = QUICK_PRESETS[presetId];
            targetTab = targetFilter.targetTab;
        } else {
            const customPresets = getCustomPresets();
            const found = customPresets.find(p => p.id === presetId);
            if (found) {
                targetFilter = found.filter;
                targetTab = targetFilter.targetTab;
            }
        }

        if (!targetFilter) return;

        // タブ切り替えが必要な場合
        if (targetTab && targetTab !== activeTab) {
            const tabBtn = document.querySelector(`.tab-link[data-tab="${targetTab}"]`);
            if (tabBtn) tabBtn.click();
        }

        // 各フィルタ値を反映
        if (filterInput) filterInput.value = targetFilter.filterText || '';
        if (industryFilter) industryFilter.value = targetFilter.industry || '';
        const indSearch = document.getElementById('industry-search');
        if (indSearch) indSearch.value = targetFilter.industrySearch || '';
        if (signalFilter) signalFilter.value = targetFilter.signal || '';
        if (payoutRatioFilter) payoutRatioFilter.value = targetFilter.payoutRatio || '';
        if (showOnlyManagedAssetsCheckbox) showOnlyManagedAssetsCheckbox.checked = !!targetFilter.showOnlyManaged;

        filterAndRender();
        updatePresetActiveStates(presetId);
    }

    function clearAllFilters() {
        if (filterInput) filterInput.value = '';
        if (industryFilter) industryFilter.value = '';
        const indSearch = document.getElementById('industry-search');
        if (indSearch) indSearch.value = '';
        if (signalFilter) signalFilter.value = '';
        if (payoutRatioFilter) payoutRatioFilter.value = '';
        if (showOnlyManagedAssetsCheckbox) showOnlyManagedAssetsCheckbox.checked = false;

        filterAndRender();
        updatePresetActiveStates(null);
    }

    function saveCurrentFilterAsPreset() {
        const fText = filterInput ? filterInput.value.trim() : '';
        const ind = industryFilter ? industryFilter.value : '';
        const indSearch = document.getElementById('industry-search') ? document.getElementById('industry-search').value : '';
        const sig = signalFilter ? signalFilter.value : '';
        const pay = payoutRatioFilter ? payoutRatioFilter.value : '';
        const managed = showOnlyManagedAssetsCheckbox ? showOnlyManagedAssetsCheckbox.checked : false;

        if (!fText && !ind && !sig && !pay && !managed) {
            alert('保存するフィルタ条件が指定されていません。何かフィルタを選択してから保存してください。');
            return;
        }

        const presets = getCustomPresets();
        if (presets.length >= 10) {
            alert('カスタムプリセットは最大10個まで保存可能です。不要なプリセットを削除してください。');
            return;
        }

        const presetName = prompt('保存するフィルタ条件の名称を入力してください:', 'マイ・フィルタ');
        if (!presetName || !presetName.trim()) return;

        const newPreset = {
            id: 'custom_' + Date.now(),
            name: presetName.trim(),
            filter: {
                filterText: fText,
                industry: ind,
                industrySearch: indSearch,
                signal: sig,
                payoutRatio: pay,
                showOnlyManaged: managed,
                targetTab: activeTab
            }
        };

        presets.push(newPreset);
        saveCustomPresets(presets);
        renderCustomPresets();
        updatePresetActiveStates(newPreset.id);
        showAlert(`プリセット「${newPreset.name}」を保存しました`, 'success');
    }

    function deleteCustomPreset(id) {
        let presets = getCustomPresets();
        const target = presets.find(p => p.id === id);
        if (!target || !confirm(`プリセット「${target.name}」を削除しますか？`)) return;

        presets = presets.filter(p => p.id !== id);
        saveCustomPresets(presets);
        if (activePresetId === id) activePresetId = null;
        renderCustomPresets();
        updatePresetActiveStates();
        showAlert('プリセットを削除しました', 'success');
    }

    // イベントリスナー初期化
    const presetBar = document.getElementById('preset-filter-bar');
    if (presetBar) {
        renderCustomPresets();

        presetBar.addEventListener('click', (e) => {
            const badge = e.target.closest('.preset-badge');
            if (badge) {
                applyPreset(badge.dataset.presetId);
                return;
            }

            const delBtn = e.target.closest('.preset-delete-btn');
            if (delBtn) {
                deleteCustomPreset(delBtn.dataset.deleteId);
                return;
            }

            if (e.target.closest('#save-preset-btn')) {
                saveCurrentFilterAsPreset();
                return;
            }

            if (e.target.closest('#clear-filters-btn')) {
                clearAllFilters();
                return;
            }
        });
    }

    const onFilterChangeWithStateSync = () => {
        filterAndRender();
        updatePresetActiveStates();
    };

    filterInput.addEventListener('input', onFilterChangeWithStateSync);
    industryFilter.addEventListener('change', onFilterChangeWithStateSync);
    const industrySearch = document.getElementById('industry-search');
    if (industrySearch) {
        industrySearch.addEventListener('input', function() {
            updateIndustryFilterOptions(this.value);
        });
    }
    signalFilter.addEventListener('change', onFilterChangeWithStateSync);
    if (payoutRatioFilter) {
        ['change', 'input'].forEach(evt => payoutRatioFilter.addEventListener(evt, onFilterChangeWithStateSync));
    }
    showOnlyManagedAssetsCheckbox.addEventListener('input', onFilterChangeWithStateSync);
    
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
            showAlert('削除しました', 'success'); window.appState.clearState(); await fetchAndRenderAllData(false);
        } catch (err) { showAlert(err.message, 'danger'); }
    });

    refreshAllButton.addEventListener('click', () => {
        if (cooldownTimer) return;
        if (isUpdating) {
            if (fetchController) {
                fetchController.abort();
            }
            return;
        }
        fetchAndRenderAllData(true);
    });
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

    // ==========================================
    // 株式分割アラート関連ロジック (Issue #216)
    // ==========================================
    const splitAlertBanner = document.getElementById('split-alert-banner');
    const btnShowSplitModal = document.getElementById('btn-show-split-modal');
    const splitAlertModal = document.getElementById('split-alert-modal');
    const splitAlertDetailsContainer = document.getElementById('split-alert-details-container');
    
    // モーダルを閉じるボタン
    const btnCloseSplitModal = document.getElementById('btn-close-split-modal');
    const btnCloseSplitModalFooter = document.getElementById('btn-close-split-modal-footer');

    // 保留中のアラートデータを保持する変数
    let pendingSplitAlerts = [];

    // アラートの確認・表示
    async function checkAndShowSplitAlerts() {
        if (!splitAlertBanner) return;
        try {
            const res = await fetch('/api/split-alerts');
            if (!res.ok) throw new Error('アラート取得失敗');
            pendingSplitAlerts = await res.json();
            
            if (pendingSplitAlerts.length > 0) {
                splitAlertBanner.classList.remove('hidden');
                splitAlertBanner.style.display = 'flex'; // flex表示で整列
            } else {
                splitAlertBanner.classList.add('hidden');
                splitAlertBanner.style.display = 'none';
            }
        } catch (err) {
            console.error('Failed to fetch split alerts:', err);
        }
    }

    // プレビューモーダルのレンダリング
    function renderSplitAlertModal() {
        if (!splitAlertDetailsContainer) return;
        if (pendingSplitAlerts.length === 0) {
            splitAlertDetailsContainer.innerHTML = '<p>現在保留中の株式分割アラートはありません。</p>';
            return;
        }

        let html = '';
        pendingSplitAlerts.forEach(alert => {
            let bodyContentHtml = '';
            let actionButtonsHtml = '';

            if (alert.is_non_holding) {
                // 非保有（0株）銘柄専用の案内カード (#291)
                bodyContentHtml = `
                    <div class="split-non-holding-card">
                        <div class="split-non-holding-icon">💡</div>
                        <div class="split-non-holding-text">
                            <strong>現在この銘柄の保有数量は 0株 (非保有) です。</strong>
                            <p style="margin: 4px 0 0 0; font-size: 0.85rem; opacity: 0.9;">保有株数・取得単価の自動調整はありません。[確認済みにする] を押すと、DB過去株価を自動補正して通知を消去します。</p>
                        </div>
                    </div>
                `;
                actionButtonsHtml = `
                    <button class="btn-primary btn-sm btn-apply-split" data-code="${alert.code}" data-ratio="${alert.ratio}">確認済みにする (通知消去)</button>
                `;
            } else {
                // 通常保有銘柄用調整プレビューテーブル
                let holdingsHtml = '';
                alert.holdings.forEach(h => {
                    holdingsHtml += `
                        <tr>
                            <td><strong>${h.account_type}</strong> (${h.security_company || '不明'})</td>
                            <td>${formatNumber(h.purchase_price, 2)}円 × ${formatNumber(h.quantity, 0)}株</td>
                            <td><span style="color: var(--danger-color); font-weight: bold;">${formatNumber(h.new_purchase_price, 2)}円</span> × <span style="color: #28a745; font-weight: bold;">${formatNumber(h.new_quantity, 0)}株</span></td>
                        </tr>
                    `;
                });

                bodyContentHtml = `
                    <table class="split-detail-table">
                        <thead>
                            <tr>
                                <th>口座</th>
                                <th>調整前</th>
                                <th>調整後 (適用プレビュー)</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${holdingsHtml}
                        </tbody>
                    </table>
                `;
                actionButtonsHtml = `
                    <button class="btn-outline btn-sm btn-dismiss-split" data-code="${alert.code}">無視する (非表示)</button>
                    <button class="btn-primary btn-sm btn-apply-split" data-code="${alert.code}" data-ratio="${alert.ratio}">適用して保存</button>
                `;
            }

            html += `
                <div class="split-detail-card" data-code="${alert.code}">
                    <div class="split-detail-header">
                        <span>${alert.name} (${alert.code}) - 分割比率 1 : ${alert.ratio}</span>
                        <span style="font-size: 0.8rem; color: #6c757d;">検知日: ${alert.detected_date}</span>
                    </div>
                    ${bodyContentHtml}
                    <div class="split-actions">
                        ${actionButtonsHtml}
                    </div>
                </div>
            `;
        });
        splitAlertDetailsContainer.innerHTML = html;
    }

    // グローバルに関数を公開（インライン onclick から確実に呼び出せるようにする）
    window.showSplitModal = function(code) {
        renderSplitAlertModal();
        if (splitAlertModal) {
            splitAlertModal.classList.remove('hidden');
        }
    };

    // モーダルを開く (バナー上のボタン)
    if (btnShowSplitModal) {
        btnShowSplitModal.addEventListener('click', () => {
            renderSplitAlertModal();
            if (splitAlertModal) splitAlertModal.classList.remove('hidden');
        });
    }

    // モーダルを閉じる
    const closeSplitModal = () => {
        if (splitAlertModal) splitAlertModal.classList.add('hidden');
    };
    if (btnCloseSplitModal) btnCloseSplitModal.addEventListener('click', closeSplitModal);
    if (btnCloseSplitModalFooter) btnCloseSplitModalFooter.addEventListener('click', closeSplitModal);
    if (splitAlertModal) {
        splitAlertModal.addEventListener('click', (e) => {
            if (e.target === splitAlertModal) closeSplitModal();
        });
    }

    // モーダル内アクション（適用・無視）のイベントデリゲーション
    if (splitAlertDetailsContainer) {
        splitAlertDetailsContainer.addEventListener('click', async (e) => {
            const target = e.target;
            if (target.classList.contains('btn-apply-split')) {
                const code = target.dataset.code;
                const ratio = parseFloat(target.dataset.ratio);
                if (!confirm(`銘柄 ${code} に比率 ${ratio} で株式分割を適用します。よろしいですか？`)) return;
                
                try {
                    const res = await fetch('/api/split-alerts/apply', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ code, ratio })
                    });
                    if (!res.ok) throw new Error('適用に失敗しました');
                    showAlert('株式分割を適用しました。', 'success');
                    
                    // アラートを更新し、モーダルを更新。残りが無ければ閉じる。
                    await checkAndShowSplitAlerts();
                    if (pendingSplitAlerts.length > 0) {
                        renderSplitAlertModal();
                    } else {
                        closeSplitModal();
                    }
                    
                    // ポートフォリオデータの再読み込みと描画
                    window.appState.clearState();
                    await fetchAndRenderAllData(false);
                } catch (err) {
                    showAlert(err.message, 'danger');
                }
            } else if (target.classList.contains('btn-dismiss-split')) {
                const code = target.dataset.code;
                if (!confirm(`このアラートを非表示にします。よろしいですか？（保有データは書き換わりません）`)) return;
                
                try {
                    const res = await fetch('/api/split-alerts/dismiss', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ code })
                    });
                    if (!res.ok) throw new Error('無視処理に失敗しました');
                    showAlert('アラートを非表示にしました。', 'success');
                    
                    await checkAndShowSplitAlerts();
                    if (pendingSplitAlerts.length > 0) {
                        renderSplitAlertModal();
                    } else {
                        closeSplitModal();
                    }
                    // テーブル描画のバッジを消すために再描画
                    window.appState.clearState();
                    await fetchAndRenderAllData(false);
                } catch (err) {
                    showAlert(err.message, 'danger');
                }
            }
        });
    }

    // ==========================================
    // 株式分割履歴モーダル関連ロジック
    // ==========================================
    const btnShowSplitHistory = document.getElementById('btn-show-split-history');
    const splitHistoryModal = document.getElementById('split-history-modal');
    const splitHistoryContainer = document.getElementById('split-history-container');
    const btnCloseSplitHistoryModal = document.getElementById('btn-close-split-history-modal');
    const btnCloseSplitHistoryModalFooter = document.getElementById('btn-close-split-history-modal-footer');

    async function loadAndShowSplitHistory() {
        if (!splitHistoryContainer) return;
        splitHistoryContainer.innerHTML = '<p style="text-align: center; color: #6c757d;">読み込み中...</p>';
        if (splitHistoryModal) splitHistoryModal.classList.remove('hidden');

        try {
            const res = await fetch('/api/split-history');
            if (!res.ok) throw new Error('分割履歴の取得に失敗しました');
            const historyData = await res.json();

            if (historyData.length === 0) {
                splitHistoryContainer.innerHTML = '<p style="text-align: center; color: #6c757d;">過去の株式分割・併合履歴はありません。</p>';
                return;
            }

            let tableHtml = `
                <table class="split-detail-table" style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 2px solid var(--border-color, #e2e8f0);">
                            <th style="padding: 8px; text-align: left;">銘柄</th>
                            <th style="padding: 8px; text-align: center;">比率</th>
                            <th style="padding: 8px; text-align: center;">検知日</th>
                            <th style="padding: 8px; text-align: center;">状況</th>
                            <th style="padding: 8px; text-align: center;">更新日</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            historyData.forEach(item => {
                let statusBadge = '';
                if (item.status === 'applied') {
                    statusBadge = '<span class="split-badge-status applied" style="background: #28a745; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 0.8rem;">✅ 適用済み</span>';
                } else if (item.status === 'dismissed') {
                    statusBadge = '<span class="split-badge-status dismissed" style="background: #6c757d; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 0.8rem;">🚫 無視</span>';
                } else {
                    statusBadge = '<span class="split-badge-status pending" style="background: #ffc107; color: #212529; padding: 2px 8px; border-radius: 12px; font-size: 0.8rem;">⏳ 保留中</span>';
                }

                const updatedDateStr = item.updated_at_jst ? item.updated_at_jst.split('T')[0] : item.detected_date;

                tableHtml += `
                    <tr style="border-bottom: 1px solid var(--border-color, #e2e8f0);">
                        <td style="padding: 8px;"><strong>${item.name}</strong> (${item.code})</td>
                        <td style="padding: 8px; text-align: center;">1 : ${item.ratio}</td>
                        <td style="padding: 8px; text-align: center;">${item.detected_date}</td>
                        <td style="padding: 8px; text-align: center;">${statusBadge}</td>
                        <td style="padding: 8px; text-align: center; font-size: 0.85rem; color: #6c757d;">${updatedDateStr}</td>
                    </tr>
                `;
            });

            tableHtml += `
                    </tbody>
                </table>
            `;
            splitHistoryContainer.innerHTML = tableHtml;

        } catch (err) {
            console.error('Failed to fetch split history:', err);
            splitHistoryContainer.innerHTML = `<p style="color: var(--danger-color, #e53e3e); text-align: center;">${err.message}</p>`;
        }
    }

    const closeSplitHistoryModal = () => {
        if (splitHistoryModal) splitHistoryModal.classList.add('hidden');
    };

    if (btnShowSplitHistory) btnShowSplitHistory.addEventListener('click', loadAndShowSplitHistory);
    if (btnCloseSplitHistoryModal) btnCloseSplitHistoryModal.addEventListener('click', closeSplitHistoryModal);
    if (btnCloseSplitHistoryModalFooter) btnCloseSplitHistoryModalFooter.addEventListener('click', closeSplitHistoryModal);
    if (splitHistoryModal) {
        splitHistoryModal.addEventListener('click', (e) => {
            if (e.target === splitHistoryModal) closeSplitHistoryModal();
        });
    }

    // ==========================================
    // LLM AI Diagnosis & Policy Config (Issue #237)
    // ==========================================
    const btnOpenPolicyConfig = document.getElementById('btn-open-policy-config');
    const investmentPolicyModal = document.getElementById('investment-policy-modal');
    const btnClosePolicyModal = document.getElementById('btn-close-policy-modal');
    const btnCancelPolicyModal = document.getElementById('btn-cancel-policy-modal');
    const investmentPolicyForm = document.getElementById('investment-policy-form');
    const policyApiKeyInput = document.getElementById('policy-api-key-input');
    const policyModelSelect = document.getElementById('policy-model-select');
    const policyPromptTextarea = document.getElementById('policy-prompt-textarea');
    const btnResetPolicyPrompt = document.getElementById('btn-reset-policy-prompt');
    const apiKeyStatusHelp = document.getElementById('api-key-status-help');

    const llmDiagnosisModal = document.getElementById('llm-diagnosis-modal');
    const btnCloseLlmModal = document.getElementById('btn-close-llm-modal');
    const btnCloseLlmModalFooter = document.getElementById('btn-close-llm-modal-footer');
    const llmLoadingContainer = document.getElementById('llm-loading-container');
    const llmResultContainer = document.getElementById('llm-result-container');
    const llmModalTitle = document.getElementById('llm-modal-title');

    const policyModalAlert = document.getElementById('policy-modal-alert');

    function showPolicyModalAlert(message, type = 'info') {
        if (!policyModalAlert) return;
        policyModalAlert.textContent = message;
        policyModalAlert.classList.remove('hidden');
        
        const isDark = document.documentElement.classList.contains('dark-mode') || document.body.classList.contains('dark-mode');
        if (type === 'info') {
            policyModalAlert.style.backgroundColor = isDark ? '#1e3a8a' : '#d1ecf1';
            policyModalAlert.style.color = isDark ? '#93c5fd' : '#0c5460';
            policyModalAlert.style.borderColor = isDark ? '#2563eb' : '#bee5eb';
        } else if (type === 'success') {
            policyModalAlert.style.backgroundColor = isDark ? '#14532d' : '#d4edda';
            policyModalAlert.style.color = isDark ? '#86efac' : '#155724';
            policyModalAlert.style.borderColor = isDark ? '#166534' : '#c3e6cb';
        } else if (type === 'danger') {
            policyModalAlert.style.backgroundColor = isDark ? '#7f1d1d' : '#f8d7da';
            policyModalAlert.style.color = isDark ? '#fca5a5' : '#721c24';
            policyModalAlert.style.borderColor = isDark ? '#991b1b' : '#f5c6cb';
        }
        setTimeout(() => {
            if (policyModalAlert) policyModalAlert.classList.add('hidden');
        }, 5000);
    }

    // 1. 設定モーダル開閉
    if (btnOpenPolicyConfig) {
        btnOpenPolicyConfig.addEventListener('click', async () => {
            if (policyModalAlert) policyModalAlert.classList.add('hidden');
            try {
                const res = await fetch('/api/investment-policy');
                if (res.ok) {
                    const config = await res.json();
                    policyApiKeyInput.value = '';
                    policyApiKeyInput.placeholder = config.api_key_masked ? `設定済み (${config.api_key_masked})` : 'AIzaSy... (空欄の場合は環境変数 GEMINI_API_KEY を参照)';
                    if (apiKeyStatusHelp) {
                        if (config.has_api_key) {
                            apiKeyStatusHelp.textContent = config.is_using_env_key ? '✓ 環境変数 GEMINI_API_KEY が検出されました。' : '✓ 画面から保存された APIキー が有効です。';
                            apiKeyStatusHelp.style.color = '#10b981';
                        } else {
                            apiKeyStatusHelp.textContent = '⚠️ APIキーが設定されていません。Google AI Studio から無料キーを取得して設定してください。';
                            apiKeyStatusHelp.style.color = '#f59e0b';
                        }
                    }
                    policyModelSelect.value = config.selected_model || 'gemini-flash-latest';
                    policyPromptTextarea.value = config.policy_prompt || '';
                }
            } catch (e) {
                console.error('Failed to load investment policy config:', e);
            }
            if (investmentPolicyModal) investmentPolicyModal.classList.remove('hidden');
        });
    }

    const closePolicyModal = () => {
        if (investmentPolicyModal) investmentPolicyModal.classList.add('hidden');
    };
    if (btnClosePolicyModal) btnClosePolicyModal.addEventListener('click', closePolicyModal);
    if (btnCancelPolicyModal) btnCancelPolicyModal.addEventListener('click', closePolicyModal);
    if (investmentPolicyModal) {
        investmentPolicyModal.addEventListener('click', (e) => {
            if (e.target === investmentPolicyModal) closePolicyModal();
        });
    }

    // 2. 設定の保存
    if (investmentPolicyForm) {
        investmentPolicyForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const apiKeyVal = policyApiKeyInput.value.trim();
            const modelVal = policyModelSelect.value;
            const promptVal = policyPromptTextarea.value.trim();
            
            try {
                const payload = {
                    selected_model: modelVal,
                    policy_prompt: promptVal
                };
                if (apiKeyVal) payload.api_key = apiKeyVal;

                const res = await fetch('/api/investment-policy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    showAlert('投資方針およびAI設定を保存しました。', 'success');
                    closePolicyModal();
                } else {
                    showPolicyModalAlert('設定の保存に失敗しました。', 'danger');
                    showAlert('設定の保存に失敗しました。', 'danger');
                }
            } catch (e) {
                console.error('Error saving policy:', e);
                showPolicyModalAlert('設定の保存中に通信エラーが発生しました。', 'danger');
                showAlert('設定の保存中に通信エラーが発生しました。', 'danger');
            }
        });
    }

    // 3. プロンプトリセット
    if (btnResetPolicyPrompt) {
        btnResetPolicyPrompt.addEventListener('click', async () => {
            if (!confirm('投資方針プロンプトをデフォルトの「インカムゲイン特化型・リスク管理専門」の内容に戻しますか？')) return;
            try {
                const res = await fetch('/api/investment-policy', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reset: true })
                });
                if (res.ok) {
                    const config = await res.json();
                    policyPromptTextarea.value = config.policy_prompt || '';
                    showPolicyModalAlert('✓ プロンプトを初期デフォルト値にリセットしました。', 'info');
                    showAlert('プロンプトを初期デフォルト値にリセットしました。', 'info');
                }
            } catch (e) {
                console.error('Error resetting policy:', e);
            }
        });
    }

    // 4. AI診断モーダルの閉鎖
    const closeLlmModal = () => {
        if (llmDiagnosisModal) llmDiagnosisModal.classList.add('hidden');
    };
    if (btnCloseLlmModal) btnCloseLlmModal.addEventListener('click', closeLlmModal);
    if (btnCloseLlmModalFooter) btnCloseLlmModalFooter.addEventListener('click', closeLlmModal);
    if (llmDiagnosisModal) {
        llmDiagnosisModal.addEventListener('click', (e) => {
            if (e.target === llmDiagnosisModal) closeLlmModal();
        });
    }

    // 5. テーブル内「🤖 AI診断」ボタンのイベント委譲 (デリゲーション & event.stopPropagation)
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.btn-llm-diagnose');
        if (!btn) return;
        
        e.stopPropagation(); // ソートや行選択のバブリング防止
        const code = btn.dataset.code;
        const assetType = btn.dataset.assetType || 'jp_stock';
        if (!code) return;
        
        runLlmDiagnosis(code, assetType, btn);
    });

    // 6. AI診断実行ロジック
    let currentDiagnoseCode = null;
    let currentDiagnoseAssetType = 'jp_stock';
    const llmCacheBadge = document.getElementById('llm-cache-badge');
    const btnReDiagnoseLlm = document.getElementById('btn-re-diagnose-llm');

    async function runLlmDiagnosis(code, assetType, triggerBtn, force = false) {
        currentDiagnoseCode = code;
        currentDiagnoseAssetType = assetType;

        const asset = allAssetsData.find(a => a.code === code);
        const stockName = asset ? asset.name : code;
        
        if (llmModalTitle) llmModalTitle.textContent = `🤖 AI投資方針適合診断 (${code} ${stockName})`;
        if (llmLoadingContainer) llmLoadingContainer.classList.remove('hidden');
        if (llmResultContainer) llmResultContainer.innerHTML = '';
        if (llmCacheBadge) llmCacheBadge.classList.add('hidden');
        if (llmDiagnosisModal) llmDiagnosisModal.classList.remove('hidden');
        
        if (triggerBtn) triggerBtn.disabled = true;
        
        try {
            const res = await fetch('/api/llm/diagnose', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code: code, asset_type: assetType, force: force })
            });
            
            const data = await res.json();
            if (llmLoadingContainer) llmLoadingContainer.classList.add('hidden');
            
            if (!res.ok || data.error) {
                const errMsg = data.message || data.detail || (typeof data === 'string' ? data : 'AI診断の実行中にエラーが発生しました。');
                renderLlmErrorCard(errMsg);
                return;
            }
            
            // キャッシュバッジの動的表示
            if (llmCacheBadge && data.is_cached) {
                llmCacheBadge.textContent = `⚡ キャッシュ表示 (${data.diagnosed_at || '有効'})`;
                llmCacheBadge.classList.remove('hidden');
            }

            renderLlmResultCard(data, stockName, code);
            
        } catch (e) {
            console.error('LLM Diagnosis error:', e);
            if (llmLoadingContainer) llmLoadingContainer.classList.add('hidden');
            renderLlmErrorCard('通信エラーが発生しました。ネットワーク接続を確認してください。');
        } finally {
            if (triggerBtn) triggerBtn.disabled = false;
        }
    }

    // 「🔄 再診断 (最新データで診断)」ボタンのイベントバインド
    if (btnReDiagnoseLlm) {
        btnReDiagnoseLlm.addEventListener('click', () => {
            if (currentDiagnoseCode) {
                runLlmDiagnosis(currentDiagnoseCode, currentDiagnoseAssetType, btnReDiagnoseLlm, true);
            }
        });
    }

    function renderLlmErrorCard(message) {
        if (!llmResultContainer) return;
        llmResultContainer.innerHTML = `
            <div class="llm-card" style="border-left: 4px solid #ef4444; background: #fef2f2;">
                <h3 style="color: #991b1b; margin-top: 0; font-size: 1rem;">⚠️ 診断を完了できませんでした</h3>
                <p style="color: #7f1d1d; line-height: 1.5; font-size: 0.9rem;">${message}</p>
                <div style="margin-top: 15px;">
                    <button type="button" class="btn-sm btn-outline" id="btn-err-open-policy-config">⚙️ 設定画面を開いて確認</button>
                </div>
            </div>
        `;
        const btnErrConfig = document.getElementById('btn-err-open-policy-config');
        if (btnErrConfig) {
            btnErrConfig.addEventListener('click', () => {
                closeLlmModal();
                if (btnOpenPolicyConfig) btnOpenPolicyConfig.click();
            });
        }
    }

    function renderLlmResultCard(data, stockName, code) {
        if (!llmResultContainer) return;
        
        let fitBadgeClass = 'fit-badge-caution';
        let fitBadgeIcon = '🟡';
        if (data.fit_level === 'fit') {
            fitBadgeClass = 'fit-badge-fit';
            fitBadgeIcon = '🟢';
        } else if (data.fit_level === 'unfit') {
            fitBadgeClass = 'fit-badge-unfit';
            fitBadgeIcon = '🔴';
        }

        const html = `
            <div class="llm-card">
                <div class="llm-card-header">
                    <div>
                        <span class="fit-badge ${fitBadgeClass}">
                            ${fitBadgeIcon} ${data.decision_label || '適合度評価完了'}
                        </span>
                        <span class="llm-confidence-tag">
                            確信度: ${data.confidence_score}%
                        </span>
                    </div>
                    <small class="llm-model-tag">Model: ${data.model_used || 'Gemini'}</small>
                </div>

                <div class="llm-meta-strip">
                    【概算配当利回り】 ${data.estimated_yield} | 【S株購入目安】 ${data.recommended_shares}
                </div>

                <div class="llm-grid-container">
                    <div class="llm-column">
                        <div class="llm-section-block theme-highlight-summary">
                            <div class="llm-section-title">📌 総合判定サマリー</div>
                            <div class="llm-text-content">${data.summary || '判定完了'}</div>
                        </div>

                        <div class="llm-section-block">
                            <div class="llm-section-title">📊 直近の業績動向と収益力</div>
                            <div class="llm-text-content">${data.performance_summary || 'データなし'}</div>
                        </div>

                        <div class="llm-section-block">
                            <div class="llm-section-title">📉 材料出尽くし・反転シグナル分析</div>
                            <div class="llm-text-content">${data.material_exhaustion_eval || '定量的データおよびマクロ動向を分析済みです。'}</div>
                        </div>

                        <div class="llm-section-block">
                            <div class="llm-section-title">📈 トレンド評価 (75日・200日移動平均)</div>
                            <div class="llm-text-content">${data.trend_analysis || '移動平均データおよびトレンド分析結果は正常に処理されました。'}</div>
                        </div>
                    </div>

                    <div class="llm-column">
                        <div class="llm-section-block">
                            <div class="llm-section-title">🛡️ 「還元の盾」とバリュエーション評価</div>
                            <div class="llm-text-content">${data.shield_and_valuation || 'データなし'}</div>
                        </div>

                        <div class="llm-section-block">
                            <div class="llm-section-title">🏢 10年スパンの事業評価（強みとリスク）</div>
                            <div class="llm-text-content">${data.business_10y_eval || 'データなし'}</div>
                        </div>

                        <div class="llm-section-block theme-highlight-action">
                            <div class="llm-section-title">💡 本システムでの立ち回りアドバイス</div>
                            <div class="llm-text-content">${data.tactical_advice || 'データなし'}</div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        llmResultContainer.innerHTML = html;
    }



    // --- 初期実行 ---
    const initialCachedState = window.appState.getState('portfolio');
    if (initialCachedState) {
        allAssetsData = Array.isArray(initialCachedState) ? initialCachedState : (initialCachedState.data || []);
        if (initialCachedState.metadata) renderUpdateReport(initialCachedState.metadata);
        updateIndustryFilterOptions();
        filterAndRender();
    } else { loadAssetsFromStorage(); }
    fetchAndRenderAllData(false);
    checkAndShowSplitAlerts(); // 初期表示時に確実にアラートをフェッチする (新規)

    // --- バックグラウンド同期進捗バナー制御 (#262) ---
    let syncIntervalId = null;

    let syncCompletedTimerId = null;

    async function checkSyncStatus() {
        try {
            const response = await fetch('/api/portfolio/sync_status');
            if (!response.ok) return;
            const statusData = await response.json();
            const bannerEl = document.getElementById('sync-status-banner');
            if (!bannerEl) return;

            if (!statusData.is_syncing && statusData.status === 'idle') {
                bannerEl.classList.add('hidden');
                if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                if (syncIntervalId) { clearInterval(syncIntervalId); syncIntervalId = null; }
                return;
            }

            bannerEl.classList.remove('hidden');
            bannerEl.className = 'sync-status-banner';

            if (statusData.is_syncing && statusData.status === 'syncing') {
                isSyncing = true;
                if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                if (updateReportContainer) updateReportContainer.classList.add('hidden');
                bannerEl.classList.add('status-syncing');
                const currName = statusData.current_name || statusData.current_code || '';
                bannerEl.innerHTML = `
                    <span>🔄 前日・過去データを表示中（バックグラウンドで最新データを更新中: <strong>${statusData.completed_count} / ${statusData.total_count}</strong>件完了 | 現在: ${currName}）</span>
                    <small style="opacity: 0.8;">※画面操作はそのまま可能です</small>
                `;
            } else {
                isSyncing = false;
                if (statusData.status === 'completed') {
                    bannerEl.classList.add('status-completed');
                    const lastTime = statusData.last_completed_at ? new Date(statusData.last_completed_at).toLocaleString() : '';
                    bannerEl.innerHTML = `
                        <span>✅ 最新データへの更新が完了しました (${lastTime})</span>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <button type="button" onclick="location.reload()" class="btn-outline" style="padding: 2px 8px; font-size: 0.75rem;">画面を更新</button>
                            <button type="button" class="disclaimer-close-btn btn-close-sync-status" title="閉じる" aria-label="閉じる">&times;</button>
                        </div>
                    `;

                    const btnCloseSync = bannerEl.querySelector('.btn-close-sync-status');
                    if (btnCloseSync) {
                        btnCloseSync.onclick = () => {
                            bannerEl.classList.add('hidden');
                            if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                        };
                    }

                    if (syncCompletedTimerId) clearTimeout(syncCompletedTimerId);
                    syncCompletedTimerId = setTimeout(() => {
                        bannerEl.classList.add('hidden');
                        syncCompletedTimerId = null;
                    }, 5000);

                    if (syncIntervalId) { clearInterval(syncIntervalId); syncIntervalId = null; }
                } else if (statusData.status === 'circuit_broken') {
                    if (syncCompletedTimerId) { clearTimeout(syncCompletedTimerId); syncCompletedTimerId = null; }
                    bannerEl.classList.add('status-circuit-broken');
                    bannerEl.innerHTML = `
                        <span>⚠️ ${statusData.error_message || 'アクセス制限を検知したため安全停止しました'}</span>
                    `;
                    if (syncIntervalId) { clearInterval(syncIntervalId); syncIntervalId = null; }
                }
            }
        } catch (e) {
            console.error('Failed to check sync status:', e);
        }
    }

    function initSyncStatusPolling() {
        checkSyncStatus();
        if (!syncIntervalId) {
            syncIntervalId = setInterval(checkSyncStatus, 3000);
        }
    }

    initSyncStatusPolling();

    // 過去の免責バナー閉じる記憶キーの自動クリーンアップ (常時表示仕様 #288)
    localStorage.removeItem('disclaimer_agreed');

    // --- 絞り込み銘柄 AI購入推奨 Top 5 レポート制御 (#313) ---
    const recommendFilteredBtn = document.getElementById('recommend-filtered-stocks-btn');
    const filteredRecModal = document.getElementById('filtered-recommendation-modal');
    const filteredRecCloseBtn = document.getElementById('btn-close-filtered-rec-modal');
    const filteredRecCloseFooterBtn = document.getElementById('btn-close-filtered-rec-modal-footer');
    const filteredRecRefreshBtn = document.getElementById('btn-refresh-filtered-rec');
    const filteredRecCopyBtn = document.getElementById('btn-copy-filtered-rec-report');
    const filteredRecSummaryBox = document.getElementById('filtered-rec-summary-box');
    const filteredRecLoading = document.getElementById('filtered-rec-loading');
    const filteredRecResultsContainer = document.getElementById('filtered-rec-results-container');

    let currentRecReportData = null;

    function openFilteredRecModal() {
        if (filteredRecModal) filteredRecModal.classList.remove('hidden');
    }

    function closeFilteredRecModal() {
        if (filteredRecModal) filteredRecModal.classList.add('hidden');
    }

    if (filteredRecCloseBtn) filteredRecCloseBtn.addEventListener('click', closeFilteredRecModal);
    if (filteredRecCloseFooterBtn) filteredRecCloseFooterBtn.addEventListener('click', closeFilteredRecModal);

    async function fetchAndRenderFilteredRecommendations(force = false) {
        let presetName = 'カスタム絞り込み';

        if (activePresetId && QUICK_PRESETS[activePresetId]) {
            const names = {
                'quick-dip-payout': '🔥 買い場×適正配当',
                'quick-bargain': '🎁 格安仕込み',
                'quick-managed': '💼 保有株のみ'
            };
            presetName = names[activePresetId] || presetName;
        } else if (activePresetId) {
            const customPresets = getCustomPresets();
            const found = customPresets.find(p => p.id === activePresetId);
            if (found) presetName = `⭐ ${found.name}`;
        }

        if (!currentFilteredAssets || currentFilteredAssets.length === 0) {
            showAlert('現在表示・絞り込まれている銘柄が0件のため、AI診断を実行できません。フィルタ条件を変更してください。', 'warning');
            openFilteredRecModal();
            if (filteredRecLoading) filteredRecLoading.classList.add('hidden');
            if (filteredRecSummaryBox) {
                filteredRecSummaryBox.innerHTML = `
                    <span>🔍 対象銘柄数: <strong>0件</strong></span>
                    <span class="preset-divider">|</span>
                    <span>条件: <strong>${escapeHtml(presetName)}</strong></span>
                `;
            }
            if (filteredRecResultsContainer) {
                filteredRecResultsContainer.innerHTML = `
                    <div class="alert alert-warning my-3 text-center p-4">
                        <h5 class="fw-bold mb-2">⚠️ 該当する銘柄が 0 件です</h5>
                        <p class="mb-0">現在のフィルタ条件（${escapeHtml(presetName)}）に合致する銘柄がポートフォリオ内に存在しません。<br>他のプリセットを選択するか、検索キーワード・フィルタ条件を変更して再試行してください。</p>
                    </div>
                `;
            }
            if (filteredRecCopyBtn) filteredRecCopyBtn.disabled = true;
            return;
        }

        if (filteredRecCopyBtn) filteredRecCopyBtn.disabled = false;
        const codes = currentFilteredAssets.map(a => String(a.code));

        openFilteredRecModal();

        if (filteredRecSummaryBox) {
            filteredRecSummaryBox.innerHTML = `
                <span>🔍 対象銘柄数: <strong>${codes.length}件</strong></span>
                <span class="preset-divider">|</span>
                <span>条件: <strong>${escapeHtml(presetName)}</strong></span>
            `;
        }

        if (filteredRecLoading) filteredRecLoading.classList.remove('hidden');
        if (filteredRecResultsContainer) filteredRecResultsContainer.innerHTML = '';

        try {
            const res = await fetch('/api/ai-diagnosis/filtered-recommendations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    filtered_codes: codes,
                    asset_type: activeTab,
                    preset_name: presetName,
                    force: force
                })
            });

            const data = await res.json();
            if (filteredRecLoading) filteredRecLoading.classList.add('hidden');

            if (!res.ok || data.error) {
                if (data.error_code === 'NO_API_KEY') {
                    if (filteredRecResultsContainer) {
                        filteredRecResultsContainer.innerHTML = `
                            <div class="alert alert-warning my-3 text-center">
                                <h5>⚠️ APIキー未設定</h5>
                                <p>${escapeHtml(data.message)}</p>
                                <button type="button" class="btn btn-primary btn-sm mt-2" onclick="closeFilteredRecModal(); document.getElementById('btn-open-investment-policy-modal').click();">
                                    ⚙️ 投資方針設定を開く
                                </button>
                            </div>
                        `;
                    }
                    return;
                }
                throw new Error(data.message || 'AI購入推奨レポートの生成に失敗しました');
            }

            currentRecReportData = data;
            renderFilteredRecommendationReport(data);

        } catch (err) {
            console.error('AI購入推奨診断エラー:', err);
            if (filteredRecLoading) filteredRecLoading.classList.add('hidden');
            if (filteredRecResultsContainer) {
                filteredRecResultsContainer.innerHTML = `
                    <div class="alert alert-danger my-3">
                        ❌ エラー: ${escapeHtml(err.message)}
                    </div>
                `;
            }
        }
    }

    function renderFilteredRecommendationReport(data) {
        if (!filteredRecResultsContainer) return;

        const recs = data.recommendations || [];
        const summary = data.overall_summary || '';

        if (recs.length === 0) {
            filteredRecResultsContainer.innerHTML = `
                <div class="alert alert-info my-3 text-center">
                    推薦条件に合致する銘柄が見つかりませんでした。
                </div>
            `;
            return;
        }

        const rankBadges = ['🥇 1位', '🥈 2位', '🥉 3位', '4位', '5位'];
        const rankClasses = ['rank-1', 'rank-2', 'rank-3', 'rank-4', 'rank-5'];

        let cardsHtml = recs.map((item, idx) => {
            const badge = rankBadges[idx] || `${item.rank || idx + 1}位`;
            const rankClass = rankClasses[idx] || 'rank-5';
            const fitStars = item.fit_stars || '★★★★☆';
            const fitScore = item.fit_score !== undefined ? item.fit_score : 85;

            return `
                <div class="recommendation-card ${rankClass} mb-3">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center gap-2">
                            <span class="rank-badge ${rankClass}">${badge}</span>
                            <h4 style="margin: 0; font-size: 1.1rem; font-weight: bold;">
                                ${escapeHtml(item.name || item.code)}
                                <small class="text-muted" style="font-size: 0.8rem;">(${escapeHtml(item.code)})</small>
                            </h4>
                            <span class="badge bg-secondary" style="font-size: 0.75rem;">${escapeHtml(item.industry || '')}</span>
                        </div>
                        <div class="fit-score-box text-end">
                            <span class="fit-stars" style="color: #f59e0b; font-size: 0.95rem;">${escapeHtml(fitStars)}</span>
                            <span class="badge bg-primary ms-1" style="font-size: 0.8rem;">適合度 ${fitScore}%</span>
                        </div>
                    </div>
                    <div class="card-body" style="padding: 10px 14px;">
                        <div class="rec-section mb-2">
                            <strong class="text-success">💡 購入推奨の強み・根拠:</strong>
                            <p style="margin: 2px 0 6px 0; font-size: 0.88rem; line-height: 1.45;">${escapeHtml(item.rationale || '')}</p>
                        </div>
                        <div class="rec-section mb-2">
                            <strong class="text-warning">⚠️ リスク・注意点:</strong>
                            <p style="margin: 2px 0 6px 0; font-size: 0.85rem; line-height: 1.45;">${escapeHtml(item.risk_factor || '')}</p>
                        </div>
                        ${item.portfolio_advice ? `
                            <div class="rec-section">
                                <strong class="text-info">📌 ポートフォリオ組入アドバイス:</strong>
                                <p style="margin: 2px 0 0 0; font-size: 0.85rem; line-height: 1.45;">${escapeHtml(item.portfolio_advice)}</p>
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');

        let overallHtml = '';
        if (summary) {
            overallHtml = `
                <div class="alert alert-purple mt-3 mb-2" style="background: rgba(147, 51, 234, 0.08); border: 1px solid rgba(147, 51, 234, 0.25); border-radius: 8px; padding: 12px 16px;">
                    <h5 style="margin: 0 0 6px 0; color: #7e22ce; font-size: 0.95rem; font-weight: bold;">📝 絞り込み銘柄群全体の総評</h5>
                    <p style="margin: 0; font-size: 0.88rem; line-height: 1.5; color: var(--text-color);">${escapeHtml(summary)}</p>
                </div>
            `;
        }

        filteredRecResultsContainer.innerHTML = cardsHtml + overallHtml;
    }

    if (recommendFilteredBtn) {
        recommendFilteredBtn.addEventListener('click', () => {
            fetchAndRenderFilteredRecommendations(false);
        });
    }

    if (filteredRecRefreshBtn) {
        filteredRecRefreshBtn.addEventListener('click', () => {
            fetchAndRenderFilteredRecommendations(true);
        });
    }

    if (filteredRecCopyBtn) {
        filteredRecCopyBtn.addEventListener('click', () => {
            if (!currentRecReportData || !currentRecReportData.recommendations) {
                alert('コピーするレポートがありません。');
                return;
            }

            const data = currentRecReportData;
            let text = `🤖 【AI厳選】購入推奨銘柄 Top 5 レポート\n`;
            text += `対象プリセット/条件: ${data.preset_name || 'カスタム絞り込み'}\n`;
            text += `分析対象数: ${data.total_candidates || 0}件\n`;
            text += `----------------------------------------\n\n`;

            (data.recommendations || []).forEach((item, idx) => {
                text += `【${item.rank || idx + 1}位】 ${item.name} (${item.code}) / ${item.industry}\n`;
                text += `適合度: ${item.fit_stars} (${item.fit_score}%)\n`;
                text += `・根拠: ${item.rationale}\n`;
                text += `・注意点: ${item.risk_factor}\n`;
                if (item.portfolio_advice) text += `・アドバイス: ${item.portfolio_advice}\n`;
                text += `\n`;
            });

            if (data.overall_summary) {
                text += `■ 絞り込み総評:\n${data.overall_summary}\n`;
            }

            navigator.clipboard.writeText(text).then(() => {
                showAlert('レポートテキストをクリップボードにコピーしました！', 'success');
            }).catch(e => {
                console.error('コピー失敗:', e);
                alert('コピーに失敗しました。');
            });
        });
    }

    // --- 主要指数フィボナッチ参照モーダル制御 (#231) ---
    if (typeof initMarketFibonacciModal === 'function') {
        initMarketFibonacciModal();
    }
});
