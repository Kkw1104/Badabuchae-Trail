import datetime
import re
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ==============================================================================
# 0. 한국 표준시(KST, UTC+9) 설정
# ==============================================================================
KST = datetime.timezone(datetime.timedelta(hours=9))


def get_now_kst():
  """해외 클라우드 서버 환경에서도 정확한 한국 표준시(KST)를 반환"""
  return datetime.datetime.now(KST)


# ==============================================================================
# 1. 페이지 기본 환경설정 및 모바일·PC 표 가운데 정렬 스타일
# ==============================================================================
st.set_page_config(
    page_title="정동·심곡 바다부채길 기상 및 탐방 안내",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# PC 및 모바일 표 가운데 정렬·줄바꿈 방지 CSS 적용
st.html("""
<style>
div[data-testid="stMarkdownContainer"] table {
    width: 100% !important;
    border-collapse: collapse !important;
    margin: 0 auto !important;
}
div[data-testid="stMarkdownContainer"] th,
div[data-testid="stMarkdownContainer"] td {
    text-align: center !important;
    vertical-align: middle !important;
    white-space: nowrap !important;
    word-break: keep-all !important;
    padding: 10px 6px !important;
    font-size: 0.95rem !important;
    border: 1px solid #cbd5e1 !important;
}
div[data-testid="stMarkdownContainer"] th {
    background-color: #f1f5f9 !important;
    color: #0f172a !important;
    font-weight: 700 !important;
    border-bottom: 2px solid #94a3b8 !important;
}
div[data-testid="stMarkdownContainer"] tr:nth-child(even) td {
    background-color: #f8fafc !important;
}
@media (max-width: 640px) {
    div[data-testid="stMarkdownContainer"] th,
    div[data-testid="stMarkdownContainer"] td {
        padding: 8px 4px !important;
        font-size: 0.85rem !important;
    }
}
</style>
""")

# ==============================================================================
# 2. 기상청 API 설정 및 해안 탐방로 안전 관리 기준
# ==============================================================================
AUTH_KEY = "aIYY8TrRRe-GGPE60QXvsA"
GRID_NX = "96"
GRID_NY = "131"

LIMITS = {
    "WIND_CAUTION": 10.0,  # 풍속 주의 기준 (m/s)
    "WIND_DANGER": 14.0,  # 풍속 통제 기준 (m/s)
    "WAVE_CAUTION": 1.8,  # 파고 주의 기준 (m)
    "WAVE_DANGER": 3.0,  # 파고 통제 기준 (m)
    "RAIN_1H_CAUTION": 15.0,  # 1시간 강수 주의 기준 (mm)
    "RAIN_3H_DANGER": 60.0,  # 3시간 누적강수 통제 기준 (mm)
    "SNOW_CAUTION": 0.5,  # 적설 주의 기준 (cm)
}


# ==============================================================================
# 3. 기상청 단기예보 데이터 수집 및 전처리 (당일/내일/모레 24시간 확보)
# ==============================================================================
def get_latest_base_datetime():
  now = get_now_kst()
  fcst_times = [2, 5, 8, 11, 14, 17, 20, 23]
  cur_hour, cur_min = now.hour, now.minute
  target_date = now.strftime("%Y%m%d")
  target_time = None

  for t in reversed(fcst_times):
    if cur_hour > t or (cur_hour == t and cur_min >= 15):
      target_time = f"{t:02d}00"
      break

  if target_time is None:
    yesterday = now - datetime.timedelta(days=1)
    target_date = yesterday.strftime("%Y%m%d")
    target_time = "2300"
  return target_date, target_time


def clean_numeric_val(val):
  if pd.isna(val) or val in ["강수없음", "적설없음"]:
    return 0.0
  val_str = str(val).strip()
  if "미만" in val_str:
    return 0.5
  m = re.search(r"(\d+(\.\d+)?)", val_str)
  return float(m.group(1)) if m else 0.0


def request_kma_items(auth_key, b_date, b_time):
  url = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
  params = {
      "pageNo": "1",
      "numOfRows": "1000",
      "dataType": "JSON",
      "base_date": b_date,
      "base_time": b_time,
      "nx": GRID_NX,
      "ny": GRID_NY,
      "authKey": auth_key,
  }
  res = requests.get(url, params=params, timeout=10).json()
  return res["response"]["body"]["items"]["item"]


@st.cache_data(ttl=1800)
def fetch_forecast_data(auth_key, base_date, base_time):
  now_kst = get_now_kst()
  yesterday_str = (now_kst - datetime.timedelta(days=1)).strftime("%Y%m%d")

  # 당일 00시~23시 전체 24시간 그래프를 위해 전일 23시 예보와 최신 예보를 병합
  all_items = []
  if not (base_date == yesterday_str and base_time == "2300"):
    try:
      early_items = request_kma_items(auth_key, yesterday_str, "2300")
      all_items.extend(early_items)
    except Exception:
      pass

  latest_items = request_kma_items(auth_key, base_date, base_time)
  all_items.extend(latest_items)

  df = pd.DataFrame(all_items)
  df = df.drop_duplicates(
      subset=["fcstDate", "fcstTime", "category"], keep="last"
  )

  pivot_df = df.pivot(
      index=["fcstDate", "fcstTime"], columns="category", values="fcstValue"
  ).reset_index()

  for col in ["WAV", "WSD", "VEC", "TMP", "POP"]:
    if col in pivot_df.columns:
      pivot_df[col] = pd.to_numeric(pivot_df[col], errors="coerce")

  pivot_df["PCP_NUM"] = (
      pivot_df["PCP"].apply(clean_numeric_val)
      if "PCP" in pivot_df.columns
      else 0.0
  )
  pivot_df["SNO_NUM"] = (
      pivot_df["SNO"].apply(clean_numeric_val)
      if "SNO" in pivot_df.columns
      else 0.0
  )

  pivot_df["DATETIME"] = pd.to_datetime(
      pivot_df["fcstDate"] + pivot_df["fcstTime"], format="%Y%m%d%H%M"
  )
  pivot_df = pivot_df.sort_values("DATETIME").reset_index(drop=True)
  pivot_df["PCP_3H"] = (
      pivot_df["PCP_NUM"].rolling(window=3, min_periods=1).sum()
  )

  weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
  # 1) 마우스 오버/터치 툴팁용 전체 일시 표기
  pivot_df["KR_TIME"] = pivot_df["DATETIME"].apply(
      lambda d: f"{d.month}/{d.day}({weekday_kr[d.weekday()]}) {d.hour:02d}시"
  )
  # 2) 그래프 X축 및 하단 상세표 전용 깔끔한 시간 표기 (예: 00시, 03시...)
  pivot_df["HOUR_ONLY"] = pivot_df["DATETIME"].apply(lambda d: f"{d.hour:02d}시")

  return pivot_df


# ==============================================================================
# 4. 금일 오전/오후 개방 전망 및 추천 탐방 시간대 산출
# ==============================================================================
def evaluate_today_risk(df):
  now_kst = get_now_kst()
  today_str = now_kst.strftime("%Y%m%d")
  today_df = df[df["fcstDate"] == today_str].copy()
  if today_df.empty:
    today_df = df.head(24).copy()

  # [오전 개장 전 점검 시간대: 06~08시]
  pre_data = today_df[today_df["fcstTime"].isin(["0600", "0700", "0800"])]
  if pre_data.empty:
    pre_data = today_df.head(3)

  pre_wsd = pre_data["WSD"].max() if "WSD" in pre_data else 3.0
  pre_wav = pre_data["WAV"].max() if "WAV" in pre_data else 0.5
  pre_pcp_1h = pre_data["PCP_NUM"].max() if "PCP_NUM" in pre_data else 0.0
  pre_pcp_3h = pre_data["PCP_3H"].max() if "PCP_3H" in pre_data else 0.0
  pre_snow = (
      pre_data["PTY"].astype(str).isin(["2", "3"]).any()
      if "PTY" in pre_data
      else False
  )

  if (
      pre_wsd >= LIMITS["WIND_DANGER"]
      or pre_wav >= LIMITS["WAVE_DANGER"]
      or pre_pcp_3h >= LIMITS["RAIN_3H_DANGER"]
  ):
    m_level = "danger"
    m_stat = "출입 통제 예상 (정시 개방 어려움)"
    m_desc = f"오전 높은 파도({pre_wav:.1f}m) 또는 강한 바람({pre_wsd:.1f}m/s)으로 인해 안전상 통제될 가능성이 높습니다."
  elif pre_snow:
    m_level = "caution"
    m_stat = "방문 주의 (개장 지연 가능성)"
    m_desc = "아침 눈 예보로 인해 탐방로 데크 제설 및 안전 점검 후 늦게 개방될 수 있습니다."
  elif (
      pre_wsd >= LIMITS["WIND_CAUTION"]
      or pre_wav >= LIMITS["WAVE_CAUTION"]
      or pre_pcp_1h >= LIMITS["RAIN_1H_CAUTION"]
  ):
    m_level = "caution"
    m_stat = "방문 주의 (현장 확인 필요)"
    m_desc = f"오전 파도({pre_wav:.1f}m)와 바람({pre_wsd:.1f}m/s)이 다소 강하여 현장 안전 점검 결과에 따라 변동될 수 있습니다."
  else:
    m_level = "safe"
    m_stat = "정상 개방 예상 (09:00 정시 오픈)"
    m_desc = f"오전 파도 높이 {pre_wav:.1f}m, 바람 세기 {pre_wsd:.1f}m/s로 기상이 양호하여 정상 개방이 예상됩니다."

  # [주간 운영 시간대: 09~16시]
  open_data = today_df[
      today_df["fcstTime"].isin(
          ["0900", "1000", "1100", "1200", "1300", "1400", "1500", "1600"]
      )
  ]
  if open_data.empty:
    open_data = today_df

  open_wsd = open_data["WSD"].max() if "WSD" in open_data else 3.0
  open_wav = open_data["WAV"].max() if "WAV" in open_data else 0.5
  open_pcp_1h = open_data["PCP_NUM"].max() if "PCP_NUM" in open_data else 0.0
  open_pcp_3h = open_data["PCP_3H"].max() if "PCP_3H" in open_data else 0.0
  open_snow = (
      open_data["PTY"].astype(str).isin(["2", "3"]).any()
      if "PTY" in open_data
      else False
  )

  if open_snow:
    a_level = "danger"
    a_stat = "출입 통제 예상 (중간 통제 가능)"
    a_desc = "일중 눈 예보로 인해 미끄럼 사고 방지 및 제설 작업을 위해 입장이 제한될 수 있습니다."
  elif (
      open_wsd >= LIMITS["WIND_DANGER"]
      or open_wav >= LIMITS["WAVE_DANGER"]
      or open_pcp_3h >= LIMITS["RAIN_3H_DANGER"]
  ):
    a_level = "danger"
    a_stat = "출입 통제 예상 (기상 악화)"
    a_desc = f"낮 시간대 강한 바람({open_wsd:.1f}m/s) 또는 높은 파도({open_wav:.1f}m)로 인해 입장이 통제될 가능성이 높습니다."
  elif (
      open_wsd >= LIMITS["WIND_CAUTION"]
      or open_wav >= LIMITS["WAVE_CAUTION"]
      or open_pcp_1h >= LIMITS["RAIN_1H_CAUTION"]
  ):
    a_level = "caution"
    a_stat = "방문 주의 (기상 변화 유의)"
    a_desc = f"오후 파도({open_wav:.1f}m) 또는 바람({open_wsd:.1f}m/s)이 다소 강하므로 노약자분들은 탐방에 주의하시기 바랍니다."
  else:
    a_level = "safe"
    a_stat = "정상 운영 예상 (전 구간 관람 양호)"
    a_desc = f"낮 최고 파도 {open_wav:.1f}m, 바람 {open_wsd:.1f}m/s로 마감 시간까지 편안한 관람이 가능합니다."

  # [쾌적 탐방 추천 시간대]
  cur_h_str = f"{now_kst.hour:02d}00"
  rem_open = open_data[open_data["fcstTime"] >= cur_h_str].copy()
  if not rem_open.empty and now_kst.hour <= 16:
    best_row = rem_open.sort_values(
        by=["WAV", "PCP_NUM", "WSD"], ascending=[True, True, True]
    ).iloc[0]
    b_hour = int(best_row["fcstTime"][:2])
    best_time = (
        f"오늘 {b_hour}시 전후 (예상 파도 {best_row['WAV']:.1f}m, 바람"
        f" {best_row['WSD']:.1f}m/s로 가장 잔잔한 시간대)"
    )
  else:
    tmrw_str = (now_kst + datetime.timedelta(days=1)).strftime("%Y%m%d")
    tmrw_open = df[
        (df["fcstDate"] == tmrw_str)
        & (
            df["fcstTime"].isin([
                "0900",
                "1000",
                "1100",
                "1200",
                "1300",
                "1400",
                "1500",
                "1600",
            ])
        )
    ]
    if not tmrw_open.empty:
      b_row = tmrw_open.sort_values(
          by=["WAV", "PCP_NUM", "WSD"], ascending=[True, True, True]
      ).iloc[0]
      b_hour = int(b_row["fcstTime"][:2])
      best_time = (
          f"내일 {b_hour}시 전후 (금일 입장 마감 / 내일 예상 파도"
          f" {b_row['WAV']:.1f}m, 바람 {b_row['WSD']:.1f}m/s)"
      )
    else:
      best_time = "오전 09:00 이후 주간 시간대 예보를 확인해 주시기 바랍니다."

  return m_level, m_stat, m_desc, a_level, a_stat, a_desc, best_time


# ==============================================================================
# 5. 향후 5일간 일자별 개방 전망 산출
# ==============================================================================
def evaluate_5day_forecast(df):
  daily_results = []
  base_dt = get_now_kst()
  weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
  labels = ["오늘", "내일", "모레", "3일 뒤", "4일 뒤"]

  for day_offset in range(5):
    dt_obj = base_dt + datetime.timedelta(days=day_offset)
    target_date = dt_obj.strftime("%Y%m%d")
    w_str = weekday_kr[dt_obj.weekday()]
    date_title = f"{dt_obj.month}월 {dt_obj.day}일 ({w_str})"

    day_data = df[df["fcstDate"] == target_date]
    if day_data.empty:
      daily_results.append({
          "label": labels[day_offset],
          "date_title": date_title,
          "level": "none",
          "status": "예보 준비 중",
          "max_wav": "-",
          "max_wsd": "-",
          "tip": "기상청 발표 대기",
      })
      continue

    op_data = day_data[
        day_data["fcstTime"].isin([
            "0900",
            "1000",
            "1100",
            "1200",
            "1300",
            "1400",
            "1500",
            "1600",
            "1700",
        ])
    ]
    if op_data.empty:
      op_data = day_data

    max_wav = (
        op_data["WAV"].max()
        if "WAV" in op_data and not op_data["WAV"].dropna().empty
        else 0.5
    )
    max_wsd = (
        op_data["WSD"].max()
        if "WSD" in op_data and not op_data["WSD"].dropna().empty
        else 3.0
    )
    max_pcp3h = (
        op_data["PCP_3H"].max()
        if "PCP_3H" in op_data and not op_data["PCP_3H"].dropna().empty
        else 0.0
    )
    max_pcp1h = (
        op_data["PCP_NUM"].max()
        if "PCP_NUM" in op_data and not op_data["PCP_NUM"].dropna().empty
        else 0.0
    )
    has_snow = (
        op_data["PTY"].astype(str).isin(["2", "3"]).any()
        if "PTY" in op_data
        else False
    )

    if (
        max_wsd >= LIMITS["WIND_DANGER"]
        or max_wav >= LIMITS["WAVE_DANGER"]
        or max_pcp3h >= LIMITS["RAIN_3H_DANGER"]
        or has_snow
    ):
      level = "danger"
      status = "출입 통제 예상"
      tip = "높은 파도·강풍 주의"
    elif (
        max_wsd >= LIMITS["WIND_CAUTION"]
        or max_wav >= LIMITS["WAVE_CAUTION"]
        or max_pcp1h >= LIMITS["RAIN_1H_CAUTION"]
    ):
      level = "caution"
      status = "방문 주의 권고"
      tip = f"파도 {max_wav:.1f}m 유의"
    else:
      level = "safe"
      status = "정상 개방 예상"
      tip = "탐방 기상 양호"

    daily_results.append({
        "label": labels[day_offset],
        "date_title": date_title,
        "level": level,
        "status": status,
        "max_wav": f"{max_wav:.1f} m",
        "max_wsd": f"{max_wsd:.1f} m/s",
        "tip": tip,
    })
  return daily_results


def render_status_box(level, text):
  if level == "safe":
    st.success(f"**[정상 개방]** {text}")
  elif level == "caution":
    st.warning(f"**[방문 주의]** {text}")
  elif level == "danger":
    st.error(f"**[출입 통제]** {text}")
  else:
    st.info(f"**[예보 대기]** {text}")


# ==============================================================================
# 6. 메인 데이터 로드 및 상단 화면 구성
# ==============================================================================
try:
  base_date, base_time = get_latest_base_datetime()
  df = fetch_forecast_data(AUTH_KEY, base_date, base_time)
  m_level, m_stat, m_desc, a_level, a_stat, a_desc, best_time = (
      evaluate_today_risk(df)
  )
  forecast_5days = evaluate_5day_forecast(df)
except Exception as e:
  st.error(
      "기상청 예보 데이터를 불러오는 중 일시적인 통신 지연이 발생했습니다. 잠시"
      f" 후 다시 시도해 주십시오. ({e})"
  )
  st.stop()


# [초기 안내 팝업창]
@st.dialog("정동·심곡 바다부채길 금일 탐방 안내")
def show_safety_modal():
  st.markdown("#### 금일 기상 여건에 따른 탐방로 운영 전망")

  st.markdown("**1. 오전 개방 전망 (09:00 개장 시점)**")
  render_status_box(m_level, m_stat)
  st.write(m_desc)

  st.markdown("**2. 오후 운영 전망 (09:00 ~ 17:30)**")
  render_status_box(a_level, a_stat)
  st.write(a_desc)

  st.divider()
  st.markdown(f"**쾌적 탐방 추천 시간**: {best_time}")
  st.markdown(
      "**매표소 직통 문의**: 정동매표소 `033-641-9444` / 심곡매표소"
      " `033-641-9445`"
  )
  st.caption(
      "※ 바다부채길은 해안 절벽 탐방로 특성상 너울성 파도 및 강풍 시 관람객"
      " 안전을 위해 예고 없이 통제될 수 있습니다."
  )

  if st.button("창 닫기 및 상세 기상표 보기", type="primary", width="stretch"):
    st.rerun()


if "popup_seen" not in st.session_state:
  st.session_state.popup_seen = True
  show_safety_modal()

# 상단 기관 헤더 영역
col_h, col_b = st.columns([3.5, 1])
with col_h:
  st.title("정동·심곡 바다부채길 기상 및 탐방 안내")
  st.write(
      "기상청 단기예보 실시간 연동 | 강원특별자치도 강릉시 강동면 (격자 96,"
      f" 131) | 발표 시각: {base_date[:4]}.{base_date[4:6]}.{base_date[6:]}"
      f" {base_time[:2]}:{base_time[2:]}"
  )
with col_b:
  st.write("")
  if st.button("금일 요약 안내창 다시 열기", type="primary", width="stretch"):
    show_safety_modal()

# 이용 시간 및 문의처 안내
with st.container(border=True):
  info_c1, info_c2 = st.columns(2)
  with info_c1:
    st.markdown(
        "**운영 및 매표 시간 안내**\n"
        "- **하절기 (4월 ~ 10월)**: 09:00 ~ 17:30 (매표 마감 **16:30**)\n"
        "- **동절기 (11월 ~ 3월)**: 09:00 ~ 16:30 (매표 마감 **15:30**)"
    )
  with info_c2:
    st.markdown(
        "**현장 관리사무소 전화 문의**\n"
        "- **정동매표소**: **033-641-9444** (강릉시 강동면 정동진리 50-13)\n"
        "- **심곡매표소**: **033-641-9445** (강릉시 강동면 심곡리 114-3)"
    )

st.write("")

# ==============================================================================
# 섹션 1. 금일 탐방로 시간대별 개방 전망
# ==============================================================================
st.subheader("1. 금일 탐방로 시간대별 개방 전망")
with st.container(border=True):
  d1, d2 = st.columns(2)
  with d1:
    st.markdown("#### 오전 개장 전 기상 진단 (06:00 ~ 08:00)")
    render_status_box(m_level, m_stat)
    st.write(m_desc)
  with d2:
    st.markdown("#### 주간 관람 시간대 기상 진단 (09:00 ~ 16:00)")
    render_status_box(a_level, a_stat)
    st.write(a_desc)

  st.info(f"**금일 가장 쾌적한 탐방 시간대**: {best_time}")

st.write("")

# ==============================================================================
# 섹션 2. 향후 5일간 일자별 개방 전망
# ==============================================================================
st.subheader("2. 향후 5일간 일자별 개방 전망")
st.write(
    "기상청 예보를 바탕으로 산출한 향후 5일간의 탐방로 개방 예상 현황입니다."
)

cols = st.columns(5)
for i, item in enumerate(forecast_5days):
  with cols[i]:
    with st.container(border=True):
      st.markdown(f"#### {item['label']} ({item['date_title']})")
      if item["level"] == "safe":
        st.success(f"**{item['status']}**")
      elif item["level"] == "caution":
        st.warning(f"**{item['status']}**")
      elif item["level"] == "danger":
        st.error(f"**{item['status']}**")
      else:
        st.info(f"**{item['status']}**")

      st.write(f"- **최고 파도 높이**: {item['max_wav']}")
      st.write(f"- **최고 바람 세기**: {item['max_wsd']}")
      st.write(f"- **기상 여건**: {item['tip']}")

st.write("")

# ==============================================================================
# 섹션 3. [오늘 / 내일 / 모레] 버튼 선택형 24시간 기상 그래프
# ==============================================================================
st.subheader("3. 일자별 24시간 기상 추이 그래프")
st.write(
    "아래에서 **오늘, 내일, 모레** 버튼을 누르시면 해당 날짜의 24시간 날씨"
    " 그래프와 하단 상세표를 확인하실 수 있습니다."
)

now_kst = get_now_kst()
weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
day_objs = [now_kst + datetime.timedelta(days=i) for i in range(3)]
day_strs = [d.strftime("%Y%m%d") for d in day_objs]
day_titles = [
    f"오늘 ({day_objs[0].month}/{day_objs[0].day}"
    f" {weekday_kr[day_objs[0].weekday()]}) 24시간",
    f"내일 ({day_objs[1].month}/{day_objs[1].day}"
    f" {weekday_kr[day_objs[1].weekday()]}) 24시간",
    f"모레 ({day_objs[2].month}/{day_objs[2].day}"
    f" {weekday_kr[day_objs[2].weekday()]}) 24시간",
]

if "selected_day_idx" not in st.session_state:
  st.session_state.selected_day_idx = 0

# [오늘 / 내일 / 모레] 실시간 날짜 버튼
btn_c1, btn_c2, btn_c3 = st.columns(3)
with btn_c1:
  if st.button(
      day_titles[0],
      type="primary" if st.session_state.selected_day_idx == 0 else "secondary",
      width="stretch",
  ):
    st.session_state.selected_day_idx = 0
    st.rerun()
with btn_c2:
  if st.button(
      day_titles[1],
      type="primary" if st.session_state.selected_day_idx == 1 else "secondary",
      width="stretch",
  ):
    st.session_state.selected_day_idx = 1
    st.rerun()
with btn_c3:
  if st.button(
      day_titles[2],
      type="primary" if st.session_state.selected_day_idx == 2 else "secondary",
      width="stretch",
  ):
    st.session_state.selected_day_idx = 2
    st.rerun()

sel_idx = st.session_state.selected_day_idx
sel_date_str = day_strs[sel_idx]
plot_df = df[df["fcstDate"] == sel_date_str].copy()

if len(plot_df) < 12:
  plot_df = df.head(24).copy()

# 3시간 간격 눈금 추출: X축에는 깔끔하게 시간(00시, 03시...)만 가로로 표시
tick_mask = [
    (d.hour % 3 == 0) or (idx == 0) for idx, d in enumerate(plot_df["DATETIME"])
]
tick_vals = [
    plot_df["KR_TIME"].iloc[i] for i in range(len(plot_df)) if tick_mask[i]
]
tick_texts = [
    plot_df["HOUR_ONLY"].iloc[i] for i in range(len(plot_df)) if tick_mask[i]
]

chart_layout = dict(
    paper_bgcolor="#ffffff",
    plot_bgcolor="#f8f9fa",
    font=dict(color="#111111", size=14),
    hovermode="x unified",
    hoverlabel=dict(bgcolor="#ffffff", font_size=14, font_color="#111111"),
    margin=dict(l=38, r=14, t=48, b=50),
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.04,
        xanchor="center",
        x=0.5,
        font=dict(size=12, color="#111111"),
    ),
    xaxis=dict(
        title=dict(text="예보 시각", standoff=10),
        tickmode="array",
        tickvals=tick_vals,
        ticktext=tick_texts,
        tickangle=0,  # PC와 모바일 모두 가로 한 줄로 고정
        showgrid=True,
        gridcolor="#dee2e6",
        tickfont=dict(size=13, color="#111111"),
    ),
)

plotly_config = {"displayModeBar": False}

# (1) 파도 높이 차트
with st.container(border=True):
  st.markdown(f"#### (1) 파도 높이 (유의파고) 예측 - {day_titles[sel_idx]}")
  st.write(
      "해안 데크 특성상 파도 높이가 **1.8m 이상**이면 물보라 및 월파 위험으로"
      " 방문 자제가 권고되며, **3.0m 이상** 시 전면 출입 통제됩니다."
  )
  fig_wav = go.Figure()
  fig_wav.add_trace(
      go.Scatter(
          x=plot_df["KR_TIME"],
          y=plot_df["WAV"],
          mode="lines+markers",
          name="예상 파도 높이 (m)",
          line=dict(color="#004ea2", width=3.5),
          marker=dict(size=7),
      )
  )
  fig_wav.add_hline(
      y=LIMITS["WAVE_DANGER"],
      line_dash="dash",
      line_color="#d90429",
      line_width=2,
      annotation_text=f"출입통제 ({LIMITS['WAVE_DANGER']}m)",
      annotation_position="top left",
      annotation_bgcolor="rgba(255,255,255,0.85)",
      annotation_font=dict(size=12, color="#d90429"),
  )
  fig_wav.add_hline(
      y=LIMITS["WAVE_CAUTION"],
      line_dash="dot",
      line_color="#d97706",
      line_width=2,
      annotation_text=f"방문주의 ({LIMITS['WAVE_CAUTION']}m)",
      annotation_position="top left",
      annotation_bgcolor="rgba(255,255,255,0.85)",
      annotation_font=dict(size=12, color="#d97706"),
  )
  fig_wav.update_layout(
      **chart_layout,
      yaxis=dict(
          title="파도 (m)",
          range=[0, 4.0],
          showgrid=True,
          gridcolor="#dee2e6",
      ),
      height=330,
  )
  st.plotly_chart(fig_wav, width="stretch", config=plotly_config)

# (2) 바람 세기 차트
with st.container(border=True):
  st.markdown(f"#### (2) 바람 세기 (풍속) 예측 - {day_titles[sel_idx]}")
  st.write(
      "바람 세기가 초속 **10.0m/s 이상**이면 보행 시 강풍 주의가 필요하며,"
      " **14.0m/s 이상** 시 안전을 위해 출입이 통제됩니다."
  )
  fig_wsd = go.Figure()
  fig_wsd.add_trace(
      go.Scatter(
          x=plot_df["KR_TIME"],
          y=plot_df["WSD"],
          mode="lines+markers",
          name="예상 바람 세기 (m/s)",
          line=dict(color="#0f766e", width=3.5),
          marker=dict(size=7),
      )
  )
  fig_wsd.add_hline(
      y=LIMITS["WIND_DANGER"],
      line_dash="dash",
      line_color="#d90429",
      line_width=2,
      annotation_text=f"출입통제 ({LIMITS['WIND_DANGER']}m/s)",
      annotation_position="top left",
      annotation_bgcolor="rgba(255,255,255,0.85)",
      annotation_font=dict(size=12, color="#d90429"),
  )
  fig_wsd.add_hline(
      y=LIMITS["WIND_CAUTION"],
      line_dash="dot",
      line_color="#d97706",
      line_width=2,
      annotation_text=f"방문주의 ({LIMITS['WIND_CAUTION']}m/s)",
      annotation_position="top left",
      annotation_bgcolor="rgba(255,255,255,0.85)",
      annotation_font=dict(size=12, color="#d97706"),
  )
  fig_wsd.update_layout(
      **chart_layout,
      yaxis=dict(
          title="바람 (m/s)",
          range=[0, 18.0],
          showgrid=True,
          gridcolor="#dee2e6",
      ),
      height=330,
  )
  st.plotly_chart(fig_wsd, width="stretch", config=plotly_config)

# (3) 강수량 차트
with st.container(border=True):
  st.markdown(f"#### (3) 비 (강수량) 예측 - {day_titles[sel_idx]}")
  st.write("시간당 **15mm 이상** 비가 내릴 경우 데크 미끄럼 주의가 요구됩니다.")
  fig_pcp = go.Figure()
  fig_pcp.add_trace(
      go.Bar(
          x=plot_df["KR_TIME"],
          y=plot_df["PCP_NUM"],
          name="1시간 강수량 (mm)",
          marker_color="#2563eb",
      )
  )
  fig_pcp.add_trace(
      go.Scatter(
          x=plot_df["KR_TIME"],
          y=plot_df["PCP_3H"],
          mode="lines+markers",
          name="3시간 누적 강수 (mm)",
          line=dict(color="#1d4ed8", width=2.5, dash="dash"),
      )
  )
  fig_pcp.add_hline(
      y=LIMITS["RAIN_1H_CAUTION"],
      line_dash="dot",
      line_color="#d97706",
      line_width=2,
      annotation_text=f"미끄럼 주의 ({LIMITS['RAIN_1H_CAUTION']}mm)",
      annotation_position="top left",
      annotation_bgcolor="rgba(255,255,255,0.85)",
      annotation_font=dict(size=12, color="#d97706"),
  )
  fig_pcp.update_layout(
      **chart_layout,
      yaxis=dict(
          title="강수 (mm)",
          range=[0, max(25.0, plot_df["PCP_3H"].max() + 5.0)],
          showgrid=True,
          gridcolor="#dee2e6",
      ),
      barmode="overlay",
      height=330,
  )
  st.plotly_chart(fig_pcp, width="stretch", config=plotly_config)

# (4) 신적설량 차트
with st.container(border=True):
  st.markdown(f"#### (4) 눈 (신적설량) 예측 - {day_titles[sel_idx]}")
  st.write(
      "**0.5cm 이상** 눈이 쌓일 경우 데크 결빙 방지를 위해 제설 후 개방됩니다."
  )
  fig_sno = go.Figure()
  fig_sno.add_trace(
      go.Bar(
          x=plot_df["KR_TIME"],
          y=plot_df["SNO_NUM"],
          name="1시간 적설량 (cm)",
          marker_color="#4f46e5",
      )
  )
  fig_sno.add_hline(
      y=LIMITS["SNOW_CAUTION"],
      line_dash="dot",
      line_color="#d97706",
      line_width=2,
      annotation_text=f"제설 기준 ({LIMITS['SNOW_CAUTION']}cm)",
      annotation_position="top left",
      annotation_bgcolor="rgba(255,255,255,0.85)",
      annotation_font=dict(size=12, color="#d97706"),
  )
  fig_sno.update_layout(
      **chart_layout,
      yaxis=dict(
          title="적설 (cm)",
          range=[0, max(3.0, plot_df["SNO_NUM"].max() + 1.0)],
          showgrid=True,
          gridcolor="#dee2e6",
      ),
      height=320,
  )
  st.plotly_chart(fig_sno, width="stretch", config=plotly_config)

st.write("")

# ==============================================================================
# 섹션 4. 시간대별 기상 예보 상세표 (시간만 깔끔하게 표기 + 중앙 정렬)
# ==============================================================================
st.subheader(f"4. 시간대별 기상 예보 상세표 - {day_titles[sel_idx]}")
st.write(
    "선택하신 날짜의 시간대별 기상 수치와 탐방 여건 판정 결과입니다. (단위:"
    " 파고 m, 풍속 m/s, 강수 mm, 기온 ℃, 비확률 %)"
)

korean_table = plot_df[
    ["HOUR_ONLY", "WAV", "WSD", "PCP_NUM", "TMP", "POP"]
].copy()


def get_row_status(row):
  if row["WAV"] >= LIMITS["WAVE_DANGER"] or row["WSD"] >= LIMITS["WIND_DANGER"]:
    return "🔴통제예상"
  elif (
      row["WAV"] >= LIMITS["WAVE_CAUTION"]
      or row["WSD"] >= LIMITS["WIND_CAUTION"]
      or row["PCP_NUM"] >= LIMITS["RAIN_1H_CAUTION"]
  ):
    return "🟡방문주의"
  return "🟢탐방양호"


korean_table["판정"] = korean_table.apply(get_row_status, axis=1)
korean_table["WAV"] = korean_table["WAV"].apply(lambda x: f"{x:.1f}m")
korean_table["WSD"] = korean_table["WSD"].apply(lambda x: f"{x:.1f}m/s")
korean_table["PCP_NUM"] = korean_table["PCP_NUM"].apply(
    lambda x: "없음" if x == 0 else f"{x:.1f}mm"
)
korean_table["TMP"] = korean_table["TMP"].apply(lambda x: f"{int(x)}℃")
korean_table["POP"] = korean_table["POP"].apply(lambda x: f"{int(x)}%")

korean_table.columns = [
    "시각",
    "파고",
    "풍속",
    "강수",
    "기온",
    "비확률",
    "판정",
]

st.markdown(
    korean_table.to_markdown(
        index=False, colalign=("center",) * len(korean_table.columns)
    )
)

st.divider()
st.caption(
    "자료 출처: 기상청 단기예보 조회서비스 Open API (강원특별자치도 강릉시"
    " 강동면 격자 96, 131) | 본 시스템의 개방 전망은 기상예보 기반 예측치이며,"
    " 실제 개방 여부는 현장 관리사무소(033-641-9444)의 최종 안전 점검에 따라"
    " 결정됩니다."
)
