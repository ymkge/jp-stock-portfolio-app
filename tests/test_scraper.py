import pytest
from scraper import BaseScraper, JPStockScraper

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
