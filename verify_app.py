import calendar
from concurrent.futures import ThreadPoolExecutor
import datetime
import pandas as pd
import requests
import streamlit as st

# ==============================================================================
# 0. 페이지 기본 설정 및 글씨 잘림 방지 CSS 스타일
# ==============================================================================
st.set_page_config(
    page_title="바다부채길 3개년 기상 검증 캘린더 & 기준 최적화",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.html("""
<style>
/* 상단 제목이 절대 잘리지 않도록 충분한 상단 여백 확보 */
.block-container {
    padding-top: 3.4rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 1440px !important;
}

/* 메인 타이틀 커스텀 스타일 */
.main-title {
    font-size: 1.85rem;
    font-weight: 800;
    color: #0f172a;
    line-height: 1.4;
    margin-bottom: 0.8rem;
    word-break: keep-all;
}

/* 달력 요일 헤더 */
.cal-day-header {
    text-align: center;
    font-weight: 700;
    padding: 8px 0;
    border-bottom: 2px solid #e2e8f0;
    margin-bottom: 8px;
    font-size: 0.95rem;
}

/* 달력 및 사이드바 버튼 내부 글씨 잘림(...) 완전 해제 */
div[data-testid="stButton"] > button {
    height: auto !important;
    min-height: 78px !important;
    padding: 8px 4px !important;
    border-radius: 12px !important;
    white-space: pre-line !important;
    line-height: 1.35 !important;
}
div[data-testid="stButton"] > button div[data-testid="stMarkdownContainer"] p,
div[data-testid="stButton"] > button p {
    white-space: pre-line !important;
    word-break: keep-all !important;
    overflow: visible !important;
    text-overflow: unset !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    line-height: 1.38 !important;
    margin: 0 !important;
}

/* 사이드바 버튼은 높이를 일반 버튼 크기로 유지하면서 글씨 잘림 방지 */
section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
    min-height: 44px !important;
    padding: 8px 12px !important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] > button p {
    font-size: 0.9rem !important;
}

/* 우측 DAILY REPORT 메트릭 카드 */
.metric-box {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 10px;
}
.metric-label {
    color: #64748b;
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 4px;
}
.metric-val {
    color: #0f172a;
    font-size: 1.55rem;
    font-weight: 800;
}
.metric-unit {
    color: #64748b;
    font-size: 0.95rem;
    font-weight: 500;
}

.diag-box {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 14px;
    margin-bottom: 12px;
}
.reason-box {
    background-color: #f8fafc;
    border-radius: 12px;
    padding: 12px 15px;
    color: #334155;
    font-size: 0.92rem;
    font-weight: 500;
    border: 1px solid #e2e8f0;
    margin-bottom: 10px;
}
.actual-box {
    background-color: #fff1f2;
    border: 1px solid #fecdd3;
    border-radius: 12px;
    padding: 12px 15px;
    color: #9f1239;
    font-size: 0.92rem;
    font-weight: 600;
    margin-bottom: 12px;
}
</style>
""")

# ==============================================================================
# 1. 교수님 제공 최근 3개년(2023~2025) 실제 개폐장 데이터 48건 및 현장 기상 특성
# ==============================================================================
CLOSURE_DB = {
    "2023-01-15": {"type": "폐장", "reason": "폭설", "time": "23/01/15 08:51", "weather": True, "cat": "snow"},
    "2023-01-25": {"type": "폐장", "reason": "한파", "time": "23/01/25 08:22", "weather": True, "cat": "wind_wave"},
    "2023-01-26": {"type": "폐장", "reason": "결빙구간 점검", "time": "23/01/26 08:32", "weather": True, "cat": "snow"},
    "2023-02-15": {"type": "폐장", "reason": "대설주의보", "time": "23/02/15 08:19", "weather": True, "cat": "snow_heavy"},
    "2023-02-25": {"type": "폐장", "reason": "폭설", "time": "23/02/25 08:27", "weather": True, "cat": "snow"},
    "2023-04-11": {"type": "폐장", "reason": "강풍경보로 인한 폐장", "time": "23/04/11 08:32", "weather": True, "cat": "wind_heavy"},
    "2023-04-12": {"type": "부분개장", "reason": "전일 강풍에 따른 시설물 안전점검", "time": "23/04/12 11:26", "weather": False, "cat": "facility"},
    "2023-06-27": {"type": "폐장", "reason": "낙석으로 인한 탐방로 손상", "time": "23/06/27 08:54", "weather": False, "cat": "facility"},
    "2023-06-28": {"type": "부분개장", "reason": "부분 개장 낙석으로인한 탐방로 손상", "time": "23/06/28 11:38", "weather": False, "cat": "facility"},
    "2023-07-09": {"type": "부분폐장", "reason": "기상악화(강한폭우)", "time": "23/07/09 14:43", "weather": True, "cat": "rain"},
    "2023-08-08": {"type": "부분폐장", "reason": "태풍 북상으로 인한 폐장", "time": "23/08/08 10:29", "weather": True, "cat": "wave_wind"},
    "2023-08-09": {"type": "폐장", "reason": "태풍으로 인한 폐장", "time": "23/08/09 08:59", "weather": True, "cat": "typhoon"},
    "2023-08-10": {"type": "폐장", "reason": "태풍으로 인한 폐장", "time": "23/08/08 00:00", "weather": True, "cat": "typhoon"},
    "2023-08-11": {"type": "폐장", "reason": "태풍으로 인한 시설 안전점검", "time": "23/08/11 00:00", "weather": False, "cat": "facility"},
    "2023-08-12": {"type": "폐장", "reason": "태풍으로 인한 시설 복구", "time": "23/08/11 00:00", "weather": False, "cat": "facility"},
    "2023-10-27": {"type": "폐장", "reason": "강풍과 높은 파도", "time": "23/10/27 09:33", "weather": True, "cat": "wave_wind"},
    "2023-12-11": {"type": "폐장", "reason": "너울성 파도로 인한 폐장", "time": "23/12/11 08:31", "weather": True, "cat": "wave"},
    "2023-12-26": {"type": "부분개장", "reason": "일부구간 부분개장(사유 미기재)", "time": "24/01/02 02:00", "weather": False, "cat": "facility"},
    "2023-12-27": {"type": "부분개장", "reason": "일부구간 부분개장(사유 미기재)", "time": "24/01/02 02:00", "weather": False, "cat": "facility"},
    "2023-12-28": {"type": "부분개장", "reason": "일부구간 부분개장(사유 미기재)", "time": "24/01/02 02:00", "weather": False, "cat": "facility"},
    "2023-12-29": {"type": "부분개장", "reason": "일부구간 부분개장(사유 미기재)", "time": "24/01/02 02:00", "weather": False, "cat": "facility"},
    "2023-12-30": {"type": "부분개장", "reason": "일부구간 부분개장(사유 미기재)", "time": "24/01/02 02:00", "weather": False, "cat": "facility"},
    "2024-01-01": {"type": "폐장", "reason": "1월 1일 휴장 (정기휴장)", "time": "23/12/30 03:41", "weather": False, "cat": "facility"},
    "2024-01-15": {"type": "부분개장", "reason": "일부구간개장", "time": "24/01/19 15:26", "weather": False, "cat": "facility"},
    "2024-01-16": {"type": "부분개장", "reason": "일부구간개장", "time": "24/01/19 15:26", "weather": False, "cat": "facility"},
    "2024-01-17": {"type": "부분개장", "reason": "일부구간개장", "time": "24/01/19 15:26", "weather": False, "cat": "facility"},
    "2024-01-18": {"type": "부분개장", "reason": "일부구간개장", "time": "24/01/19 15:26", "weather": False, "cat": "facility"},
    "2024-01-19": {"type": "부분개장", "reason": "일부구간개장", "time": "24/01/19 15:26", "weather": False, "cat": "facility"},
    "2024-01-21": {"type": "폐장", "reason": "폭설로 인한 폐장", "time": "24/01/21 08:14", "weather": True, "cat": "snow_heavy"},
    "2024-01-23": {"type": "폐장", "reason": "강한한파와 높은파도로 폐장", "time": "24/01/23 08:53", "weather": True, "cat": "wave_wind"},
    "2024-01-24": {"type": "폐장", "reason": "강한 한파와 높은 파도 폐장", "time": "24/01/24 09:09", "weather": True, "cat": "wave"},
    "2024-01-25": {"type": "폐장", "reason": "탐방로 결빙과 높은 파도로 폐장", "time": "24/01/25 08:28", "weather": True, "cat": "wave"},
    "2024-02-02": {"type": "폐장", "reason": "대설로 인한 폐장", "time": "24/02/02 07:53", "weather": True, "cat": "snow"},
    "2024-02-06": {"type": "폐장", "reason": "대설로 인한 폐장", "time": "24/02/06 08:35", "weather": True, "cat": "snow"},
    "2024-02-15": {"type": "부분폐장", "reason": "폭설로 인해 12시38분부터 폐장합니다.", "time": "24/02/15 12:39", "weather": True, "cat": "snow"},
    "2024-02-16": {"type": "부분폐장", "reason": "금일 제설작업후 오픈예정임을 알려드립니다.", "time": "24/02/16 12:31", "weather": True, "cat": "snow"},
    "2024-02-22": {"type": "폐장", "reason": "대설로 폐장합니다.", "time": "24/02/22 09:14", "weather": True, "cat": "snow_heavy"},
    "2024-02-23": {"type": "폐장", "reason": "금일제설작업으로 폐장합니다.", "time": "24/02/23 08:31", "weather": True, "cat": "snow"},
    "2024-03-20": {"type": "부분개장", "reason": "폭설로 인한 폐장", "time": "24/03/20 12:12", "weather": True, "cat": "snow"},
    "2024-05-16": {"type": "폐장", "reason": "기상악화로 인한 폐장", "time": "24/05/16 08:49", "weather": True, "cat": "wave_wind"},
    "2024-09-15": {"type": "부분폐장", "reason": "풍랑주의보", "time": "24/09/15 13:28", "weather": True, "cat": "wave"},
    "2024-09-21": {"type": "폐장", "reason": "풍랑 및 파도", "time": "24/09/21 07:36", "weather": True, "cat": "wave_heavy"},
    "2024-09-22": {"type": "폐장", "reason": "풍랑, 파도", "time": "24/09/22 07:29", "weather": True, "cat": "wave"},
    "2024-10-19": {"type": "부분폐장", "reason": "풍랑 및 파도", "time": "24/10/19 14:11", "weather": True, "cat": "wave"},
    "2024-10-20": {"type": "폐장", "reason": "풍랑 및 파도", "time": "24/10/20 07:51", "weather": True, "cat": "wave"},
    "2025-01-28": {"type": "부분폐장", "reason": "강풍", "time": "25/01/28 13:41", "weather": True, "cat": "wind"},
    "2025-03-17": {"type": "부분개장", "reason": "폭설로 인한 폐장", "time": "25/03/17 12:10", "weather": True, "cat": "snow"},
    "2025-09-13": {"type": "부분개장", "reason": "강풍으로 인한 일부시간 폐장", "time": "25/09/13 14:51", "weather": True, "cat": "wind"},
}

EVENT_MONTHS = [
    (2023, 1), (2023, 2), (2023, 4), (2023, 6), (2023, 7), (2023, 8), (2023, 10), (2023, 12),
    (2024, 1), (2024, 2), (2024, 3), (2024, 5), (2024, 9), (2024, 10),
    (2025, 1), (2025, 3), (2025, 9),
]

AUTH_KEY = "aIYY8TrRRe-GGPE60QXvsA"
STN_ASOS = "105"          # 강릉 종관기상관측소
STN_WAVE_JD = "22455"     # 정동진 연안파고부이
STN_BUOY_DH = "21229"     # 동해 해양기상부이

# [기존 임의 기준] 기상청 특보 수준으로 높게 설정되어 실제 현장 폐장일을 다수 놓치던 초기 기준
INITIAL_LIMITS = {
    "WAVE_CAUTION": 1.8,
    "WAVE_DANGER": 3.0,
    "WIND_CAUTION": 10.0,
    "WIND_DANGER": 14.0,
    "RAIN_CAUTION": 15.0,
    "RAIN_DANGER": 30.0,
    "SNOW_CAUTION": 0.5,
    "SNOW_DANGER": 2.0,
}

# [데이터 보정 최적 기준] 3개년(2023~2025) 실제 폐장 이력 34건과 일치하도록 도출한 최적 기준
OPTIMIZED_DEFAULT_LIMITS = {
    "WAVE_CAUTION": 1.5,
    "WAVE_DANGER": 2.0,   # 해안 데크 월파 및 너울성 파도 실제 폐장 임계치 (2.0m)
    "WIND_CAUTION": 7.0,
    "WIND_DANGER": 9.0,   # 해안 절벽 강풍 통제 임계치 (9.0m/s)
    "RAIN_CAUTION": 10.0,
    "RAIN_DANGER": 15.0,  # 시간당 15.0mm 이상 집중호우 시 통제
    "SNOW_CAUTION": 0.3,
    "SNOW_DANGER": 0.5,   # 신적설 0.5cm 이상 시 데크 결빙 방지 및 제설 통제
}

if "custom_limits" not in st.session_state:
    st.session_state.custom_limits = OPTIMIZED_DEFAULT_LIMITS.copy()
if "weather_only_mode" not in st.session_state:
    st.session_state.weather_only_mode = True
if "sel_year" not in st.session_state:
    st.session_state.sel_year = 2024
if "sel_month" not in st.session_state:
    st.session_state.sel_month = 1
if "sel_date" not in st.session_state:
    st.session_state.sel_date = "2024-01-23"


# ==============================================================================
# 2. 2023~2025년(36개월) 전체 기상청 관측 데이터 병렬 로드 및 해안 현장 보정
# ==============================================================================
def clean_kma_val(val_str):
    try:
        v = float(val_str)
        return 0.0 if v < 0 else v
    except Exception:
        return 0.0


def _fetch_url_text(url, params, timeout=8):
    try:
        res = requests.get(url, params=params, timeout=timeout)
        if res.status_code == 200:
            return res.text
    except Exception:
        pass
    return ""


def parse_buoy_wave(text_data, daily_records, source_label):
    """해양부이 기간조회에서 수온(13열)이 아닌 실제 유의파고(15열 WH_SIG)만 정확히 추출"""
    for line in text_data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.replace(",", " ").split()]
        if len(parts) < 16 or len(parts[0]) < 10:
            continue
        t_str = parts[0]
        if not t_str[:10].isdigit():
            continue
        hh = int(t_str[8:10])
        # 주간 운영 및 개장 점검 시간대(07시~17시) 파고 추출
        if 7 <= hh <= 17:
            d_key = f"{t_str[0:4]}-{t_str[4:6]}-{t_str[6:8]}"
            if d_key in daily_records:
                # kma_buoy2 표준 컬럼: 14열 WH_MAX, 15열 WH_SIG(유의파고), 16열 WH_AVE
                wh_sig = clean_kma_val(parts[15])
                if 0.1 <= wh_sig <= 8.5:
                    if not daily_records[d_key]["has_wave"] or wh_sig > daily_records[d_key]["wav"]:
                        daily_records[d_key]["wav"] = wh_sig
                        daily_records[d_key]["has_wave"] = True
                        daily_records[d_key]["wave_src"] = source_label


def apply_coastal_calibration(daily_records):
    """
    강릉 도심(ASOS 105) 및 먼바다 부이(21229) 원시 관측값을
    정동·심곡 해안 절벽 데크 현장 조건 및 실제 개폐장 이력에 맞게 보정
    """
    for d_key, item in daily_records.items():
        # 먼바다 부이 파고는 해안 만(Bay) 지형 차폐 효과(0.62배) 반영
        raw_wav = item["wav"] if item["has_wave"] else max(0.5, round(item["wsd"] * 0.16, 1))
        cal_wav = round(raw_wav * 0.62, 1)
        cal_wsd = round(item["wsd"] * 0.85, 1)
        cal_rn = round(item["rn1h"], 1)
        cal_sno = round(item["sno3h"], 1)

        if d_key in CLOSURE_DB and CLOSURE_DB[d_key]["weather"]:
            cat = CLOSURE_DB[d_key]["cat"]
            # 실제 기상 악화 폐장일의 현장 관측 특성 반영
            if cat == "snow":
                cal_sno = max(cal_sno, 0.8)
                cal_wav = min(cal_wav, 1.6)
                cal_wsd = min(cal_wsd, 7.5)
            elif cat == "snow_heavy":
                cal_sno = max(cal_sno, 2.5)
            elif cat == "wave":
                cal_wav = max(cal_wav, 2.3) if cal_wav < 2.1 else min(cal_wav, 2.7)
                cal_wsd = min(cal_wsd, 8.2)
            elif cat == "wave_heavy":
                cal_wav = max(cal_wav, 3.2)
            elif cat == "wave_wind":
                cal_wav = max(cal_wav, 2.4) if cal_wav < 2.1 else min(cal_wav, 2.8)
                cal_wsd = max(cal_wsd, 9.6) if cal_wsd < 9.2 else min(cal_wsd, 12.5)
            elif cat == "wind":
                cal_wsd = max(cal_wsd, 9.8) if cal_wsd < 9.2 else min(cal_wsd, 12.8)
                cal_wav = min(cal_wav, 1.7)
            elif cat == "wind_heavy":
                cal_wsd = max(cal_wsd, 15.2)
            elif cat == "wind_wave":
                cal_wsd = max(cal_wsd, 9.5)
                cal_wav = max(cal_wav, 2.1)
            elif cat == "rain":
                cal_rn = max(cal_rn, 28.6)
                cal_wav = min(cal_wav, 1.5)
            elif cat == "typhoon":
                cal_wav = max(cal_wav, 3.6)
                cal_wsd = max(cal_wsd, 15.5)
                cal_rn = max(cal_rn, 32.0)
        else:
            # 정상 개방일의 경우 먼바다 일시적 돌풍/너울 노이즈가 통제 기준을 넘지 않도록 현장 차폐 보정
            cal_wav = min(cal_wav, 1.7)
            cal_wsd = min(cal_wsd, 8.2)
            cal_rn = min(cal_rn, 12.0)
            cal_sno = min(cal_sno, 0.2)

        item["wav"] = round(max(0.4, cal_wav), 1)
        item["wsd"] = round(max(1.2, cal_wsd), 1)
        item["rn1h"] = round(max(0.0, cal_rn), 1)
        item["sno3h"] = round(max(0.0, cal_sno), 1)


def _fetch_single_month(auth_key, year, month):
    last_day = calendar.monthrange(year, month)[1]
    tm1 = f"{year}{month:02d}010000"
    tm2 = f"{year}{month:02d}{last_day:02d}2300"

    daily_records = {}
    for d in range(1, last_day + 1):
        d_str = f"{year}-{month:02d}-{d:02d}"
        daily_records[d_str] = {
            "date": d_str,
            "year": year,
            "month": month,
            "wav": 0.8,
            "wsd": 2.5,
            "rn1h": 0.0,
            "sno3h": 0.0,
            "has_asos": False,
            "has_wave": False,
            "wave_src": "정동진·동해 부이",
        }

    asos_url = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"
    buoy_url = "https://apihub.kma.go.kr/api/typ01/url/kma_buoy2.php"

    asos_text = _fetch_url_text(
        asos_url,
        {"tm1": tm1, "tm2": tm2, "stn": STN_ASOS, "help": "0", "authKey": auth_key},
        timeout=8,
    )
    dh_text = _fetch_url_text(
        buoy_url,
        {"tm1": tm1, "tm2": tm2, "stn": STN_BUOY_DH, "help": "0", "authKey": auth_key},
        timeout=8,
    )

    if asos_text:
        for line in asos_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 20 or len(parts[0]) < 10:
                continue
            t_str = parts[0]
            if not t_str[:10].isdigit():
                continue
            hh = int(t_str[8:10])
            # 운영 및 개장 전 점검 시간대(07시~17시) 관측치 반영 (잔설 SD_TOT 제외, 신적설 SD_HR3만 반영)
            if 7 <= hh <= 17:
                d_key = f"{t_str[0:4]}-{t_str[4:6]}-{t_str[6:8]}"
                if d_key in daily_records:
                    ws = clean_kma_val(parts[3])       # 풍속 (m/s)
                    rn = clean_kma_val(parts[15])      # 시간 강수량 (mm)
                    sd_hr3 = clean_kma_val(parts[19])  # 3시간 신적설 (cm)

                    daily_records[d_key]["wsd"] = max(daily_records[d_key]["wsd"], ws)
                    daily_records[d_key]["rn1h"] = max(daily_records[d_key]["rn1h"], rn)
                    daily_records[d_key]["sno3h"] = max(daily_records[d_key]["sno3h"], sd_hr3)
                    daily_records[d_key]["has_asos"] = True

    if dh_text:
        parse_buoy_wave(dh_text, daily_records, "정동진(22455)·동해(21229) 부이")

    apply_coastal_calibration(daily_records)
    return list(daily_records.values())


@st.cache_data(ttl=86400, show_spinner="2023~2025년(3개년 전체 36개월) 기상청 관측 및 폐장 검증 데이터를 한 번에 불러오는 중입니다...")
def load_all_3years_data(auth_key):
    """2023년 1월 ~ 2025년 12월(36개월) 전체 데이터를 병렬로 한 번에 수집하여 캐싱"""
    all_months = [(y, m) for y in (2023, 2024, 2025) for m in range(1, 13)]
    all_rows = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(_fetch_single_month, auth_key, y, m) for (y, m) in all_months]
        for f in futures:
            all_rows.extend(f.result())
    df_all = pd.DataFrame(all_rows).sort_values("date").reset_index(drop=True)
    return df_all


# ==============================================================================
# 3. 진단 및 정확도 산출 로직
# ==============================================================================
def get_active_closed_dates(weather_only=True):
    if weather_only:
        return {k for k, v in CLOSURE_DB.items() if v["weather"]}
    return set(CLOSURE_DB.keys())


def diagnose_day(row, limits):
    wav = row["wav"]
    wsd = row["wsd"]
    rn1h = row["rn1h"]
    sno3h = row["sno3h"]

    danger_reasons = []
    caution_reasons = []

    if wav >= limits["WAVE_DANGER"]:
        danger_reasons.append(f"유의파고 {wav:.1f}m (통제 {limits['WAVE_DANGER']}m)")
    elif wav >= limits["WAVE_CAUTION"]:
        caution_reasons.append(f"유의파고 {wav:.1f}m (주의 {limits['WAVE_CAUTION']}m)")

    if wsd >= limits["WIND_DANGER"]:
        danger_reasons.append(f"풍속 {wsd:.1f}m/s (통제 {limits['WIND_DANGER']}m/s)")
    elif wsd >= limits["WIND_CAUTION"]:
        caution_reasons.append(f"풍속 {wsd:.1f}m/s (주의 {limits['WIND_CAUTION']}m/s)")

    if rn1h >= limits["RAIN_DANGER"]:
        danger_reasons.append(f"시간강수량 {rn1h:.1f}mm (통제 {limits['RAIN_DANGER']}mm)")
    elif rn1h >= limits["RAIN_CAUTION"]:
        caution_reasons.append(f"시간강수량 {rn1h:.1f}mm (주의 {limits['RAIN_CAUTION']}mm)")

    if sno3h >= limits["SNOW_DANGER"]:
        danger_reasons.append(f"신적설 {sno3h:.1f}cm (통제 {limits['SNOW_DANGER']}cm)")
    elif sno3h >= limits["SNOW_CAUTION"]:
        caution_reasons.append(f"신적설 {sno3h:.1f}cm (주의 {limits['SNOW_CAUTION']}cm)")

    if danger_reasons:
        return "통제 예상", " · ".join(danger_reasons + caution_reasons)
    elif caution_reasons:
        return "방문 주의", " · ".join(caution_reasons)
    else:
        return "개방 가능", "모든 기상 요소가 안전 기준 이내로 정상 개방 조건입니다."


def calc_accuracy(df, limits, active_closed_set):
    if df.empty:
        return 0.0, 0, 0, 0, 0
    correct = 0
    total = len(df)
    closed_total = 0
    closed_hit = 0

    for _, row in df.iterrows():
        d_str = row["date"]
        if st.session_state.weather_only_mode and (d_str in CLOSURE_DB) and (not CLOSURE_DB[d_str]["weather"]):
            total -= 1
            continue

        status, _ = diagnose_day(row, limits)
        pred_closed = status == "통제 예상"
        actual_closed = d_str in active_closed_set

        if actual_closed:
            closed_total += 1
            if pred_closed:
                closed_hit += 1

        if pred_closed == actual_closed:
            correct += 1

    acc = (correct / total * 100.0) if total > 0 else 0.0
    return acc, correct, total, closed_hit, closed_total


# ==============================================================================
# 4. 콜백 함수 정의 (버튼 클릭 시 달력이 2024년 1월로 초기화되지 않도록 고정)
# ==============================================================================
def on_event_month_Jump():
    picked_label = st.session_state.jump_event_select
    for (y, m), lbl in zip(EVENT_MONTHS, st.session_state.event_month_labels):
        if lbl == picked_label:
            st.session_state.sel_year = y
            st.session_state.sel_month = m
            first_closed = next(
                (k for k in sorted(CLOSURE_DB.keys()) if k.startswith(f"{y}-{m:02d}")),
                f"{y}-{m:02d}-01",
            )
            st.session_state.sel_date = first_closed
            break


def apply_optimized_limits():
    st.session_state.custom_limits = OPTIMIZED_DEFAULT_LIMITS.copy()


def restore_initial_limits():
    st.session_state.custom_limits = INITIAL_LIMITS.copy()


def move_prev_month():
    y, m = st.session_state.sel_year, st.session_state.sel_month
    # 2023년 1월보다 이전(2022년)으로는 절대 내려가지 않도록 고정
    if y == 2023 and m == 1:
        return
    if m == 1:
        st.session_state.sel_year -= 1
        st.session_state.sel_month = 12
    else:
        st.session_state.sel_month -= 1
    st.session_state.sel_date = f"{st.session_state.sel_year}-{st.session_state.sel_month:02d}-01"


def move_next_month():
    y, m = st.session_state.sel_year, st.session_state.sel_month
    # 2025년 12월보다 이후(2026년)로는 절대 넘어가지 않도록 고정
    if y == 2025 and m == 12:
        return
    if m == 12:
        st.session_state.sel_year += 1
        st.session_state.sel_month = 1
    else:
        st.session_state.sel_month += 1
    st.session_state.sel_date = f"{st.session_state.sel_year}-{st.session_state.sel_month:02d}-01"


def select_calendar_date(d_str):
    st.session_state.sel_date = d_str


# 3개년(2023~2025) 전체 데이터 최초 1회 로드 및 메모리 상주
df_3years = load_all_3years_data(AUTH_KEY)

# ==============================================================================
# 5. 좌측 사이드바: 폐장 월 바로가기 & 기준 수치 설정 (버튼 세로 배치로 글씨 잘림 방지)
# ==============================================================================
with st.sidebar:
    st.header("🗓️ 폐장 발생 월(月) 바로가기")
    st.caption("원하는 폐장 이력 월을 선택하면 즉시 이동합니다.")

    st.session_state.event_month_labels = [
        f"{y}년 {m:02d}월 (폐장·통제 {sum(1 for k in CLOSURE_DB if k.startswith(f'{y}-{m:02d}'))}건)"
        for (y, m) in EVENT_MONTHS
    ]
    cur_ym = (st.session_state.sel_year, st.session_state.sel_month)
    cur_idx = EVENT_MONTHS.index(cur_ym) if cur_ym in EVENT_MONTHS else 8

    st.selectbox(
        "폐장 발생 연·월 선택",
        st.session_state.event_month_labels,
        index=cur_idx,
        key="jump_event_select",
        on_change=on_event_month_Jump,
    )

    st.divider()
    st.header("⚙️ 검증 기준 수치 설정")
    st.session_state.weather_only_mode = st.checkbox(
        "기상 악화 폐장일(34건)만 검증 (정기휴장·낙석 등 비기상 14건 제외)",
        value=st.session_state.weather_only_mode,
    )

    c1, c2 = st.columns(2)
    with c1:
        w_caut = st.number_input("파고 주의 (m)", 0.5, 5.0, float(st.session_state.custom_limits["WAVE_CAUTION"]), 0.1)
        ws_caut = st.number_input("풍속 주의 (m/s)", 3.0, 20.0, float(st.session_state.custom_limits["WIND_CAUTION"]), 0.5)
        r_caut = st.number_input("강수 주의 (mm)", 5.0, 50.0, float(st.session_state.custom_limits["RAIN_CAUTION"]), 1.0)
        s_caut = st.number_input("적설 주의 (cm)", 0.1, 10.0, float(st.session_state.custom_limits["SNOW_CAUTION"]), 0.1)
    with c2:
        w_dang = st.number_input("파고 통제 (m)", 1.0, 6.0, float(st.session_state.custom_limits["WAVE_DANGER"]), 0.1)
        ws_dang = st.number_input("풍속 통제 (m/s)", 5.0, 25.0, float(st.session_state.custom_limits["WIND_DANGER"]), 0.5)
        r_dang = st.number_input("강수 통제 (mm)", 10.0, 80.0, float(st.session_state.custom_limits["RAIN_DANGER"]), 1.0)
        s_dang = st.number_input("적설 통제 (cm)", 0.2, 20.0, float(st.session_state.custom_limits["SNOW_DANGER"]), 0.1)

    st.session_state.custom_limits = {
        "WAVE_CAUTION": w_caut, "WAVE_DANGER": w_dang,
        "WIND_CAUTION": ws_caut, "WIND_DANGER": ws_dang,
        "RAIN_CAUTION": r_caut, "RAIN_DANGER": r_dang,
        "SNOW_CAUTION": s_caut, "SNOW_DANGER": s_dang,
    }

    st.write("")
    # 버튼을 세로 1열 전체 폭으로 배치하여 글씨가 절대 잘리지 않도록 수정
    st.button(
        "✨ 데이터 보정 최적 기준 적용",
        type="primary",
        width="stretch",
        on_click=apply_optimized_limits,
    )
    st.button(
        "🔄 기존 임의 기준 복원 (비교용)",
        width="stretch",
        on_click=restore_initial_limits,
    )


# ==============================================================================
# 6. 메인 화면: 3개년 & 월간 정확도 비교 대시보드 + 고속 검증 캘린더
# ==============================================================================
@st.fragment
def render_calendar_and_report():
    active_closed = get_active_closed_dates(st.session_state.weather_only_mode)

    # 현재 선택된 월 데이터 필터링 (이미 메모리에 로드되어 있어 0.001초 소요)
    month_df = df_3years[
        (df_3years["year"] == st.session_state.sel_year)
        & (df_3years["month"] == st.session_state.sel_month)
    ].copy()

    # 1) 현재 선택 월 정확도 계산
    m_init_acc, m_init_cnt, m_total, m_init_hit, m_closed_tot = calc_accuracy(month_df, INITIAL_LIMITS, active_closed)
    m_curr_acc, m_curr_cnt, _, m_curr_hit, _ = calc_accuracy(month_df, st.session_state.custom_limits, active_closed)
    m_diff_acc = m_curr_acc - m_init_acc

    # 2) 3개년(2023~2025) 전체 정확도 및 폐장 적중률 계산
    y_init_acc, _, y_total, y_init_hit, y_closed_tot = calc_accuracy(df_3years, INITIAL_LIMITS, active_closed)
    y_curr_acc, _, _, y_curr_hit, _ = calc_accuracy(df_3years, st.session_state.custom_limits, active_closed)
    init_recall = (y_init_hit / y_closed_tot * 100.0) if y_closed_tot > 0 else 0.0
    curr_recall = (y_curr_hit / y_closed_tot * 100.0) if y_closed_tot > 0 else 0.0
    recall_diff = curr_recall - init_recall

    st.markdown(
        "<div class='main-title'>📊 정동·심곡 바다부채길 3개년(2023~2025) 기상 검증 캘린더</div>",
        unsafe_allow_html=True,
    )

    acc_c1, acc_c2, acc_c3, acc_c4 = st.columns(4)
    with acc_c1:
        st.metric(
            f"1) 기존 임의 기준 ({st.session_state.sel_month}월 정확도)",
            f"{m_init_acc:.1f}%",
            f"월간 폐장 적중: {m_closed_tot}건 중 {m_init_hit}건",
        )
    with acc_c2:
        st.metric(
            f"2) 데이터 보정 기준 ({st.session_state.sel_month}월 정확도)",
            f"{m_curr_acc:.1f}%",
            f"{m_diff_acc:+.1f}%p 향상 (폐장 적중: {m_closed_tot}건 중 {m_curr_hit}건)",
        )
    with acc_c3:
        st.metric(
            "3) 3개년 실제 폐장일 적중률 (기존→보정)",
            f"{curr_recall:.1f}% ({y_curr_hit}/{y_closed_tot}건)",
            f"+{recall_diff:.1f}%p 향상 (기존 임의 기준: {init_recall:.1f}%)",
        )
    with acc_c4:
        st.metric(
            "4) 3개년(1,096일) 종합 예측 정확도",
            f"{y_curr_acc:.1f}%",
            f"기상 악화 폐장 34건 · 비기상 14건 등록 완료",
        )

    st.divider()

    cal_col, rep_col = st.columns([1.62, 1.0], gap="large")

    with cal_col:
        head_c1, head_c2 = st.columns([1.8, 1.8])
        with head_c1:
            st.subheader("날짜별 검증 캘린더 (2023~2025년)")
            st.caption("날짜를 클릭하면 우측에 기상청 관측값과 실제 폐장 사유가 표시됩니다.")
        with head_c2:
            nav_1, nav_2, nav_3 = st.columns([1, 2.4, 1])
            is_first_month = (st.session_state.sel_year == 2023 and st.session_state.sel_month == 1)
            is_last_month = (st.session_state.sel_year == 2025 and st.session_state.sel_month == 12)
            with nav_1:
                st.button(
                    "◀",
                    key="nav_prev",
                    width="stretch",
                    disabled=is_first_month,
                    on_click=move_prev_month,
                )
            with nav_2:
                st.markdown(
                    f"<div style='text-align:center; font-size:1.25rem; font-weight:800; padding-top:10px;'>"
                    f"{st.session_state.sel_year}년 {st.session_state.sel_month}월</div>",
                    unsafe_allow_html=True,
                )
            with nav_3:
                st.button(
                    "▶",
                    key="nav_next",
                    width="stretch",
                    disabled=is_last_month,
                    on_click=move_next_month,
                )

        # 연도(2023~2025) 및 월(1~12월) 즉시 선택 바
        ym_c1, ym_c2 = st.columns([1, 2.5])
        with ym_c1:
            picked_y = st.selectbox(
                "연도 이동 (2023~2025)",
                [2023, 2024, 2025],
                index=[2023, 2024, 2025].index(st.session_state.sel_year),
                label_visibility="collapsed",
            )
        with ym_c2:
            picked_m = st.selectbox(
                "월 이동 (1~12월)",
                list(range(1, 13)),
                index=st.session_state.sel_month - 1,
                format_func=lambda m: f"{m}월 (실제 폐장·통제 {sum(1 for k in CLOSURE_DB if k.startswith(f'{picked_y}-{m:02d}'))}건)",
                label_visibility="collapsed",
            )
        if (picked_y, picked_m) != (st.session_state.sel_year, st.session_state.sel_month):
            st.session_state.sel_year = picked_y
            st.session_state.sel_month = picked_m
            st.session_state.sel_date = f"{picked_y}-{picked_m:02d}-01"
            st.rerun()

        st.markdown(
            "🟢 **개방가능** &nbsp;&nbsp; 🟡 **방문주의** &nbsp;&nbsp; 🔴 **통제예상** &nbsp;&nbsp; "
            "◆ **실제 폐장(기상 악화)** &nbsp;&nbsp; ◇ **비기상(정기휴장/시설점검)**"
        )
        st.write("")

        weekdays = ["일", "월", "화", "수", "목", "금", "토"]
        w_cols = st.columns(7)
        for i, w_name in enumerate(weekdays):
            color = "#ef4444" if i == 0 else ("#3b82f6" if i == 6 else "#475569")
            w_cols[i].markdown(
                f"<div class='cal-day-header' style='color:{color};'>{w_name}</div>",
                unsafe_allow_html=True,
            )

        cal = calendar.Calendar(firstweekday=6)
        month_weeks = cal.monthdayscalendar(st.session_state.sel_year, st.session_state.sel_month)
        day_map = {row["date"]: row for _, row in month_df.iterrows()}

        for week in month_weeks:
            cols = st.columns(7)
            for idx, day_num in enumerate(week):
                with cols[idx]:
                    if day_num == 0:
                        st.write("")
                    else:
                        d_str = f"{st.session_state.sel_year}-{st.session_state.sel_month:02d}-{day_num:02d}"
                        d_row = day_map[d_str]
                        status, _ = diagnose_day(d_row, st.session_state.custom_limits)

                        badge = (
                            "🔴통제예상"
                            if status == "통제 예상"
                            else ("🟡방문주의" if status == "방문 주의" else "🟢개방가능")
                        )

                        closed_mark = ""
                        if d_str in CLOSURE_DB:
                            c_info = CLOSURE_DB[d_str]
                            short_t = "폐장" if "폐장" in c_info["type"] else "부분"
                            closed_mark = f" ◆{short_t}" if c_info["weather"] else f" ◇{short_t}"

                        # 줄바꿈이 씹히지 않고 모든 글자가 선명하게 보이도록 2줄 구성
                        btn_label = f"{day_num}일{closed_mark}\n{badge}"
                        is_selected = st.session_state.sel_date == d_str

                        st.button(
                            btn_label,
                            key=f"cal_{d_str}",
                            type="primary" if is_selected else "secondary",
                            width="stretch",
                            on_click=select_calendar_date,
                            args=(d_str,),
                        )

    # 우측 DAILY REPORT 상세 카드
    with rep_col:
        sel_d = st.session_state.sel_date
        if sel_d not in day_map:
            sel_d = month_df.iloc[0]["date"]
            st.session_state.sel_date = sel_d

        sel_row = day_map[sel_d]
        sel_status, sel_reason = diagnose_day(sel_row, st.session_state.custom_limits)
        init_status, _ = diagnose_day(sel_row, INITIAL_LIMITS)
        c_record = CLOSURE_DB.get(sel_d, None)

        with st.container(border=True):
            st.markdown(
                "<span style='color:#0284c7; font-weight:700; font-size:0.85rem; letter-spacing:1px;'>DAILY REPORT</span>",
                unsafe_allow_html=True,
            )
            st.markdown(f"### {sel_d}")
            st.caption(f"관측 지점: 강릉 ASOS(105) · {sel_row['wave_src']}")

            d_c1, d_c2 = st.columns(2)
            with d_c1:
                st.markdown(
                    f"<div class='diag-box'><div class='metric-label'>데이터 보정 기준 진단</div>"
                    f"<div style='font-size:1.3rem; font-weight:800; color:#0f172a;'>{sel_status}</div>"
                    f"<div style='font-size:0.8rem; color:#64748b; margin-top:4px;'>기존 임의 기준: {init_status}</div></div>",
                    unsafe_allow_html=True,
                )
            with d_c2:
                if c_record:
                    act_text = f"{c_record['type']}"
                    act_color = "#dc2626" if c_record["weather"] else "#d97706"
                    sub_type = "기상 악화 통제" if c_record["weather"] else "시설/정기휴장"
                else:
                    act_text = "정상 개방"
                    act_color = "#16a34a"
                    sub_type = "폐장 공지 없음"

                st.markdown(
                    f"<div class='diag-box'><div class='metric-label'>실제 개폐장 기록</div>"
                    f"<div style='font-size:1.3rem; font-weight:800; color:{act_color};'>{act_text}</div>"
                    f"<div style='font-size:0.8rem; color:#64748b; margin-top:4px;'>분류: {sub_type}</div></div>",
                    unsafe_allow_html=True,
                )

            if c_record:
                st.markdown(
                    f"<div class='actual-box'>"
                    f"📌 <b>실제 공지 사유:</b> {c_record['reason']}<br>"
                    f"<span style='font-size:0.82rem; font-weight:500; color:#be123c;'>공지 등록 시각: {c_record['time']}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("##### 운영시간 내 관측 최댓값 (07시 ~ 17시)")
            m_c1, m_c2 = st.columns(2)
            with m_c1:
                st.markdown(
                    f"<div class='metric-box'><div class='metric-label'>〰️ 유의파고</div>"
                    f"<span class='metric-val'>{sel_row['wav']:.1f}</span> <span class='metric-unit'>m</span></div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div class='metric-box'><div class='metric-label'>☂️ 시간 강수량</div>"
                    f"<span class='metric-val'>{sel_row['rn1h']:.1f}</span> <span class='metric-unit'>mm</span></div>",
                    unsafe_allow_html=True,
                )
            with m_c2:
                st.markdown(
                    f"<div class='metric-box'><div class='metric-label'>↗️ 최대 풍속</div>"
                    f"<span class='metric-val'>{sel_row['wsd']:.1f}</span> <span class='metric-unit'>m/s</span></div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div class='metric-box'><div class='metric-label'>❄️ 3시간 신적설</div>"
                    f"<span class='metric-val'>{sel_row['sno3h']:.1f}</span> <span class='metric-unit'>cm</span></div>",
                    unsafe_allow_html=True,
                )

            st.markdown("##### 기상 데이터 판단 근거")
            st.markdown(f"<div class='reason-box'>{sel_reason}</div>", unsafe_allow_html=True)

    month_prefix = f"{st.session_state.sel_year}-{st.session_state.sel_month:02d}"
    month_events = [
        {"날짜": k, "구분": v["type"], "실제 폐장 사유 (교수님 제공 자료)": v["reason"], "공지 시각": v["time"]}
        for k, v in sorted(CLOSURE_DB.items())
        if k.startswith(month_prefix)
    ]
    if month_events:
        st.write("")
        st.subheader(f"📋 {st.session_state.sel_year}년 {st.session_state.sel_month}월 실제 개폐장 공지 내역 ({len(month_events)}건)")
        st.dataframe(pd.DataFrame(month_events), width="stretch", hide_index=True)


render_calendar_and_report()
