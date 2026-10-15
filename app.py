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
# 1. 페이지 기본 환경설정 (공공기관 웹 표준 레이아웃)
# ==============================================================================
st.set_page_config(
    page_title="정동·심곡 바다부채길 기상 및 탐방 안내",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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
# 3. 기상청 단기예보 데이터 수집 및 전처리
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


@st.cache_data(ttl=1800)
def fetch_forecast_data(auth_key, base_date, base_time):
  url = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getVilageFcst"
  params = {
      "pageNo": "1",
      "numOfRows": "1000",
      "dataType": "JSON",
      "base_date": base_date,
      "base_time": base_time,
      "nx": GRID_NX,
      "ny": GRID_NY,
      "authKey": auth_key,
  }

  res = requests.get(url, params=params, timeout=10).json()
  items = res["response"]["body"]["items"]["item"]
  df = pd.DataFrame(items)

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

  # 한글 일시 표기 컬럼 생성 (어르신 가독성 개선)
  weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
  pivot_df["KR_TIME"] = pivot_df["DATETIME"].apply(
      lambda d: f"{d.month}/{d.day}({weekday_kr[d.weekday()]}) {d.hour:02d}시"
  )

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
  open_hours = today_df[
      today_df["fcstTime"].isin(
          ["0900", "1000", "1100", "1200", "1300", "1400", "1500", "1600"]
      )
  ].copy()
  if not open_hours.empty:
    best_row = open_hours.sort_values(
        by=["WAV", "PCP_NUM", "WSD"], ascending=[True, True, True]
    ).iloc[0]
    b_hour = int(best_row["fcstTime"][:2])
    b_wav = best_row["WAV"]
    b_wsd = best_row["WSD"]
    best_time = (
        f"오늘 {b_hour}시 전후 (예상 파도 {b_wav:.1f}m, 바람 {b_wsd:.1f}m/s로"
        " 가장 잔잔한 시간대)"
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
          f"내일 {b_hour}시 전후 (금일 매표 마감 / 내일 예상 파도"
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
  """시니어 가독성을 위해 색상 박스로 상태를 큼직하게 표시"""
  if level == "safe":
    st.success(f"**[정상 개방]** {text}")
  elif level == "caution":
    st.warning(f"**[방문 주의]** {text}")
  elif level == "danger":
    st.error(f"**[출입 통제]** {text}")
  else:
    st.info(f"**[예보 대기]** {text}")


# ==============================================================================
# 6. 메인 데이터 로드 및 화면 출력
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


# [초기 안내 팝업창 - 공공기관 공지 모달 형태]
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

# 이용 시간 및 문의처 안내 바 (어르신 필수 확인 정보)
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
# 섹션 3. 시간대별 기상 추이 그래프 (고대비·큰 글씨·한글 축 적용)
# ==============================================================================
st.subheader("3. 시간대별 기상 추이 그래프 (향후 48시간)")
st.write(
    "그래프에 마우스를 올리거나 화면을 터치하시면 해당 시각의 정확한 수치를 큰"
    " 글씨로 확인하실 수 있습니다."
)

plot_df = df.head(48).copy()

# 6시간 간격 한글 눈금 생성 (글자 겹침 방지 및 가독성 확보)
tick_indices = [
    i
    for i, d in enumerate(plot_df["DATETIME"])
    if d.hour in [0, 6, 12, 18] or i == 0
]
tick_vals = [plot_df["KR_TIME"].iloc[i] for i in tick_indices]

chart_layout = dict(
    paper_bgcolor="#ffffff",
    plot_bgcolor="#f8f9fa",
    font=dict(color="#111111", size=15),
    hovermode="x unified",
    hoverlabel=dict(bgcolor="#ffffff", font_size=15, font_color="#111111"),
    margin=dict(l=50, r=40, t=55, b=45),
    xaxis=dict(
        title="예보 일시",
        tickmode="array",
        tickvals=tick_vals,
        ticktext=tick_vals,
        showgrid=True,
        gridcolor="#dee2e6",
        tickfont=dict(size=13, color="#111111"),
    ),
)

# (1) 파도 높이 차트
with st.container(border=True):
  st.markdown("#### (1) 파도 높이 (유의파고) 예측")
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
      annotation_text=f"출입통제 기준 ({LIMITS['WAVE_DANGER']}m)",
      annotation_position="top right",
      annotation_font=dict(size=14, color="#d90429"),
  )
  fig_wav.add_hline(
      y=LIMITS["WAVE_CAUTION"],
      line_dash="dot",
      line_color="#d97706",
      line_width=2,
      annotation_text=f"방문주의 기준 ({LIMITS['WAVE_CAUTION']}m)",
      annotation_position="top right",
      annotation_font=dict(size=14, color="#d97706"),
  )
  fig_wav.update_layout(
      **chart_layout,
      yaxis=dict(
          title="파도 높이 (m)",
          range=[0, 4.0],
          showgrid=True,
          gridcolor="#dee2e6",
      ),
      height=340,
  )
  st.plotly_chart(fig_wav, width="stretch")

# (2) 바람 세기 차트
with st.container(border=True):
  st.markdown("#### (2) 바람 세기 (풍속) 예측")
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
      annotation_text=f"출입통제 기준 ({LIMITS['WIND_DANGER']}m/s)",
      annotation_position="top right",
      annotation_font=dict(size=14, color="#d90429"),
  )
  fig_wsd.add_hline(
      y=LIMITS["WIND_CAUTION"],
      line_dash="dot",
      line_color="#d97706",
      line_width=2,
      annotation_text=f"방문주의 기준 ({LIMITS['WIND_CAUTION']}m/s)",
      annotation_position="top right",
      annotation_font=dict(size=14, color="#d97706"),
  )
  fig_wsd.update_layout(
      **chart_layout,
      yaxis=dict(
          title="바람 세기 (m/s)",
          range=[0, 18.0],
          showgrid=True,
          gridcolor="#dee2e6",
      ),
      height=340,
  )
  st.plotly_chart(fig_wsd, width="stretch")

# (3) 강수량 및 적설량 차트 (2열 배치로 스크롤 피로도 감소)
c_rain, c_snow = st.columns(2)
with c_rain:
  with st.container(border=True):
    st.markdown("#### (3) 비 (강수량) 예측")
    st.write(
        "시간당 **15mm 이상** 비가 내릴 경우 데크 미끄럼 주의가 요구됩니다."
    )
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
        annotation_position="top right",
    )
    fig_pcp.update_layout(
        **chart_layout,
        yaxis=dict(
            title="강수량 (mm)",
            range=[0, max(25.0, plot_df["PCP_3H"].max() + 5.0)],
            showgrid=True,
            gridcolor="#dee2e6",
        ),
        barmode="overlay",
        height=320,
    )
    st.plotly_chart(fig_pcp, width="stretch")

with c_snow:
  with st.container(border=True):
    st.markdown("#### (4) 눈 (신적설량) 예측")
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
        annotation_text=f"제설작업 기준 ({LIMITS['SNOW_CAUTION']}cm)",
        annotation_position="top right",
    )
    fig_sno.update_layout(
        **chart_layout,
        yaxis=dict(
            title="적설량 (cm)",
            range=[0, max(3.0, plot_df["SNO_NUM"].max() + 1.0)],
            showgrid=True,
            gridcolor="#dee2e6",
        ),
        height=320,
    )
    st.plotly_chart(fig_sno, width="stretch")

st.write("")

# ==============================================================================
# 섹션 4. 시간대별 기상 예보표 (단위 및 한글 판정 직접 표기)
# ==============================================================================
st.subheader("4. 시간대별 기상 예보 상세표 (향후 12시간)")
st.write("각 시간대별 예상 기상 수치와 탐방 여건 판정 결과입니다.")

korean_table = plot_df[
    ["KR_TIME", "WAV", "WSD", "PCP_NUM", "TMP", "POP"]
].head(12).copy()


def get_row_status(row):
  if row["WAV"] >= LIMITS["WAVE_DANGER"] or row["WSD"] >= LIMITS["WIND_DANGER"]:
    return "출입 통제 예상"
  elif (
      row["WAV"] >= LIMITS["WAVE_CAUTION"]
      or row["WSD"] >= LIMITS["WIND_CAUTION"]
      or row["PCP_NUM"] >= LIMITS["RAIN_1H_CAUTION"]
  ):
    return "방문 주의"
  return "탐방 양호"


korean_table["탐방 여건"] = korean_table.apply(get_row_status, axis=1)
korean_table["WAV"] = korean_table["WAV"].apply(lambda x: f"{x:.1f} m")
korean_table["WSD"] = korean_table["WSD"].apply(lambda x: f"{x:.1f} m/s")
korean_table["PCP_NUM"] = korean_table["PCP_NUM"].apply(
    lambda x: "강수 없음" if x == 0 else f"{x:.1f} mm"
)
korean_table["TMP"] = korean_table["TMP"].apply(lambda x: f"{int(x)} ℃")
korean_table["POP"] = korean_table["POP"].apply(lambda x: f"{int(x)} %")

korean_table.columns = [
    "예보 일시",
    "파도 높이",
    "바람 세기",
    "강수량",
    "기온",
    "비 올 확률",
    "탐방 여건 판정",
]

st.markdown(korean_table.to_markdown(index=False))

st.divider()
st.caption(
    "자료 출처: 기상청 단기예보 조회서비스 Open API (강원특별자치도 강릉시"
    " 강동면 격자 96, 131) | 본 시스템의 개방 전망은 기상예보 기반 예측치이며,"
    " 실제 개방 여부는 현장 관리사무소(033-641-9444)의 최종 안전 점검에 따라"
    " 결정됩니다."
)
