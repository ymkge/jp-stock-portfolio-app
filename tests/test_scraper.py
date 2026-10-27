import pytest
from scraper import BaseScraper, JPStockScraper, InvestTrustScraper

class MockScraper(BaseScraper):
    def fetch_data(self, code):
        pass

def test_extract_next_data():
    scraper = MockScraper()
    html = 'self.__next_f.push([1, "{\\"foo\\":\\"bar\\"}"])'
    # BaseScraper._extract_next_data performs unescaping
    result = scraper._extract_next_data(html)
    assert result == '{"foo":"bar"}'

def test_extract_legacy_data():
    scraper = MockScraper()
    html = '<script>__PRELOADED_STATE__ = {"a":1}</script>'
    result = scraper._extract_legacy_data(html)
    assert result == '{"a":1}'

def test_calculate_moving_average():
    scraper = JPStockScraper()
    histories = [
        {"closePrice": "110"},
        {"closePrice": "120"},
        {"closePrice": "130"},
        {"closePrice": "140"},
        {"closePrice": "150"}
    ]
    # (110+120+130)/3 = 120
    assert scraper._calculate_moving_average(histories, 3) == 120.0
    # 乖離が大きすぎるデータは除外
    histories_with_outlier = [
        {"closePrice": "100"},
        {"closePrice": "1000"}, # Outlier
        {"closePrice": "100"}
    ]
    # cur_p = 100 なら 1000 は (1000-100)/100 = 9.0 > 2.0 なので除外される
    # 残った2つの平均は 100、要素数が足りないので None になるはず（days=3）
    assert scraper._calculate_moving_average(histories_with_outlier, 3, cur_p=100.0) is None

def test_calculate_fibonacci():
    scraper = JPStockScraper()
    histories = [
        {"closePrice": "150"}, # current (first in list)
        {"closePrice": "200"}, # high
        {"closePrice": "100"}  # low
    ]
    # hi=200, lo=100, cur=150. (200-150)/(200-100) = 50/100 = 50%
    result = scraper._calculate_fibonacci(histories)
    assert result["retracement"] == 50.0
    assert result["high"] == 200.0
    assert result["low"] == 100.0

def test_jp_stock_scraper_fetch_data_mock(mocker):
    scraper = JPStockScraper()
    
    # mock _make_request to avoid real network calls
    mock_res_q = mocker.Mock()
    mock_res_q.text = 'self.__next_f.push([1, "{\\"name\\":\\"Test Stock\\",\\"per\\":{\\"value\\":\\"15.0\\"}}"])'
    
    mock_res_h = mocker.Mock()
    mock_res_h.text = 'self.__next_f.push([1, "[{\\"date\\":\\"2024/01/01\\",\\"values\\":[\\"1000\\",\\"1010\\",\\"990\\",\\"1000\\",\\"10000\\",\\"1000\\",\\"0\\"]}]"])'
    
    mock_res_d = mocker.Mock()
    mock_res_d.text = 'self.__next_f.push([1, "{\\"dividend\\":[]}"])'
    
    mocker.patch.object(scraper, '_make_request', side_effect=[mock_res_q, mock_res_h, mock_res_d])
    mocker.patch('history_manager.get_historical_data_for_analysis', return_value=[])
    
    # Note: _scavenge_common_data needs real regex matching on html/json
    # For simplicity, we'll mock that too if needed, but let's see if it works with minimal mock
    
    data = scraper.fetch_data("8001")
    assert data["code"] == "8001"
    assert data["per"] == "15.0"


def test_jp_stock_scraper_quote_symbol_issue294():
    """案件 #294: JPStockScraper の _get_quote_symbol が 6623.N や 7203 を正しく処理するかテスト"""
    scraper = JPStockScraper()
    assert scraper._get_quote_symbol("6623.N") == "6623.N"
    assert scraper._get_quote_symbol("7203.T") == "7203.T"
    assert scraper._get_quote_symbol("7203") == "7203.T"
    assert scraper._get_quote_symbol("130A") == "130A.T"


def test_jp_stock_scraper_dividend_split_mismatch_correction(mocker):
    """案件 #330: トップページDPSが分割前のままで、詳細タブの dividend_history に分割後DPSがある場合の自動補正テスト"""
    scraper = JPStockScraper()

    # モックレスポンス:
    # 1. quote (トップページ): dps: 180, price: 3357
    mock_res_q = mocker.Mock()
    mock_res_q.text = '''self.__next_f.push([1, "{\\"name\\":\\"三井住友FG\\",\\"price\\":{\\"value\\":\\"3357\\"},\\"dps\\":{\\"value\\":\\"180\\"}}"])'''

    # 2. history: 空
    mock_res_h = mocker.Mock()
    mock_res_h.text = 'self.__next_f.push([1, "[]"])'

    # 3. dividend: 2027年 90.0円 (JSON形式)
    mock_res_d = mocker.Mock()
    mock_res_d.text = 'self.__next_f.push([1, "[{\\"settlementDate\\":\\"202703\\",\\"annualForecastValue\\":\\"90.0\\"}]"])'

    mocker.patch.object(scraper, '_make_request', side_effect=[mock_res_q, mock_res_h, mock_res_d])
    mocker.patch('history_manager.get_historical_data_for_analysis', return_value=[])

    data = scraper.fetch_data("8316")
    # トップページの180.0ではなく、詳細タブの90.0が採用されること
    assert data["annual_dividend"] == 90.0
    # 90.0 / 3357 * 100 = 2.68% に計算されること
    assert data["yield"] == "2.68"


# --- 投資信託の純資産総額・信託報酬 3層フォールバックテスト (#364) ---

def test_invest_trust_parse_and_format_net_assets():
    """純資産総額の正規化ヘルパー関数の検証"""
    # 百万円単位
    m_cap, n_assets = InvestTrustScraper._parse_and_format_net_assets("13,983,739", "百万円")
    assert m_cap == "13983739000000"
    assert n_assets == "13.98兆円"

    # 億円単位
    m_cap, n_assets = InvestTrustScraper._parse_and_format_net_assets("4388.78", "億円")
    assert m_cap == "438878000000"
    assert n_assets == "4388.78億円"

    # 兆円単位
    m_cap, n_assets = InvestTrustScraper._parse_and_format_net_assets("1.25", "兆円")
    assert m_cap == "1250000000000"
    assert n_assets == "1.25兆円"

    # 円単位
    m_cap, n_assets = InvestTrustScraper._parse_and_format_net_assets("50000000", "円")
    assert m_cap == "50000000"
    assert n_assets == "50百万円"

    # 不正・無効値
    assert InvestTrustScraper._parse_and_format_net_assets(None) == ("N/A", "N/A")
    assert InvestTrustScraper._parse_and_format_net_assets("") == ("N/A", "N/A")
    assert InvestTrustScraper._parse_and_format_net_assets("abc") == ("N/A", "N/A")
    assert InvestTrustScraper._parse_and_format_net_assets("-100") == ("N/A", "N/A")


def test_invest_trust_format_trust_fee():
    """信託報酬の正規化ヘルパー関数の検証"""
    # %なし数値文字列
    assert InvestTrustScraper._format_trust_fee("0.05775") == "0.05775%"
    # %あり文字列（二重%防止）
    assert InvestTrustScraper._format_trust_fee("0.05775%") == "0.05775%"
    # 空白混入
    assert InvestTrustScraper._format_trust_fee("  0.0938 % ") == "0.0938%"
    # 不正・無効値
    assert InvestTrustScraper._format_trust_fee(None) == "N/A"
    assert InvestTrustScraper._format_trust_fee("") == "N/A"
    assert InvestTrustScraper._format_trust_fee("N/A") == "N/A"
    assert InvestTrustScraper._format_trust_fee("---") == "N/A"
    assert InvestTrustScraper._format_trust_fee("abc") == "N/A"


def test_invest_trust_fetch_tier1_rsc(mocker):
    """Tier 1: 新形式 JSON (Next.js RSC) からの抽出テスト"""
    scraper = InvestTrustScraper()
    mock_res = mocker.Mock()
    # 新形式 Next.js RSC ペイロード
    mock_res.text = '''<title>eMAXIS Slim全世界株式(オール・カントリー)【0331418A】：投資信託 - Yahoo!ファイナンス</title>
self.__next_f.push([1, "{\\"price\\":{\\"value\\":\\"37441\\"},\\"changePrice\\":\\"252\\",\\"changePriceRate\\":\\"0.68\\",\\"items\\":{\\"name\\":\\"純資産残高\\",\\"primary\\":{\\"value\\":\\"13,983,739\\",\\"suffix\\":\\"百万円\\"}},\\"fee_item\\":{\\"name\\":\\"信託報酬\\",\\"primary\\":{\\"value\\":\\"0.05775\\",\\"suffix\\":\\"%\\"}}}\\n"])'''

    mocker.patch.object(scraper, '_make_request', return_value=mock_res)

    data = scraper.fetch_data("0331418A")
    assert data["code"] == "0331418A"
    assert data["name"] == "eMAXIS Slim全世界株式(オール・カントリー)"
    assert data["price"] == "37441"
    assert data["change"] == "252"
    assert data["change_percent"] == "0.68"
    assert data["net_assets"] == "13.98兆円"
    assert data["market_cap"] == "13983739000000"
    assert data["trust_fee"] == "0.05775%"


def test_invest_trust_fetch_tier2_legacy(mocker):
    """Tier 2: 旧形式 JSON (Legacy) からの後方互換抽出テスト"""
    scraper = InvestTrustScraper()
    mock_res = mocker.Mock()
    # 旧形式 JSON ペイロード
    mock_res.text = '''<title>SBI・V・S&P500インデックス・ファンド【89311199】：投資信託 - Yahoo!ファイナンス</title>
<script>__PRELOADED_STATE__ = {
        "price": "41424",
        "changePrice": "322",
        "changePriceRate": "0.78",
        "mainFundDetail": {
            "items": {
                "netAssetBalance": {"price": "3078221"},
                "payRateTotal": {"rate": "0.0938"}
            }
        }
    }</script>'''

    mocker.patch.object(scraper, '_make_request', return_value=mock_res)

    data = scraper.fetch_data("89311199")
    assert data["code"] == "89311199"
    assert data["name"] == "SBI・V・S&P500インデックス・ファンド"
    assert data["price"] == "41424"
    assert data["net_assets"] == "3.08兆円"
    assert data["market_cap"] == "3078221000000"
    assert data["trust_fee"] == "0.0938%"


def test_invest_trust_fetch_tier3_html(mocker):
    """Tier 3: HTML 直接抽出フォールバック（順位テキスト混入あり）のテスト"""
    scraper = InvestTrustScraper()
    mock_res = mocker.Mock()
    # JSONなし、HTMLのみのレスポンス
    mock_res.text = '''<html><body>
        <h1>eMAXIS Slim米国株式(S&P500)</h1>
        <dl>
            <dt><span>基準価額</span></dt><dd>44,590円</dd>
            <dt><span>純資産残高</span></dt><dd>1位13,074,192百万円</dd>
            <dt><span>信託報酬</span></dt><dd>10位0.0814%</dd>
        </dl>
    </body></html>'''

    mocker.patch.object(scraper, '_make_request', return_value=mock_res)

    data = scraper.fetch_data("03311187")
    assert data["code"] == "03311187"
    assert data["net_assets"] == "13.07兆円"
    assert data["market_cap"] == "13074192000000"
    assert data["trust_fee"] == "0.0814%"


def test_invest_trust_fetch_failure_fallback(mocker):
    """全層マッチ失敗時（データ欠損時）に N/A を安全に返すフェイルセーフテスト"""
    scraper = InvestTrustScraper()
    mock_res = mocker.Mock()
    mock_res.text = '''<html><body><h1>Empty Fund</h1></body></html>'''

    mocker.patch.object(scraper, '_make_request', return_value=mock_res)

    data = scraper.fetch_data("99999999")
    assert data["code"] == "99999999"
    assert data["net_assets"] == "N/A"
    assert data["market_cap"] == "N/A"
    assert data["trust_fee"] == "N/A"


