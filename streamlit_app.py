# -*- coding: utf-8 -*-
"""
주가 차트 (Streamlit)
---------------------
종목코드와 기간을 입력하면 인터랙티브 캔들차트를 보여줍니다.
Streamlit Community Cloud 등에 올리면 링크만으로 실행할 수 있습니다.

로컬 실행:  pip install -r requirements.txt  →  streamlit run streamlit_app.py
"""

import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import FinanceDataReader as fdr
import streamlit as st

st.set_page_config(page_title="주가 차트 조회", page_icon="📈", layout="wide")

INTERVAL_LABELS = {"1d": "일봉", "1wk": "주봉", "1mo": "월봉", "3mo": "분기봉"}
RESAMPLE_RULE = {"1wk": "W", "1mo": "ME", "3mo": "QE"}
UP, DOWN = "#e5342b", "#1f6fe5"  # 한국식: 상승 빨강 / 하락 파랑

# 관심 종목: 코드 -> 기업명 (상장폐지 종목도 이름이 뜨도록 직접 지정)
STOCK_NAMES = {
    "059270": "해성에어로보틱스",
    "313760": "캐리",
    "060230": "제이케이시냅스",
    "023440": "제이스코홀딩스",
    "196490": "디에이테크놀로지",
    "217620": "선샤인푸드",
    "203690": "아크솔루션스",
    "082210": "옵트론텍",
    "227100": "프로브잇",
    "323230": "엠에프엠코리아",
    "041590": "플래스크",
    "224060": "더코디",
    "317240": "TS트릴리온",
    "017000": "신원종합개발",
    "214870": "한울비앤씨",
    "136510": "스마트솔루션즈",
    "033310": "엠투엔",
    "219750": "한국비티비",
    "096640": "멜파스",
    "159910": "에코글로우",
    "056000": "코원플레이",
    "060300": "레드로버",
    "197140": "디지캡",
    "215090": "솔디펜스",
    "099520": "DGI",
    "045890": "금빛",
    "058420": "제이웨이",
    "066110": "한프",
    "086250": "화신테크",
    "127160": "매직마이크로",
    "900100": "파이온엑스",
    "029480": "광무",
    "036260": "이매진아시아",
    "080440": "에스제이케이",
    "033600": "럭슬",
    "082660": "코스나인",
    "150840": "인트로메딕",
    "069540": "빛과전자",
    "106520": "노블엠앤비",
    "197210": "리드",
    "111820": "지유온",
    "083470": "이엠앤아이",
    "008800": "행남사",
    "131100": "티엔엔터테인먼트",
    "030270": "에스마크",
    "047440": "디케이씨",
    "112240": "에스에프씨",
    "038530": "케이바이오랩스",
    "058370": "비엔씨컴퍼니",
    "068150": "케이엔씨글로벌",
    "056730": "CNT85",
    "036500": "에스에스컴텍",
    "038160": "팍스넷",
}
WATCHLIST = list(STOCK_NAMES.keys())


@st.cache_data(show_spinner=False)
def get_stock_name(code: str) -> str:
    # 1) 직접 지정한 이름(상장폐지 종목 포함) 우선
    if code in STOCK_NAMES:
        return STOCK_NAMES[code]
    # 2) 없으면 KRX 현재 상장목록에서 조회
    try:
        listing = fdr.StockListing("KRX").set_index("Code")["Name"]
        return str(listing.get(code, code))
    except Exception:
        return code


@st.cache_data(show_spinner=False)
def get_stock_data(code, start, end, interval):
    """FinanceDataReader 조회 + 원본 노트북 정제 로직."""
    df = fdr.DataReader(code, start, end)
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)

    ohlc = ["Open", "High", "Low", "Close"]
    zero_rows = (df[ohlc] == 0).any(axis=1)
    df.loc[zero_rows, ohlc] = np.nan
    df["Close"] = df["Close"].ffill()
    for col in ohlc:
        df.loc[zero_rows, col] = df.loc[zero_rows, "Close"]
    df = df.dropna(subset=ohlc)

    rule = RESAMPLE_RULE.get(interval)
    if rule:
        df = df.resample(rule).agg(
            {"Open": "first", "High": "max", "Low": "min",
             "Close": "last", "Volume": "sum"}
        ).dropna()
    return df


def build_figure(df, code, interval):
    name = get_stock_name(code)
    chart_type = INTERVAL_LABELS.get(interval, interval)
    x = df.index.strftime("%Y-%m-%d").tolist()
    vol_colors = [UP if c >= o else DOWN for o, c in zip(df["Open"], df["Close"])]

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="주가",
        increasing=dict(line=dict(color=UP), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN), fillcolor=DOWN),
        yaxis="y",
    ))
    fig.add_trace(go.Bar(
        x=x, y=df["Volume"], name="거래량",
        marker=dict(color=vol_colors, line=dict(width=0)),
        yaxis="y2", hovertemplate="거래량 %{y:,.0f}<extra></extra>",
    ))

    fig.update_layout(
        title=dict(text=f"{name} ({code}) · {chart_type} 주가 추이",
                   x=0.01, xanchor="left", font=dict(size=20)),
        height=680, margin=dict(l=60, r=40, t=60, b=40),
        paper_bgcolor="white", plot_bgcolor="white",
        dragmode="pan", hovermode="x unified", showlegend=False,
        xaxis=dict(domain=[0, 1], anchor="y2", type="category",
                   showgrid=True, gridcolor="#eee", nticks=12, tickangle=-30,
                   rangeslider=dict(visible=False)),
        yaxis=dict(domain=[0.30, 1.0], title="주가", showgrid=True,
                   gridcolor="#eee", tickformat=",", side="right"),
        yaxis2=dict(domain=[0.0, 0.22], title="거래량", showgrid=True,
                    gridcolor="#eee", tickformat=".2s", side="right"),
        font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif"),
    )
    return fig, name, chart_type


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("📈 주가 차트 조회")
st.caption("종목코드와 기간을 입력하면 인터랙티브 캔들차트를 보여줍니다. (한국거래소 · FinanceDataReader)")

if "code" not in st.session_state:
    st.session_state.code = WATCHLIST[0]


def _pick_from_watchlist():
    st.session_state.code = st.session_state.watch_pick


with st.sidebar:
    st.subheader("관심 종목")
    st.selectbox(
        "목록에서 선택",
        options=WATCHLIST,
        key="watch_pick",
        format_func=lambda c: f"{get_stock_name(c)} ({c})",
        on_change=_pick_from_watchlist,
    )
    st.caption(f"총 {len(WATCHLIST)}개 · 선택하면 아래 차트가 바뀝니다.")

c1, c2, c3, c4 = st.columns([1.2, 1, 1, 1])
with c1:
    code = st.text_input("종목코드", key="code", placeholder="예: 005930")
with c2:
    start = st.date_input("시작일", dt.date.today() - dt.timedelta(days=180))
with c3:
    end = st.date_input("종료일", dt.date.today())
with c4:
    interval = st.selectbox("봉 종류", list(INTERVAL_LABELS.keys()),
                            format_func=lambda k: INTERVAL_LABELS[k])

code = (code or "").strip()

if not code:
    st.info("종목코드를 입력하세요.")
    st.stop()

try:
    with st.spinner("데이터를 불러오는 중…"):
        df = get_stock_data(code, start.isoformat(), end.isoformat(), interval)
except Exception as e:
    st.error(f"데이터 조회 실패: {e}")
    st.stop()

if df is None or df.empty:
    st.warning("해당 기간에 데이터가 없습니다. 종목코드/기간을 확인하세요.")
    st.stop()

fig, name, chart_type = build_figure(df, code, interval)
st.plotly_chart(
    fig, use_container_width=True,
    config={
        "scrollZoom": True, "displaylogo": False,
        "toImageButtonOptions": {"format": "png", "scale": 3,
                                 "filename": f"{code}_{interval}"},
        "modeBarButtonsToRemove": ["select2d", "lasso2d"],
    },
)
st.caption(f"{name} · {chart_type} · {len(df)}개 봉  |  드래그 이동 · 스크롤 확대 · 더블클릭 초기화 · 카메라 아이콘으로 PNG 저장")

# CSV 다운로드 (엑셀 한글 깨짐 방지: utf-8-sig)
csv_df = df.copy()
csv_df.index.name = "Date"
csv_bytes = csv_df.to_csv(encoding="utf-8-sig").encode("utf-8-sig")
st.download_button(
    label="⬇️ CSV로 다운로드",
    data=csv_bytes,
    file_name=f"{name}_{code}_{interval}_{start.isoformat()}_{end.isoformat()}.csv",
    mime="text/csv",
    use_container_width=False,
)

with st.expander("원본 시세 데이터 보기"):
    st.dataframe(df, use_container_width=True)
