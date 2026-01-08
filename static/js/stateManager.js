// static/js/stateManager.js

/**
 * アプリケーション全体の状態を管理するオブジェクト（メモリキャッシュ）
 */
const state = {
    global: {
        data: null,
        lastFetchTime: null,
    }
};

// バックエンドのAPIクールダウン設定（秒）
const API_COOLDOWN_SECONDS = 10;
const SESSION_STORAGE_KEY = 'globalLastFetchTime';

/**
 * 全件更新系APIを呼び出してよいかチェックする。
 * まずメモリキャッシュを確認し、なければsessionStorageから最終取得時刻を読み込む。
 * @returns {boolean} - API呼び出しが許可される場合はtrue
 */
function canFetch() {
    // 1. メモリ上の最終取得時刻を確認
    let lastFetchTime = state.global.lastFetchTime;

    // 2. メモリになければ、sessionStorageから読み込みを試みる
    if (!lastFetchTime) {
        const storedTime = sessionStorage.getItem(SESSION_STORAGE_KEY);
        if (storedTime) {
            lastFetchTime = new Date(storedTime);
            state.global.lastFetchTime = lastFetchTime; // メモリにもキャッシュする
        }
    }

    // 3. 最終取得時刻がなければ、API呼び出しを許可
    if (!lastFetchTime) {
        return true;
    }

    // 4. 最終取得時刻と現在時刻を比較して、クールダウン期間を過ぎているか判定
    const now = new Date();
    const secondsSinceLastFetch = (now - lastFetchTime) / 1000;
    return secondsSinceLastFetch > API_COOLDOWN_SECONDS;
}

/**
 * 状態を新しいデータと時刻で更新する。
 * メモリキャッシュとsessionStorageの両方に最終取得時刻を保存する。
 * @param {any} data - APIから取得した新しいデータ
 */
function updateState(data) {
    const now = new Date();
    state.global.data = data;
    state.global.lastFetchTime = now;
    // sessionStorageにはDateオブジェクトをISO文字列形式で保存
    sessionStorage.setItem(SESSION_STORAGE_KEY, now.toISOString());
}

/**
 * 現在メモリキャッシュに保持している状態（データ）を取得する
 * @returns {any|null} - 保持しているデータ、なければnull
 */
function getState() {
    return state.global.data;
}

/**
 * 状態をクリアする。
 * メモリキャッシュとsessionStorageの両方から最終取得時刻を削除する。
 */
function clearState() {
    state.global.data = null;
    state.global.lastFetchTime = null;
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

// 他のJSファイルからアクセスできるよう、windowオブジェクトに公開する
window.appState = {
    canFetch,
    updateState,
    getState,
    clearState,
};
