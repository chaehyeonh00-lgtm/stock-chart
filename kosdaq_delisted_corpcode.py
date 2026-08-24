#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2015~2026 코스닥 상장폐지 기업의 DART corp_code 구하기

데이터 소스
  1) KRX 정보데이터시스템(data.krx.co.kr) '상장폐지현황'  → 종목코드/종목명/시장/폐지일/사유
  2) DART OpenAPI corpCode.xml                          → corp_code(고유번호) 매핑

사용법
  1) https://opendart.fss.or.kr 에서 무료 API 키 발급
  2) 아래 DART_API_KEY 에 입력 (또는 환경변수 DART_API_KEY)
  3) python3 kosdaq_delisted_corpcode.py
  결과: kosdaq_delisted_2015_2026.csv
"""
import os, re, io, sys, time, zipfile
import xml.etree.ElementTree as ET
import requests
import pandas as pd

DART_API_KEY = os.environ.get("DART_API_KEY", "cb5441bf426181a9412c41c1f581b3cfb2a08742")
START_DATE = "2015-01-01"
END_DATE   = "2026-12-31"
OUT_CSV    = "kosdaq_delisted_2015_2026.csv"


# ---------------------------------------------------------------------------
# 1) KRX 상장폐지 현황 (시장구분 포함)
# ---------------------------------------------------------------------------
def fetch_krx_delisted(start_date: str, end_date: str) -> pd.DataFrame:
    """KRX data.krx.co.kr 상장폐지현황(MDCSTAT23801)을 조회한다."""
    url = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd",
    }
    payload = {
        "bld": "dbms/MDC/STAT/issue/MDCSTAT23801",   # 상장폐지현황
        "mktId": "ALL",                               # 전체 시장(코스닥은 아래서 필터)
        "isuCd": "ALL", "isuCd2": "ALL",
        "strtDd": start_date.replace("-", ""),
        "endDd": end_date.replace("-", ""),
        "share": "1", "csvxls_isNo": "false",
    }
    r = requests.post(url, data=payload, headers=headers, timeout=30)
    r.raise_for_status()
    rows = r.json().get("output", [])
    df = pd.json_normalize(rows)
    if df.empty:
        return df

    # 컬럼: ISU_CD / (ISU_SRT_CD) / ISU_NM / MKT_NM / DELIST_DD / DELIST_RSN_DSC
    code_col = "ISU_SRT_CD" if "ISU_SRT_CD" in df.columns else "ISU_CD"
    df = df.rename(columns={
        code_col: "stock_code", "ISU_NM": "name", "MKT_NM": "market",
        "DELIST_DD": "delist_date", "DELIST_RSN_DSC": "reason",
    })
    # 6자리 종목코드로 정규화 (12자리 표준코드 KR7xxxxxxxx0 대응)
    def norm(c):
        c = str(c).strip()
        m = re.search(r"\d{6}", c)
        return m.group(0) if m else c
    df["stock_code"] = df["stock_code"].map(norm)
    df["delist_date"] = pd.to_datetime(df["delist_date"], errors="coerce")

    # 코스닥만 (MKT_NM에 '코스닥' 포함). 코스닥글로벌 등 세분류도 포함됨
    df = df[df["market"].astype(str).str.contains("코스닥", na=False)].copy()
    keep = ["stock_code", "name", "market", "delist_date", "reason"]
    return df[[c for c in keep if c in df.columns]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2) DART corpCode.xml
# ---------------------------------------------------------------------------
def fetch_dart_corpcode(api_key: str) -> pd.DataFrame:
    """DART 전체 공시대상회사 고유번호(corp_code) 목록."""
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    r = requests.get(url, params={"crtfc_key": api_key}, timeout=60)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    xml_bytes = zf.read("CORPCODE.xml")
    root = ET.fromstring(xml_bytes)
    recs = []
    for node in root.iter("list"):
        recs.append({
            "corp_code": (node.findtext("corp_code") or "").strip(),
            "corp_name": (node.findtext("corp_name") or "").strip(),
            "stock_code": (node.findtext("stock_code") or "").strip(),
            "modify_date": (node.findtext("modify_date") or "").strip(),
        })
    df = pd.DataFrame(recs)
    df["stock_code"] = df["stock_code"].str.replace(r"\D", "", regex=True)
    return df


# ---------------------------------------------------------------------------
# 3) 매핑: 종목코드 우선, 실패 시 회사명 보조 매칭
# ---------------------------------------------------------------------------
def _norm_name(s: str) -> str:
    s = str(s)
    s = re.sub(r"\(주\)|주식회사|㈜", "", s)
    s = re.sub(r"\s+", "", s)
    return s.strip()


def map_corpcode(delisted: pd.DataFrame, corp: pd.DataFrame) -> pd.DataFrame:
    # (a) 종목코드로 조인 — corpCode.xml에 종목코드가 남아있는 경우
    corp_by_code = corp[corp["stock_code"].str.len() == 6].drop_duplicates("stock_code")
    out = delisted.merge(
        corp_by_code[["stock_code", "corp_code", "corp_name"]],
        on="stock_code", how="left",
    )
    out["matched_by"] = out["corp_code"].notna().map({True: "stock_code", False: ""})

    # (b) 미매칭분은 회사명으로 보조 매칭 (상장폐지 후 종목코드가 공란인 경우)
    corp2 = corp.copy()
    corp2["nkey"] = corp2["corp_name"].map(_norm_name)
    name_map = corp2.groupby("nkey")["corp_code"].apply(list).to_dict()

    need = out["corp_code"].isna()
    for i in out[need].index:
        key = _norm_name(out.at[i, "name"])
        cands = name_map.get(key, [])
        if len(cands) == 1:
            out.at[i, "corp_code"] = cands[0]
            out.at[i, "matched_by"] = "name"
        elif len(cands) > 1:
            out.at[i, "corp_code"] = cands[0]          # 동명이인: 첫 후보
            out.at[i, "matched_by"] = "name_ambiguous"  # 수동 확인 권장
    return out


def main():
    if "DART" in DART_API_KEY or len(DART_API_KEY) < 30:
        sys.exit("DART_API_KEY를 먼저 설정하세요 (https://opendart.fss.or.kr).")

    print("[1/3] KRX 상장폐지 현황 조회…")
    delisted = fetch_krx_delisted(START_DATE, END_DATE)
    print(f"      코스닥 상장폐지 {len(delisted)}건")

    print("[2/3] DART corpCode.xml 다운로드…")
    corp = fetch_dart_corpcode(DART_API_KEY)
    print(f"      DART 공시대상회사 {len(corp)}건")

    print("[3/3] corp_code 매핑…")
    result = map_corpcode(delisted, corp)
    result = result.sort_values("delist_date").reset_index(drop=True)

    matched = result["corp_code"].notna().sum()
    print(f"      매핑 완료: {matched}/{len(result)}건")
    by = result["matched_by"].value_counts().to_dict()
    print(f"      매칭방식: {by}")

    result.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"저장: {OUT_CSV}")


if __name__ == "__main__":
    main()
