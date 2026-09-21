"""
日本市場（東京証券取引所）の営業日・休業日・祝日判定モジュール (#323)

jpholiday が利用可能な場合はそれを活用し、
万一ライブラリが未インストールやロード不可の場合でも自律動作する
完全な祝日・国民の休日・振替休日・東証年末年始特例の判定フォールバックを完備。
"""

import math
from datetime import date, datetime, timedelta
from typing import Union, Optional

try:
    import jpholiday
    HAS_JPHOLIDAY = True
except ImportError:
    jpholiday = None
    HAS_JPHOLIDAY = False


def _get_vernal_equinox_day(year: int) -> int:
    """春分の日の日付（日）を算出する（渡辺敏夫の略算式: 1980〜2099年対応）"""
    if 1980 <= year <= 2099:
        return int(20.8431 + 0.242194 * (year - 1980) - int((year - 1980) / 4))
    # 範囲外フォールバック
    return 20 if (year % 4 == 0 or year % 4 == 1) else 21


def _get_autumnal_equinox_day(year: int) -> int:
    """秋分の日の日付（日）を算出する（渡辺敏夫の略算式: 1980〜2099年対応）"""
    if 1980 <= year <= 2099:
        return int(23.2488 + 0.242194 * (year - 1980) - int((year - 1980) / 4))
    # 範囲外フォールバック
    return 23 if (year % 4 == 0 or year % 4 == 1) else 22


def _get_nth_monday(year: int, month: int, n: int) -> date:
    """指定された年月の第n月曜日の日付を取得する"""
    first_day = date(year, month, 1)
    first_day_weekday = first_day.weekday()  # 0=Mon, ..., 6=Sun
    # 最初の月曜日までの日数
    days_to_first_monday = (0 - first_day_weekday) % 7
    first_monday = first_day + timedelta(days=days_to_first_monday)
    return first_monday + timedelta(weeks=n - 1)


def _is_national_holiday_raw(d: date) -> bool:
    """
    指定日そのものが法律で定められた「国民の祝日」そのもの（固定祝日・ハッピーマンデー・春分秋分）か判定する。
    ※振替休日・国民の休日は含まない（これらは別判定）
    """
    y, m, day = d.year, d.month, d.day

    # 1. 固定祝日
    if (m, day) in [
        (1, 1),   # 元日
        (2, 11),  # 建国記念の日
        (4, 29),  # 昭和の日
        (5, 3),   # 憲法記念日
        (5, 4),   # みどりの日
        (5, 5),   # こどもの日
        (11, 3),  # 文化の日
        (11, 23), # 勤労感謝の日
    ]:
        return True

    # 天皇誕生日 (2020年以降は2/23、1989-2018年は12/23)
    if y >= 2020 and (m, day) == (2, 23):
        return True
    if 1989 <= y <= 2018 and (m, day) == (12, 23):
        return True

    # 山の日 (2016年以降。2020, 2021年のオリンピック特例は後述)
    if y >= 2016:
        if y == 2020 and (m, day) == (8, 10):
            return True
        elif y == 2021 and (m, day) == (8, 8):
            return True
        elif y not in (2020, 2021) and (m, day) == (8, 11):
            return True

    # 2. ハッピーマンデー制度祝日 (2000年以降順次導入)
    # 成人の日: 1月第2月曜日 (2000年以降)
    if y >= 2000 and m == 1 and d == _get_nth_monday(y, 1, 2):
        return True
    elif y < 2000 and (m, day) == (1, 15):
        return True

    # 海の日: 7月第3月曜日 (2003年以降)
    if y >= 2003:
        if y == 2020 and (m, day) == (7, 23):
            return True
        elif y == 2021 and (m, day) == (7, 22):
            return True
        elif y not in (2020, 2021) and m == 7 and d == _get_nth_monday(y, 7, 3):
            return True
    elif 1996 <= y < 2003 and (m, day) == (7, 20):
        return True

    # 敬老の日: 9月第3月曜日 (2003年以降)
    if y >= 2003 and m == 9 and d == _get_nth_monday(y, 9, 3):
        return True
    elif y < 2003 and (m, day) == (9, 15):
        return True

    # スポーツの日 (体育の日): 10月第2月曜日 (2000年以降)
    if y >= 2000:
        if y == 2020 and (m, day) == (7, 24):
            return True
        elif y == 2021 and (m, day) == (7, 23):
            return True
        elif y not in (2020, 2021) and m == 10 and d == _get_nth_monday(y, 10, 2):
            return True
    elif y < 2000 and (m, day) == (10, 10):
        return True

    # 3. 春分の日・秋分の日
    if m == 3 and day == _get_vernal_equinox_day(y):
        return True
    if m == 9 and day == _get_autumnal_equinox_day(y):
        return True

    # 2019年即位特例 (2019年5月1日、10月22日)
    if y == 2019 and (m, day) in [(5, 1), (10, 22)]:
        return True

    return False


def _is_holiday_fallback(d: date) -> bool:
    """
    jpholiday ライブラリが存在しない場合の完全自律フォールバック判定。
    国民の祝日、振替休日（2007年改正法準拠）、国民の休日を計算して判定する。
    """
    # 1. 国民の祝日そのものか？
    if _is_national_holiday_raw(d):
        return True

    # 日曜日は祝日判定としてはFalse（週末判定で除外されるが、振替休日の対象日は月〜土）
    if d.weekday() == 6:
        return False

    # 2. 振替休日判定 (2007年改正祝日法: 祝日が日曜の場合、翌日以降の最も近い祝日でない平日)
    # 例: 5/3が日曜の場合、5/4(祝), 5/5(祝)を経て 5/6(水) が振替休日
    curr = d - timedelta(days=1)
    while curr.year >= 1973:
        if _is_national_holiday_raw(curr):
            if curr.weekday() == 6:
                # 祝日かつ日曜日まで連鎖が遡れた ➔ d は振替休日！
                return True
            # 平日祝日ならさらに前日を遡る
            curr -= timedelta(days=1)
        else:
            # 祝日でない日に当たったため振替休日ではない
            break

    # 3. 国民の休日判定 (前日と翌日の双方が国民の祝日である平日)
    # 例: 2026年9月22日（火）= 9/21(敬老の日) と 9/23(秋分の日) の間の平日
    prev_day = d - timedelta(days=1)
    next_day = d + timedelta(days=1)
    if _is_national_holiday_raw(prev_day) and _is_national_holiday_raw(next_day):
        return True

    return False


def is_jp_market_holiday(dt_or_date: Union[datetime, date, str]) -> bool:
    """
    指定された日が日本市場（東京証券取引所）の休業日かどうかを判定する。

    判定基準:
    1. 土曜日・日曜日
    2. 国民の祝日・振替休日・国民の休日
    3. 証券取引所特有の休業日（12/31 大納会翌日、1/2, 1/3 年始休業日）
       ※1/1は元日（国民の祝日）として判定
    """
    if isinstance(dt_or_date, datetime):
        d = dt_or_date.date()
    elif isinstance(dt_or_date, date):
        d = dt_or_date
    elif isinstance(dt_or_date, str):
        try:
            d = datetime.strptime(dt_or_date[:10], "%Y-%m-%d").date()
        except ValueError:
            return False
    else:
        return False

    # 1. 週末判定（土: 5, 日: 6）
    if d.weekday() >= 5:
        return True

    # 2. 証券取引所特有の休業日 (12/31, 1/2, 1/3)
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day in (2, 3)):
        return True

    # 3. 国民の祝日・振替休日・国民の休日判定
    if HAS_JPHOLIDAY and jpholiday:
        try:
            if jpholiday.is_holiday(d):
                return True
        except Exception:
            # 万一の jpholiday 内部エラー時は自律フォールバックを実行
            pass

    # jpholiday が無い、またはフォールバック時
    return _is_holiday_fallback(d)
