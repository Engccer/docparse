"""Upstage Document Parse 파서 (docparse).

  python upstage_parse.py "<파일>"   → <파일>_upstage.md

실패 계약(2026-08-31): 오류·빈 결과·비동기 배치 일부 누락이면 출력 파일을 만들지
않고 종료 코드 1. 실행 시작 시 같은 이름의 이전 출력을 지운다(실패한 실행 뒤
어제 파일이 오늘 결과로 오인되는 것 방지). header/footer/page_number로 분류돼
제거된 요소는 텍스트 표본을 표준 출력에 남겨, 의미 있는 머리말(문서번호·
당사자 식별자 등)이 조용히 사라지지 않게 한다.
"""
import os
import sys
import time
import traceback

REMOVED_SAMPLE_MAX = 20


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    try:
        import requests
    except ImportError as e:
        print("오류: requests 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install requests")
        print(f"상세: {e}")
        return 1

    # API 키 설정
    try:
        api_key = os.environ["UPSTAGE_API_KEY"]
    except KeyError:
        print("오류: UPSTAGE_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export UPSTAGE_API_KEY=\"your-api-key\"  (Windows: setx UPSTAGE_API_KEY \"your-api-key\")")
        return 1

    # 지원 파일 확장자
    SUPPORTED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png', '.hwp', '.hwpx', '.docx', '.pptx', '.xlsx']

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_upstage.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def clear_stale_output(output_file):
        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"기존 출력 제거: {output_file}")

    # 필터링할 노이즈 카테고리 (헤더, 푸터, 페이지 번호)
    NOISE_CATEGORIES = {"header", "footer", "page_number"}

    def filter_noise_from_elements(result):
        """elements에서 header/footer/page_number를 제거하고 markdown 재조합.

        제거한 요소의 텍스트 표본을 출력해 검토 가능하게 남긴다.
        """
        elements = result.get("elements", [])
        if not elements:
            # elements가 없으면 content.markdown 그대로 반환
            return result.get("content", {}).get("markdown", "")

        filtered_parts = []
        removed = []
        for elem in elements:
            category = elem.get("category", "")
            md = elem.get("content", {}).get("markdown", "") or elem.get("content", {}).get("text", "")
            if category in NOISE_CATEGORIES:
                removed.append((category, " ".join(md.split())[:60]))
                continue
            if md:
                filtered_parts.append(md)

        if removed:
            print(f"노이즈 제거: {len(removed)}개 요소 (header/footer/page_number) 필터링됨. 제거된 텍스트 표본:")
            seen = set()
            shown = 0
            for category, text in removed:
                key = (category, text)
                if key in seen or not text:
                    continue
                seen.add(key)
                print(f"  - [{category}] {text}")
                shown += 1
                if shown >= REMOVED_SAMPLE_MAX:
                    print(f"  ... 외 {len(removed) - shown}건")
                    break
            print("  (문서번호·당사자 식별자처럼 본문 정보가 섞여 있으면 퓨전 때 되살릴 것)")

        return "\n\n".join(filtered_parts)

    def save_markdown(filename, markdown_content, page_count=None):
        output_file = get_output_filename(filename)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        if page_count:
            print(f"변환 완료! {page_count}페이지, {len(markdown_content)}글자가 저장되었습니다.")
        else:
            print(f"변환 완료! {len(markdown_content)}글자가 저장되었습니다.")
        print(f"출력 파일: {output_file}")

    def request_data():
        return {
            "model": "document-parse-nightly",
            "ocr": "auto",
            "mode": "enhanced",
            "output_formats": "['markdown']",
            "coordinates": "false",
        }

    def sync_parse(filename):
        """동기 방식 문서 파싱 (새 API, enhanced 모드)"""
        url = "https://api.upstage.ai/v1/document-digitization"
        headers = {"Authorization": f"Bearer {api_key}"}
        with open(filename, "rb") as fh:
            return requests.post(url, headers=headers, files={"document": fh}, data=request_data())

    def async_parse(filename):
        """비동기 방식 문서 파싱. 성공 시 (markdown, 배치 수), 실패 시 None.

        배치 하나라도 download_url이 없거나 다운로드·JSON 해석에 실패하면 전체를
        실패로 본다(일부 쪽이 빠진 파일을 완료본으로 저장하지 않는다).
        """
        print("비동기 모드로 전환합니다...")
        url = "https://api.upstage.ai/v1/document-digitization/async"
        headers = {"Authorization": f"Bearer {api_key}"}
        with open(filename, "rb") as fh:
            response = requests.post(url, headers=headers, files={"document": fh}, data=request_data())
        if response.status_code not in [200, 202]:
            print(f"비동기 API 오류: {response.status_code} - {response.text}")
            return None

        job_data = response.json()
        request_id = job_data.get("request_id")
        if not request_id:
            print("비동기 작업 ID 없음. 응답 확인:", job_data)
            return None

        print(f"비동기 작업 ID: {request_id}")

        # 폴링: 상태 및 결과 확인
        status_url = f"https://api.upstage.ai/v1/document-digitization/requests/{request_id}"

        while True:
            status_response = requests.get(status_url, headers=headers)
            status_data = status_response.json()
            status = status_data.get("status")
            print(f"비동기 처리 상태: {status}")

            if status == "completed":
                batches = status_data.get("batches", [])
                if not batches:
                    print("오류: completed 상태인데 배치 목록이 비어 있습니다.")
                    return None
                all_parts = []
                for idx, batch in enumerate(batches, 1):
                    download_url = batch.get("download_url")
                    if not download_url:
                        print(f"오류: 배치 {idx}/{len(batches)}에 download_url이 없습니다. 부분 결과를 저장하지 않습니다.")
                        return None
                    result_response = requests.get(download_url, headers=headers)
                    if result_response.status_code != 200:
                        print(f"오류: 배치 {idx}/{len(batches)} 다운로드 실패 ({result_response.status_code}).")
                        return None
                    try:
                        result = result_response.json()
                    except ValueError as e:
                        print(f"오류: 배치 {idx}/{len(batches)} 결과가 JSON이 아닙니다: {e}")
                        print("  서버 측 파싱은 완료(과금)된 상태일 수 있으니 무턱대고 재실행하지 말 것(gotchas.md).")
                        return None
                    all_parts.append(filter_noise_from_elements(result))
                return "\n".join(all_parts), len(batches)
            elif status == "failed":
                print(f"비동기 처리 실패: {status_data.get('error', '알 수 없는 오류')}")
                return None

            time.sleep(5)

    def process_file(filename):
        """단일 파일 문서 파싱. 출력 파일을 만들었으면 True."""
        print(f"입력 파일: {filename}")
        clear_stale_output(get_output_filename(filename))

        # 실행: 동기 먼저 시도, 실패 시 비동기로 전환
        print("변환 중... (enhanced 모드)")
        response = sync_parse(filename)

        if response.status_code == 200:
            result = response.json()
            markdown_content = filter_noise_from_elements(result)
            if not markdown_content:
                # elements 필터링 결과가 비어있으면 content.markdown 사용
                markdown_content = result.get("content", {}).get("markdown", "")
            if markdown_content and markdown_content.strip():
                page_count = result.get("usage", {}).get("pages", None)
                save_markdown(filename, markdown_content, page_count)
                return True
            print("오류: Markdown 내용이 비어 있습니다. 출력 파일을 만들지 않았습니다.")
            return False

        if response.status_code == 413 or "too large" in response.text.lower():
            print(f"파일이 너무 큽니다. (응답: {response.status_code})")
        else:
            print(f"동기 API 오류: {response.status_code} - {response.text}")
            print("비동기 방식으로 재시도합니다...")
        async_result = async_parse(filename)
        if not async_result:
            print("오류: 비동기 파싱 실패. 출력 파일을 만들지 않았습니다.")
            return False
        markdown_content, page_count = async_result
        if not markdown_content.strip():
            print("오류: 비동기 결과가 비어 있습니다. 출력 파일을 만들지 않았습니다.")
            return False
        save_markdown(filename, markdown_content, page_count)
        return True

    # 명령줄 인수로 파일 경로 받기
    if len(sys.argv) > 1:
        filename = sys.argv[1]
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
            return 1
        if not os.path.exists(filename):
            print(f"오류: 파일을 찾을 수 없습니다: {filename}")
            return 1
        return 0 if process_file(filename) else 1

    # 현재 디렉토리에서 지원되는 파일 찾기
    supported_files = sorted([f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS])
    if not supported_files:
        print("오류: 현재 디렉토리에 지원되는 파일이 없습니다.")
        print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
        return 1
    if len(supported_files) == 1:
        return 0 if process_file(supported_files[0]) else 1

    print(f"지원되는 파일 {len(supported_files)}개 발견:")
    for i, f in enumerate(supported_files, 1):
        print(f"  {i}. {f}")
    print()
    print("1) 하나씩 선택하여 변환")
    print("2) 모두 변환")
    choice = input("선택 (1/2): ").strip()
    print()

    all_ok = True
    for i, f in enumerate(supported_files, 1):
        if choice != "2":
            yn = input(f"[{i}/{len(supported_files)}] {f} 변환? (Y/N): ").strip().upper()
            if yn != "Y":
                print("건너뜀.")
                print()
                continue
        else:
            print(f"[{i}/{len(supported_files)}] {f}")
        try:
            all_ok = process_file(f) and all_ok
        except Exception as e:
            print(f"오류 발생: {e}")
            all_ok = False
        print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    exit_code = 1
    try:
        exit_code = main()
    except Exception as e:
        print(f"\n오류 발생: {e}")
        print("\n상세 정보:")
        traceback.print_exc()

    # 대화형 터미널에서 수동 실행할 때만 종료 전 일시정지. AI 에이전트·
    # 백그라운드·파이프 등 비-TTY 실행에서는 stdin이 EOF로 닫히지 않아
    # input()이 무한 블록되므로 isatty()로 가드 (2026-05-19).
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nEnter를 눌러 종료...")
        except EOFError:
            pass
    sys.exit(exit_code)
