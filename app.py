import datetime
import re
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# ==============================================================================
# 1. 페이지 환경설정
# ==============================================================================
st.set_page_config(
    page_title="정동진 바다부채길 실시간 안전운영 예보",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ==============================================================================
# 2. 기상청 API 설정 및 악기상 안전 기준
# ==============================================================================
AUTH_KEY = "aIYY8TrRRe-GGPE60QXvsA"
GRID_NX = "96"
GRID_NY = "131"

LIMITS = {
    "WIND_CAUTION": 10.0,  # 풍속 주의: 방문 자제 권장 (m/s)
    "WIND_DANGER": 14.0,  # 풍속 경고: 출입통제 요구 (m/s)
    "WAVE_CAUTION": 1.8,  # 파고 주의: 방문 자제 권장 (m)
    "WAVE_DANGER": 3.0,  # 파고 경고: 출입통제 요구 (m)
    "RAIN_1H_CAUTION": 15.0,  # 시간당 15mm: 데크 미끄럼 주의
    "RAIN_3H_DANGER": 60.0,  # 3시간 60mm: 호우 출입통제
    "SNOW_CAUTION": 0.5,  # 신적설 0.5cm: 제설작업 주의
}


# ==============================================================================
# 3. 데이터 수집 및 전처리 파이프라인
# ==============================================================================
def get_latest_base_datetime():
  now = datetime.datetime.now()
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


@st.cache_data(ttl=3600)
def fetch_forecast_data(auth_key):
  base_date, base_time = get_latest_base_datetime()
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

  return pivot_df, base_date, base_time


# ==============================================================================
# 4. 실시간 당일 리스크 & 복합 골든타임 평가
# ==============================================================================
def evaluate_today_risk(df):
  today_str = datetime.datetime.now().strftime("%Y%m%d")
  today_df = df[df["fcstDate"] == today_str].copy()
  if today_df.empty:
    today_df = df.head(24).copy()

  # [오전 06~08시 판정]
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
    m_stat = "🔴 출입통제가 요구되는 상황"
    m_desc = f"오전 강풍({pre_wsd}m/s) 또는 파고({pre_wav}m) 등으로 정시 개방 불가 및 전면 통제 유력"
  elif pre_snow:
    m_stat = "🟡 현장 방문 자제 권장"
    m_desc = (
        "개장 전 새벽/아침 강설로 인해 데크 제설작업으로 늦게 개장할 가능성 있음"
    )
  elif (
      pre_wsd >= LIMITS["WIND_CAUTION"]
      or pre_wav >= LIMITS["WAVE_CAUTION"]
      or pre_pcp_1h >= LIMITS["RAIN_1H_CAUTION"]
  ):
    m_stat = "🟡 현장 방문 자제 권장"
    m_desc = (
        f"오전 파고({pre_wav}m) 또는 바람({pre_wsd}m/s)으로 안전 점검 후 지연"
        " 개장 가능성"
    )
  else:
    m_stat = "🟢 정상 운영 (정시 개방 유력)"
    m_desc = (
        f"오전 파고 {pre_wav}m, 바람 {pre_wsd}m/s로 양호하여 09:00 정시 개방 유력"
    )

  # [오후 09~16시 판정]
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
    a_stat = "🔴 출입통제가 요구되는 상황"
    a_desc = "운영 중 눈 예보로 인해 잠시 운영 중단 후 제설작업으로 출입 통제 가능성 있음"
  elif (
      open_wsd >= LIMITS["WIND_DANGER"]
      or open_wav >= LIMITS["WAVE_DANGER"]
      or open_pcp_3h >= LIMITS["RAIN_3H_DANGER"]
  ):
    a_stat = "🔴 출입통제가 요구되는 상황"
    a_desc = (
        f"운영 중 강풍({open_wsd}m/s) 또는 파고({open_wav}m)로 조기 퇴장 및"
        " 출입통제 요구"
    )
  elif (
      open_wsd >= LIMITS["WIND_CAUTION"]
      or open_wav >= LIMITS["WAVE_CAUTION"]
      or open_pcp_1h >= LIMITS["RAIN_1H_CAUTION"]
  ):
    a_stat = "🟡 현장 방문 자제 권장"
    a_desc = (
        f"오후 파고({open_wav}m) 또는 바람({open_wsd}m/s)으로 관람 환경 불량,"
        " 방문 자제 권장"
    )
  else:
    a_stat = "🟢 정상 운영 (안정적)"
    a_desc = f"오후 최고 파고 {open_wav}m, 풍속 {open_wsd}m/s로 마감 시간까지 안정적 탐방 가능"

  # [3대 복합 기상 골든타임 판정]
  open_hours = today_df[
      today_df["fcstTime"].isin(
          ["0900", "1000", "1100", "1200", "1300", "1400", "1500", "1600"]
      )
  ].copy()
  if not open_hours.empty:
    best_row = open_hours.sort_values(
        by=["WAV", "PCP_NUM", "WSD"], ascending=[True, True, True]
    ).iloc[0]
    b_hour = best_row["fcstTime"][:2]
    b_wav = best_row["WAV"]
    b_wsd = best_row["WSD"]
    b_pcp = best_row.get("PCP_NUM", 0.0)
    best_time = (
        f"{b_hour}:00 경 (파고 {b_wav}m, 풍속 {b_wsd}m/s, 강수"
        f" {b_pcp}mm)"
    )
  else:
    best_time = "당일 운영 시간대 예보 확인 필요"

  return m_stat, m_desc, a_stat, a_desc, best_time


# ==============================================================================
# 5. 향후 5일간 일별 운영 예측 엔진 (오늘, 내일, 모레, 3일뒤, 4일뒤)
# ==============================================================================
def evaluate_5day_forecast(df):
  daily_results = []
  base_dt = datetime.datetime.now()
  weekday_kr = ["월", "화", "수", "목", "금", "토", "일"]
  labels = ["오늘", "내일", "모레", "3일 뒤", "4일 뒤"]

  for day_offset in range(5):
    dt_obj = base_dt + datetime.timedelta(days=day_offset)
    target_date = dt_obj.strftime("%Y%m%d")
    w_str = weekday_kr[dt_obj.weekday()]
    date_title = f"{dt_obj.strftime('%m.%d')}({w_str})"

    day_data = df[df["fcstDate"] == target_date]
    if day_data.empty:
      daily_results.append({
          "label": labels[day_offset],
          "date_title": date_title,
          "badge": "⚪",
          "status": "예보 집계중",
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
      badge = "🔴"
      status = "출입통제 예상"
      tip = f"파고 {max_wav:.1f}m / 바람 {max_wsd:.1f}m"
    elif (
        max_wsd >= LIMITS["WIND_CAUTION"]
        or max_wav >= LIMITS["WAVE_CAUTION"]
        or max_pcp1h >= LIMITS["RAIN_1H_CAUTION"]
    ):
      badge = "🟡"
      status = "방문자제 예상"
      tip = f"파고 {max_wav:.1f}m 주의"
    else:
      badge = "🟢"
      status = "정상운영 예상"
      tip = "기상 양호"

    daily_results.append({
        "label": labels[day_offset],
        "date_title": date_title,
        "badge": badge,
        "status": status,
        "max_wav": f"{max_wav:.1f}m",
        "max_wsd": f"{max_wsd:.1f}m/s",
        "tip": tip,
    })
  return daily_results


# ==============================================================================
# 6. 메인 화면 렌더링
# ==============================================================================
try:
  df, base_date, base_time = fetch_forecast_data(AUTH_KEY)
  m_stat, m_desc, a_stat, a_desc, best_time = evaluate_today_risk(df)
  forecast_5days = evaluate_5day_forecast(df)
except Exception as e:
  st.error(f"기상청 데이터를 불러오는 중 오류가 발생했습니다: {e}")
  st.stop()


# [팝업 모달창]
@st.dialog("🌊 정동진 바다부채길 실시간 안전 안내")
def show_safety_modal():
  st.subheader("📋 실시간 구간별 안심 진단 요약")

  st.markdown(f"**개장 전(오전) 진단**: {m_stat}")
  st.caption(f"└ {m_desc}")

  st.markdown(f"**개장 중(오후) 진단**: {a_stat}")
  st.caption(f"└ {a_desc}")

  st.markdown(f"✨ **추천 골든타임**: **{best_time} 전후**")

  st.caption(
      "※ 바다부채길은 해안 절벽 데크 특성상 너울성 파도 및 강풍 발령 시 안전을"
      " 위해 입장이 전면 통제됩니다."
  )

  if st.button("🔍 상세 기상 분석 차트 및 데이터 보기", width="stretch"):
    st.rerun()


if "popup_seen" not in st.session_state:
  st.session_state.popup_seen = True
  show_safety_modal()

# 헤더 영역
col_h, col_b = st.columns([4, 1])
with col_h:
  st.title("🌊 정동진 바다부채길 실시간 안전운영 예보 시스템")
  st.caption(
      f"기상청 단기예보 실시간 연동 (격자 {GRID_NX}, {GRID_NY} | 발표 기준:"
      f" {base_date} {base_time})"
  )
with col_b:
  st.write("")
  if st.button("📢 안전 진단 팝업 다시보기", width="stretch"):
    show_safety_modal()

# 향후 5일간 일별 운영 예측 카드
st.subheader("📅 향후 5일간 바다부채길 개방 여부 예상")
cols = st.columns(5)
for i, item in enumerate(forecast_5days):
  with cols[i]:
    with st.container(border=True):
      st.markdown(f"**{item['label']}** `{item['date_title']}`")
      st.markdown(f"### {item['badge']} {item['status']}")
      st.caption(
          f"최고파고: **{item['max_wav']}** | 최고풍속: **{item['max_wsd']}**"
      )
      st.caption(f"상황: {item['tip']}")

# 당일 시간대별 세부 안전 진단 결과 카드
with st.container(border=True):
  st.subheader("🛡️ 당일 시간대별 세부 안전 진단 결과")
  d1, d2 = st.columns(2)
  with d1:
    st.markdown("#### 개장 전 (06:00 ~ 08:00) 진단")
    st.markdown(f"### {m_stat}")
    st.caption(f"└ {m_desc}")
  with d2:
    st.markdown("#### 개장 중 (09:00 ~ 16:00) 진단")
    st.markdown(f"### {a_stat}")
    st.caption(f"└ {a_desc}")

  st.info(
      f"✨ **당일 추천 골든타임**: {best_time} 전후 (하루 중 파고 및 바람이 가장 잔잔하여"
      " 안전 탐방에 가장 적합한 시간대)"
  )

# 4대 악기상 예측 차트
st.subheader("📈 향후 48시간 4대 악기상 예측 추이")
st.caption(
    "차트 위에 마우스를 올리거나 터치하면 시간대별 정밀 수치를 확인할 수 있습니다."
)

plot_df = df.head(48).copy()
chart_layout = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(15, 28, 48, 0.6)",
    font=dict(color="#e0e6ed"),
    hovermode="x unified",
    margin=dict(l=40, r=40, t=40, b=30),
    xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
)

# 1. 파고 차트
fig_wav = go.Figure()
fig_wav.add_trace(
    go.Scatter(
        x=plot_df["DATETIME"],
        y=plot_df["WAV"],
        mode="lines+markers",
        name="예상 유의파고 (m)",
        line=dict(color="#00b4d8", width=3),
        marker=dict(size=6),
    )
)
fig_wav.add_hline(
    y=LIMITS["WAVE_DANGER"],
    line_dash="dash",
    line_color="#ff4757",
    annotation_text=f"출입통제 기준 ({LIMITS['WAVE_DANGER']}m)",
    annotation_position="top right",
)
fig_wav.add_hline(
    y=LIMITS["WAVE_CAUTION"],
    line_dash="dot",
    line_color="#ffab00",
    annotation_text=f"방문자제 기준 ({LIMITS['WAVE_CAUTION']}m)",
    annotation_position="top right",
)
fig_wav.update_layout(
    **chart_layout,
    title="🌊 [1] 예상 유의파고 추이 (월파 및 데크 안전)",
    yaxis=dict(
        title="파고 (m)",
        range=[0, 4.0],
        showgrid=True,
        gridcolor="rgba(255,255,255,0.08)",
    ),
    height=320,
)
st.plotly_chart(fig_wav, width="stretch")

# 2. 풍속 차트
fig_wsd = go.Figure()
fig_wsd.add_trace(
    go.Scatter(
        x=plot_df["DATETIME"],
        y=plot_df["WSD"],
        mode="lines+markers",
        name="현장 풍속 (m/s)",
        line=dict(color="#ffa502", width=3),
        marker=dict(size=6),
    )
)
fig_wsd.add_hline(
    y=LIMITS["WIND_DANGER"],
    line_dash="dash",
    line_color="#ff4757",
    annotation_text=f"출입통제 기준 ({LIMITS['WIND_DANGER']}m/s)",
    annotation_position="top right",
)
fig_wsd.add_hline(
    y=LIMITS["WIND_CAUTION"],
    line_dash="dot",
    line_color="#ffab00",
    annotation_text=f"방문자제 기준 ({LIMITS['WIND_CAUTION']}m/s)",
    annotation_position="top right",
)
fig_wsd.update_layout(
    **chart_layout,
    title="💨 [2] 예상 풍속 추이 (강풍 및 돌풍 주의)",
    yaxis=dict(
        title="풍속 (m/s)",
        range=[0, 18.0],
        showgrid=True,
        gridcolor="rgba(255,255,255,0.08)",
    ),
    height=320,
)
st.plotly_chart(fig_wsd, width="stretch")

# 3. 강수량 차트
fig_pcp = go.Figure()
fig_pcp.add_trace(
    go.Bar(
        x=plot_df["DATETIME"],
        y=plot_df["PCP_NUM"],
        name="1시간 강수량 (mm)",
        marker_color="#1e90ff",
        opacity=0.75,
    )
)
fig_pcp.add_trace(
    go.Scatter(
        x=plot_df["DATETIME"],
        y=plot_df["PCP_3H"],
        mode="lines+markers",
        name="3시간 누적 호우 (mm)",
        line=dict(color="#70a1ff", width=2.5, dash="dash"),
    )
)
fig_pcp.add_hline(
    y=LIMITS["RAIN_3H_DANGER"],
    line_dash="dash",
    line_color="#ff4757",
    annotation_text=f"호우 출입통제 ({LIMITS['RAIN_3H_DANGER']}mm)",
    annotation_position="top right",
)
fig_pcp.add_hline(
    y=LIMITS["RAIN_1H_CAUTION"],
    line_dash="dot",
    line_color="#ffab00",
    annotation_text=f"데크 미끄럼 주의 ({LIMITS['RAIN_1H_CAUTION']}mm)",
    annotation_position="top right",
)
fig_pcp.update_layout(
    **chart_layout,
    title="🌧️ [3] 예상 강수량 추이 (호우 및 침수)",
    yaxis=dict(
        title="강수량 (mm)", showgrid=True, gridcolor="rgba(255,255,255,0.08)"
    ),
    barmode="overlay",
    height=320,
)
st.plotly_chart(fig_pcp, width="stretch")

# 4. 신적설량 차트
fig_sno = go.Figure()
fig_sno.add_trace(
    go.Bar(
        x=plot_df["DATETIME"],
        y=plot_df["SNO_NUM"],
        name="1시간 신적설 (cm)",
        marker_color="#a55eea",
    )
)
fig_sno.add_hline(
    y=LIMITS["SNOW_CAUTION"],
    line_dash="dot",
    line_color="#ffab00",
    annotation_text=f"제설작업 주의선 ({LIMITS['SNOW_CAUTION']}cm)",
    annotation_position="top right",
)
fig_sno.update_layout(
    **chart_layout,
    title="❄️ [4] 예상 신적설 추이 (대설 및 결빙)",
    yaxis=dict(
        title="적설량 (cm)",
        range=[0, max(5.0, plot_df["SNO_NUM"].max() + 1.0)],
        showgrid=True,
        gridcolor="rgba(255,255,255,0.08)",
    ),
    height=320,
)
st.plotly_chart(fig_sno, width="stretch")

# 시간대별 상세 데이터 표
st.subheader("📋 시간대별 기상예보 상세 데이터")
korean_table = plot_df[[
    "DATETIME",
    "WAV",
    "WSD",
    "PCP_NUM",
    "PCP_3H",
    "SNO_NUM",
    "TMP",
    "POP",
]].head(12).copy()
korean_table.columns = [
    "예보일시",
    "유의파고(m)",
    "풍속(m/s)",
    "1시간강수(mm)",
    "3시간누적(mm)",
    "신적설(cm)",
    "기온(℃)",
    "강수확률(%)",
]
korean_table["예보일시"] = korean_table["예보일시"].dt.strftime("%m-%d %H:%M")

st.markdown(korean_table.to_markdown(index=False))

st.caption(
    "Data Source: Korea Meteorological Administration API Hub (Grid 96, 131) |"
    " Jeongdongjin Badabuchae-gil Safety Forecasting System"
)
