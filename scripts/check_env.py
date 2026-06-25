#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docparse 환경 점검: 파서별 의존 패키지·API 키 준비 상태를 한 번에 리포트.

처음 클론한 사용자가 어떤 파서를 바로 쓸 수 있는지, 무엇을 더 설치하거나
설정해야 하는지 한눈에 확인한다. 키 발급 URL도 함께 안내한다.
읽기 전용이며 아무것도 설치하거나 변경하지 않는다.

사용:  python scripts/check_env.py
"""
import importlib.util
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 안전
except Exception:
    pass

# 무료·로컬 파서 (API 키 불필요)
LOCAL = [
    {"name": "hwpx_local", "module": "hwpx_tomd", "pip": "hwpx-tomd",
     "note": "HWPX 전용·오프라인"},
    {"name": "opendataloader", "module": "opendataloader_pdf", "pip": "opendataloader-pdf",
     "note": "PDF 전용, 별도로 Java 런타임 필요"},
]

# 클라우드 파서 (API 키 필요). keys: 만족해야 할 키 후보(하나라도 충족 시 사용 가능).
#   "A+B" 형태는 A와 B를 모두 요구한다는 의미(예: GV_TOKEN+GV_PROJECT).
CLOUD = [
    {"name": "upstage", "module": "requests", "pip": "requests",
     "keys": ["UPSTAGE_API_KEY"], "url": "https://console.upstage.ai/",
     "note": "기준선·교차검증"},
    {"name": "gemini", "module": "google.genai", "pip": "google-genai",
     "keys": ["GEMINI_API_KEY"], "url": "https://aistudio.google.com/apikey",
     "note": "small PDF Primary·alt text 생성"},
    {"name": "llamaparse", "module": "llama_cloud", "pip": "llama-cloud",
     "keys": ["LLAMAPARSE_API_KEY"], "url": "https://cloud.llamaindex.ai/",
     "note": "medium 이상 PDF의 Primary"},
    {"name": "mistral", "module": "mistralai", "pip": "mistralai",
     "keys": ["MISTRAL_API_KEY"], "url": "https://console.mistral.ai/",
     "note": "3자 교차검증·비한국어"},
    {"name": "corepin", "module": "requests", "pip": "requests",
     "keys": ["COREPIN_API_KEY"], "url": "https://corepin.ai/",
     "note": "다포맷 단일 API"},
    {"name": "gvision", "module": "requests", "pip": "requests",
     "keys": ["GOOGLE_VISION_API_KEY", "GV_TOKEN+GV_PROJECT"],
     "url": "https://console.cloud.google.com/apis/credentials",
     "note": "손글씨 OCR(Vision API 활성화 필요)"},
]

# 여러 파서·스크립트가 공유하는 의존성. 없으면 일부 기능만 제한된다.
SHARED = [
    {"module": "fitz", "pip": "PyMuPDF",
     "note": "PDF 페이지 진단·렌더(gvision)·크레딧 추정(llamaparse)·alt text"},
]


def installed(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def key_ok(keys):
    """키 후보 중 하나라도 충족하면 (True, 충족한 표현)."""
    for k in keys:
        if "+" in k:
            parts = k.split("+")
            if all(os.environ.get(p) for p in parts):
                return True, k
        elif os.environ.get(k):
            return True, k
    return False, None


def main():
    print("docparse 환경 점검")
    print("=" * 40)

    usable = 0          # 지금 바로 사용 가능
    key_needed = 0      # 패키지는 OK, 키만 설정하면 사용 가능
    pkg_needed = 0      # 패키지 설치 필요

    print("\n[무료·로컬 파서] (API 키 불필요)")
    for p in LOCAL:
        if installed(p["module"]):
            print(f"  [O] {p['name']:<16} 사용 가능 · {p['note']}")
            usable += 1
        else:
            print(f"  [설치] {p['name']:<14} pip install {p['pip']}  ({p['note']})")
            pkg_needed += 1

    print("\n[클라우드 파서] (API 키 필요)")
    for p in CLOUD:
        has_pkg = installed(p["module"])
        has_key, which = key_ok(p["keys"])
        if has_pkg and has_key:
            print(f"  [O] {p['name']:<16} 사용 가능 ({which}) · {p['note']}")
            usable += 1
        elif has_pkg and not has_key:
            shown = " 또는 ".join(p["keys"])
            print(f"  [키설정] {p['name']:<13} 패키지 OK, 키 미설정: {shown}")
            print(f"          키 발급: {p['url']}")
            key_needed += 1
        else:
            shown = " 또는 ".join(p["keys"])
            print(f"  [설치] {p['name']:<14} pip install {p['pip']} · 키 미설정: {shown}")
            print(f"          키 발급: {p['url']}")
            pkg_needed += 1

    print("\n[공통 의존성]")
    for s in SHARED:
        if installed(s["module"]):
            print(f"  [O] {s['pip']:<16} 설치됨 · {s['note']}")
        else:
            print(f"  [설치] {s['pip']:<14} pip install {s['pip']}  ({s['note']})")

    print("\n" + "=" * 40)
    print(f"바로 사용 가능: {usable}  /  키 설정 시 가능: {key_needed}  /  설치 필요: {pkg_needed}")
    print("전체 한 번에 설치: pip install -r requirements.txt")
    if key_needed or pkg_needed:
        print("키는 환경 변수로 설정한다(.env.example 참고). 소스에 하드코딩하지 말 것.")


if __name__ == "__main__":
    main()
