import calendar
import datetime
import pandas as pd
import requests
import streamlit as st

# ==============================================================================
# 0. 페이지 기본 설정 및 캘린더 카드형 UI 스타일
# ==============================================================================
st.set_page_config(
    page_title="바다부채길 3개년 기상 검증 캘린더 & 기준 최적화",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.html("""
<style>
.block-container { padding-top: 1.8rem !important; max-width: 1400px !important; }

.cal-day-header {
    text-align: center;
    font-weight: 700;
    padding: 8px 0;
    border-bottom: 1px solid #e2e8f0;
    margin-bottom: 8px;
    font-size: 0.95rem;
}

.metric-box {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 16px 18px;
    margin-bottom: 12px;
}
.metric-label {
    color: #64748b;
    font-size: 0.88rem;
    font-weight: 600;
    margin-bottom: 6px;
}
.metric-val {
    color: #0f172a;
    font-size: 1.65rem;
    font-weight: 800;
}
.metric-unit {
    color: #64748b;
    font-size: 1.0rem;
    font-weight: 500;
}

.diag-box {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 14px;
}
.reason-box {
    background-color: #f8fafc;
    border-radius: 12px;
    padding: 14px 16px;
    color: #334155;
    font-size: 0.95rem;
    font-weight: 500;
    border: 1px solid #e2e8f0;
}

div[data-testid="stVerticalBlock"] button[kind="secondary"],
div[data-testid="stVerticalBlock"] button[kind="primary"] {
    height: 92px !important;
    white-space: pre-line !important;
    line-height: 1.45 !important;
    font-weight: 600 !important;
    border-radius: 12px !important;
}
</style>
""")

# ==============================================================================
# 1. 기상청 API 설정 (강릉 육상 105 + 정동진 연안부이 22455 + 동해 부이 21229)
# ==============================================================================
AUTH_KEY = "aIYY8TrRRe-GGPE60QXvsA"
STN_ASOS = "105"          # 강릉 종관기상관측소 (풍속, 시간강수량, 3시간신적설)
STN_WAVE_JD = "22455"     # 정동진 연안파고부이 (1순위 파고 관측소)
STN_BUOY_DH = "21229"     # 동해 해양기상부이 (2순위 보조 파고 관측소)

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

if "custom_limits" not in st.session_state:
    st.session_state.custom_limits = INITIAL_LIMITS.copy()

if "closed_dates" not in st.session_state:
    st.session_state.closed_dates = {
        "2023-07-09", "2023-08-10", "2023-08-11", "2023-12-11", "2023-12-12"
    }

if "sel_year" not in st.session_state:
    st.session_state.sel_year = 2023
if "sel_month" not in st.session_state:
    st.session_state.sel_month = 7
if "sel_date" not in st.session_state:
    st.session_state.sel_date = "2023-07-09"


# ==============================================================================
# 2. 기상청 과거 관측 데이터 수집 함수 (결측값 -9.0 제거 및 2중 파고 보완)
# ==============================================================================
def clean_kma_val(val_str):
    """기상청 API의 결측값(-9, -9.0, -99 등)을 0.0으로 안전하게 변환"""
    try:
        v = float(val_str)
        return 0.0 if v < 0 else v
    except Exception:
        return 0.0


def parse_buoy_response(text_data, daily_records, source_label):
    """부이 기간조회 응답 텍스트에서 06~18시 유의파고 최댓값을 추출"""
    for line in text_data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.replace(",", " ").split()]
        if len(parts) < 6 or len(parts[0]) < 10:
            continue
        t_str = parts[0]
        if not t_str[:10].isdigit():
            continue
        hh = int(t_str[8:10])
        if 6 <= hh <= 18:
            d_key = f"{t_str[0:4]}-{t_str[4:6]}-{t_str[6:8]}"
            if d_key in daily_records:
                # kma_buoy2(13번째 열) 또는 파고부이(유의파고 열) 자동 판별
                wh_sig = 0.0
                if len(parts) >= 14:
                    wh_sig = clean_kma_val(parts[13])
                if wh_sig == 0.0 and len(parts) >= 7:
                    wh_sig = clean_kma_val(parts[6])

                if wh_sig > 0:
                    if not daily_records[d_key]["has_wave"]:
                        daily_records[d_key]["wav"] = wh_sig
                        daily_records[d_key]["has_wave"] = True
                        daily_records[d_key]["wave_src"] = source_label
                    else:
                        if wh_sig > daily_records[d_key]["wav"]:
                            daily_records[d_key]["wav"] = wh_sig
                            daily_records[d_key]["wave_src"] = source_label


@st.cache_data(ttl=86400, show_spinner="기상청 관측 데이터(강릉 ASOS + 정동진·동해 부이)를 불러오는 중입니다...")
def fetch_monthly_kma_obs(auth_key, year, month):
    last_day = calendar.monthrange(year, month)[1]
    tm1 = f"{year}{month:02d}010000"
    tm2 = f"{year}{month:02d}{last_day:02d}2300"

    daily_records = {}
    for d in range(1, last_day + 1):
        d_str = f"{year}-{month:02d}-{d:02d}"
        daily_records[d_str] = {
            "date": d_str,
            "wav": 0.6,
            "wsd": 0.0,
            "rn1h": 0.0,
            "sno3h": 0.0,
            "has_asos": False,
            "has_wave": False,
            "wave_src": "정동진·동해 부이",
        }

    # 1) 강릉 종관기상관측(ASOS 105) 시간자료 (기간 조회: kma_sfctm3.php)
    asos_url = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"
    try:
        res_asos = requests.get(
            asos_url,
            params={"tm1": tm1, "tm2": tm2, "stn": STN_ASOS, "help": "0", "authKey": auth_key},
            timeout=12,
        )
        if res_asos.status_code == 200:
            for line in res_asos.text.splitlines():
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
                if 6 <= hh <= 18:
                    d_key = f"{t_str[0:4]}-{t_str[4:6]}-{t_str[6:8]}"
                    if d_key in daily_records:
                        ws = clean_kma_val(parts[3])      # 풍속 (m/s)
                        rn = clean_kma_val(parts[15])     # 시간 강수량 (mm)
                        sno = clean_kma_val(parts[19])    # 3시간 신적설 (cm)
                        daily_records[d_key]["wsd"] = max(daily_records[d_key]["wsd"], ws)
                        daily_records[d_key]["rn1h"] = max(daily_records[d_key]["rn1h"], rn)
                        daily_records[d_key]["sno3h"] = max(daily_records[d_key]["sno3h"], sno)
                        daily_records[d_key]["has_asos"] = True
    except Exception:
        pass

    # 2) 1순위: 정동진 연안파고부이(22455) 조회
    buoy_url = "https://apihub.kma.go.kr/api/typ01/url/kma_buoy2.php"
    try:
        res_jd = requests.get(
            buoy_url,
            params={"tm1": tm1, "tm2": tm2, "stn": STN_WAVE_JD, "help": "0", "authKey": auth_key},
            timeout=10,
        )
        if res_jd.status_code == 200:
            parse_buoy_response(res_jd.text, daily_records, "정동진 연안부이(22455)")
    except Exception:
        pass

    # 3) 2순위: 정동진 부이 결측일을 위해 동해 해양기상부이(21229) 보완 조회
    try:
        res_dh = requests.get(
            buoy_url,
            params={"tm1": tm1, "tm2": tm2, "stn": STN_BUOY_DH, "help": "0", "authKey": auth_key},
            timeout=12,
        )
        if res_dh.status_code == 200:
            parse_buoy_response(res_dh.text, daily_records, "동해 해양부이(21229)")
    except Exception:
        pass

    # 4) 해상 부이 장비 점검일 발생 시 풍속 기반 해안 파고 보정 (자료 부족 원천 방지)
    for d_key, item in daily_records.items():
        if not item["has_wave"]:
            est_wav = round(max(0.5, item["wsd"] * 0.18 + (0.4 if item["rn1h"] >= 10 else 0.0)), 1)
            item["wav"] = est_wav
            item["wave_src"] = "강릉 해안풍속 기반 산출"

    return pd.DataFrame(list(daily_records.values()))


# ==============================================================================
# 3. 기준 수치에 따른 개폐장 진단 및 판단 근거 생성 함수
# ==============================================================================
def diagnose_day(row, limits):
    wav = row["wav"]
    wsd = row["wsd"]
    rn1h = row["rn1h"]
    sno3h = row["sno3h"]

    danger_reasons = []
    caution_reasons = []

    if wav >= limits["WAVE_DANGER"]:
        danger_reasons.append(f"유의파고 {wav:.1f}m (통제 기준 {limits['WAVE_DANGER']}m)")
    elif wav >= limits["WAVE_CAUTION"]:
        caution_reasons.append(f"유의파고 {wav:.1f}m (주의 기준 {limits['WAVE_CAUTION']}m)")

    if wsd >= limits["WIND_DANGER"]:
        danger_reasons.append(f"풍속 {wsd:.1f}m/s (통제 기준 {limits['WIND_DANGER']}m/s)")
    elif wsd >= limits["WIND_CAUTION"]:
        caution_reasons.append(f"풍속 {wsd:.1f}m/s (주의 기준 {limits['WIND_CAUTION']}m/s)")

    if rn1h >= limits["RAIN_DANGER"]:
        danger_reasons.append(f"시간강수량 {rn1h:.1f}mm (통제 기준 {limits['RAIN_DANGER']}mm)")
    elif rn1h >= limits["RAIN_CAUTION"]:
        caution_reasons.append(f"시간강수량 {rn1h:.1f}mm (주의 기준 {limits['RAIN_CAUTION']}mm)")

    if sno3h >= limits["SNOW_DANGER"]:
        danger_reasons.append(f"3시간 신적설 {sno3h:.1f}cm (통제 기준 {limits['SNOW_DANGER']}cm)")
    elif sno3h >= limits["SNOW_CAUTION"]:
        caution_reasons.append(f"3시간 신적설 {sno3h:.1f}cm (주의 기준 {limits['SNOW_CAUTION']}cm)")

    if danger_reasons:
        return "통제 예상", " · ".join(danger_reasons + caution_reasons)
    elif caution_reasons:
        return "방문 주의", " · ".join(caution_reasons)
    else:
        return "개방 가능", "모든 기상 요소가 안전 기준 이내로 정상 개방 조건입니다."


def calc_accuracy(df, limits, closed_set):
    if df.empty:
        return 0.0, 0, 0
    correct = 0
    total = len(df)
    for _, row in df.iterrows():
        status, _ = diagnose_day(row, limits)
        pred_closed = status == "통제 예상"
        actual_closed = row["date"] in closed_set
        if pred_closed == actual_closed:
            correct += 1
    return (correct / total) * 100.0, correct, total


# ==============================================================================
# 4. 좌측 사이드바: 기준 수치 조절 및 교수님 폐장 데이터 입력창
# ==============================================================================
with st.sidebar:
    st.header("⚙️ 검증 기준 수치 설정")
    st.caption("수치를 조절하면 달력과 상단 예측 정확도가 실시간으로 변합니다.")

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
        s_dang = st.number_input("적설 통제 (cm)", 0.5, 20.0, float(st.session_state.custom_limits["SNOW_DANGER"]), 0.5)

    st.session_state.custom_limits = {
        "WAVE_CAUTION": w_caut, "WAVE_DANGER": w_dang,
        "WIND_CAUTION": ws_caut, "WIND_DANGER": ws_dang,
        "RAIN_CAUTION": r_caut, "RAIN_DANGER": r_dang,
        "SNOW_CAUTION": s_caut, "SNOW_DANGER": s_dang,
    }

    st.divider()
    st.subheader("📋 실제 폐장일 목록 입력")
    st.caption("교수님께 받은 폐장 날짜(YYYY-MM-DD)를 줄바꿈이나 쉼표로 붙여넣으세요.")
    closed_text = st.text_area(
        "폐장 날짜 목록",
        value="\n".join(sorted(st.session_state.closed_dates)),
        height=130,
    )
    parsed_dates = {
        token.strip()
        for token in closed_text.replace(",", "\n").splitlines()
        if len(token.strip()) == 10
    }
    st.session_state.closed_dates = parsed_dates


# ==============================================================================
# 5. 월별 데이터 로드 및 정확도 자동 최적화
# ==============================================================================
month_df = fetch_monthly_kma_obs(AUTH_KEY, st.session_state.sel_year, st.session_state.sel_month)

with st.sidebar:
    if st.button("✨ 현재 월 최적 수치 자동 찾기", type="primary", width="stretch"):
        best_acc = -1.0
        best_lim = st.session_state.custom_limits.copy()
        for wd in [1.8, 2.0, 2.2, 2.5, 2.8, 3.0]:
            for wsd in [10.0, 11.0, 12.0, 13.0, 14.0]:
                for rnd in [15.0, 20.0, 25.0, 30.0]:
                    cand = {
                        "WAVE_CAUTION": round(wd - 0.5, 1),
                        "WAVE_DANGER": wd,
                        "WIND_CAUTION": round(wsd - 3.0, 1),
                        "WIND_DANGER": wsd,
                        "RAIN_CAUTION": round(rnd - 5.0, 1),
                        "RAIN_DANGER": rnd,
                        "SNOW_CAUTION": 0.5,
                        "SNOW_DANGER": 1.5,
                    }
                    acc, _, _ = calc_accuracy(month_df, cand, st.session_state.closed_dates)
                    if acc > best_acc:
                        best_acc = acc
                        best_lim = cand
        st.session_state.custom_limits = best_lim
        st.rerun()

init_acc, init_cnt, total_days = calc_accuracy(month_df, INITIAL_LIMITS, st.session_state.closed_dates)
curr_acc, curr_cnt, _ = calc_accuracy(month_df, st.session_state.custom_limits, st.session_state.closed_dates)
diff_acc = curr_acc - init_acc

st.title("📊 정동·심곡 바다부채길 과거 기상 검증 캘린더")
acc_c1, acc_c2, acc_c3 = st.columns(3)
with acc_c1:
    st.metric("1) 기존 임의 기준 정확도", f"{init_acc:.1f}%", f"{total_days}일 중 {init_cnt}일 일치")
with acc_c2:
    st.metric(
        "2) 데이터 기반 수정 기준 정확도",
        f"{curr_acc:.1f}%",
        f"{diff_acc:+.1f}%p 정확도 향상 ({curr_cnt}일 일치)",
    )
with acc_c3:
    st.metric("3) 현재 월 등록된 실제 폐장일", f"{sum(d in st.session_state.closed_dates for d in month_df['date'])}일", "좌측 메뉴에서 추가/수정 가능")

st.divider()

# ==============================================================================
# 6. 메인 레이아웃: 좌측 날짜별 검증 캘린더 + 우측 DAILY REPORT 카드
# ==============================================================================
cal_col, rep_col = st.columns([1.65, 1.0], gap="large")

with cal_col:
    head_c1, head_c2 = st.columns([2.2, 1.5])
    with head_c1:
        st.subheader("날짜별 검증 캘린더")
        st.caption("날짜를 선택하면 그날의 관측자료와 진단 근거를 표시합니다.")
    with head_c2:
        nav_1, nav_2, nav_3 = st.columns([1, 2.2, 1])
        with nav_1:
            if st.button("◀", width="stretch"):
                if st.session_state.sel_month == 1:
                    st.session_state.sel_year -= 1
                    st.session_state.sel_month = 12
                else:
                    st.session_state.sel_month -= 1
                st.session_state.sel_date = f"{st.session_state.sel_year}-{st.session_state.sel_month:02d}-01"
                st.rerun()
        with nav_2:
            st.markdown(
                f"<div style='text-align:center; font-size:1.25rem; font-weight:800; padding-top:6px;'>"
                f"{st.session_state.sel_year}년 {st.session_state.sel_month}월</div>",
                unsafe_allow_html=True,
            )
        with nav_3:
            if st.button("▶", width="stretch"):
                if st.session_state.sel_month == 12:
                    st.session_state.sel_year += 1
                    st.session_state.sel_month = 1
                else:
                    st.session_state.sel_month += 1
                st.session_state.sel_date = f"{st.session_state.sel_year}-{st.session_state.sel_month:02d}-01"
                st.rerun()

    st.markdown(
        "🟢 **개방 가능** &nbsp;&nbsp; 🟡 **방문 주의** &nbsp;&nbsp; 🔴 **통제 예상** &nbsp;&nbsp; ◆ **실제 폐장**"
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
                    is_closed = d_str in st.session_state.closed_dates

                    badge = "🔴 통제 예상" if status == "통제 예상" else ("🟡 방문 주의" if status == "방문 주의" else "🟢 개방 가능")
                    closed_mark = " ◆폐장" if is_closed else ""
                    btn_label = f"{day_num}{closed_mark}\n\n{badge}"

                    is_selected = (st.session_state.sel_date == d_str)
                    if st.button(
                        btn_label,
                        key=f"cal_{d_str}",
                        type="primary" if is_selected else "secondary",
                        width="stretch",
                    ):
                        st.session_state.sel_date = d_str
                        st.rerun()

# ==============================================================================
# 7. 우측 패널: 선택한 날짜의 DAILY REPORT 상세 카드
# ==============================================================================
with rep_col:
    sel_d = st.session_state.sel_date
    if sel_d not in day_map:
        sel_d = month_df.iloc[0]["date"]
        st.session_state.sel_date = sel_d

    sel_row = day_map[sel_d]
    sel_status, sel_reason = diagnose_day(sel_row, st.session_state.custom_limits)
    actual_closed = sel_d in st.session_state.closed_dates

    with st.container(border=True):
        st.markdown("<span style='color:#0284c7; font-weight:700; font-size:0.85rem; letter-spacing:1px;'>DAILY REPORT</span>", unsafe_allow_html=True)
        st.markdown(f"### {sel_d}")
        st.caption(f"관측 지점: 강릉 ASOS(105) · {sel_row['wave_src']}")

        toggle_closed = st.checkbox("◆ 이 날짜를 '실제 폐장일'로 지정", value=actual_closed, key=f"chk_{sel_d}")
        if toggle_closed != actual_closed:
            if toggle_closed:
                st.session_state.closed_dates.add(sel_d)
            else:
                st.session_state.closed_dates.discard(sel_d)
            st.rerun()

        st.divider()

        d_c1, d_c2 = st.columns(2)
        with d_c1:
            st.markdown(
                f"<div class='diag-box'><div class='metric-label'>자체 기준 진단</div>"
                f"<div style='font-size:1.35rem; font-weight:800; color:#0f172a;'>{sel_status}</div></div>",
                unsafe_allow_html=True,
            )
        with d_c2:
            act_text = "실제 폐장" if actual_closed else "정상 개방"
            act_color = "#dc2626" if actual_closed else "#16a34a"
            st.markdown(
                f"<div class='diag-box'><div class='metric-label'>실제 개폐장</div>"
                f"<div style='font-size:1.35rem; font-weight:800; color:{act_color};'>{act_text}</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown("##### 운영시간 내 관측 최댓값 (06시 ~ 18시)")
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
                f"<div class='metric-box'><div class='metric-label'>↗️ 풍속</div>"
                f"<span class='metric-val'>{sel_row['wsd']:.1f}</span> <span class='metric-unit'>m/s</span></div>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='metric-box'><div class='metric-label'>❄️ 3시간 신적설</div>"
                f"<span class='metric-val'>{sel_row['sno3h']:.1f}</span> <span class='metric-unit'>cm</span></div>",
                unsafe_allow_html=True,
            )

        st.markdown("##### 판단 근거")
        st.markdown(f"<div class='reason-box'>{sel_reason}</div>", unsafe_allow_html=True)
