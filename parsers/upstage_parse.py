import os
import sys
import time
import traceback

def main():
    try:
        import requests
    except ImportError as e:
        print(f"오류: requests 패키지를 찾을 수 없습니다.")
        print(f"설치 명령: pip install requests")
        print(f"상세: {e}")
        return

    # API 키 설정
    try:
        api_key = os.environ["UPSTAGE_API_KEY"]
    except KeyError:
        print("오류: UPSTAGE_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export UPSTAGE_API_KEY=\"your-api-key\"  (Windows: setx UPSTAGE_API_KEY \"your-api-key\")")
        return

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

    # 필터링할 노이즈 카테고리 (헤더, 푸터, 페이지 번호)
    NOISE_CATEGORIES = {"header", "footer", "page_number"}

    def filter_noise_from_elements(result):
        """elements에서 header/footer/page_number를 제거하고 markdown 재조합"""
        elements = result.get("elements", [])
        if not elements:
            # elements가 없으면 content.markdown 그대로 반환
            return result.get("content", {}).get("markdown", "")

        filtered_parts = []
        removed_count = 0
        for elem in elements:
            category = elem.get("category", "")
            if category in NOISE_CATEGORIES:
                removed_count += 1
                continue
            md = elem.get("content", {}).get("markdown", "")
            if md:
                filtered_parts.append(md)

        if removed_count > 0:
            print(f"노이즈 제거: {removed_count}개 요소 (header/footer/page_number) 필터링됨")

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

    def sync_parse(filename):
        """동기 방식 문서 파싱 (새 API, enhanced 모드)"""
        url = "https://api.upstage.ai/v1/document-digitization"
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"document": open(filename, "rb")}
        data = {
            "model": "document-parse-nightly",
            "ocr": "auto",
            "mode": "enhanced",
            "output_formats": "['markdown']",
            "coordinates": "false",
        }

        response = requests.post(url, headers=headers, files=files, data=data)
        return response

    def async_parse(filename):
        """비동기 방식 문서 파싱 (새 API, enhanced 모드)"""
        print("비동기 모드로 전환합니다...")
        url = "https://api.upstage.ai/v1/document-digitization/async"
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"document": open(filename, "rb")}
        data = {
            "model": "document-parse-nightly",
            "ocr": "auto",
            "mode": "enhanced",
            "output_formats": "['markdown']",
            "coordinates": "false",
        }

        response = requests.post(url, headers=headers, files=files, data=data)
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
                all_parts = []
                for batch in batches:
                    download_url = batch.get("download_url")
                    if download_url:
                        result_response = requests.get(download_url, headers=headers)
                        result = result_response.json()
                        md = filter_noise_from_elements(result)
                        all_parts.append(md)
                return "\n".join(all_parts), len(batches)
            elif status == "failed":
                print(f"비동기 처리 실패: {status_data.get('error', '알 수 없는 오류')}")
                return None

            time.sleep(5)

    def process_file(filename):
        """단일 파일 문서 파싱"""
        print(f"입력 파일: {filename}")

        # 실행: 동기 먼저 시도, 실패 시 비동기로 전환
        print("변환 중... (enhanced 모드)")
        response = sync_parse(filename)

        if response.status_code == 200:
            result = response.json()
            markdown_content = filter_noise_from_elements(result)
            if not markdown_content:
                # elements 필터링 결과가 비어있으면 content.markdown 사용
                markdown_content = result.get("content", {}).get("markdown", "")
            if markdown_content:
                page_count = result.get("usage", {}).get("pages", None)
                save_markdown(filename, markdown_content, page_count)
            else:
                print("오류: Markdown 내용을 찾을 수 없습니다.")
        elif response.status_code == 413 or "too large" in response.text.lower():
            # 파일이 너무 큰 경우 비동기로 전환
            print(f"파일이 너무 큽니다. (응답: {response.status_code})")
            async_result = async_parse(filename)
            if async_result:
                markdown_content, page_count = async_result
                save_markdown(filename, markdown_content, page_count)
        else:
            print(f"동기 API 오류: {response.status_code} - {response.text}")
            # 다른 오류도 비동기로 재시도
            print("비동기 방식으로 재시도합니다...")
            async_result = async_parse(filename)
            if async_result:
                markdown_content, page_count = async_result
                save_markdown(filename, markdown_content, page_count)

    # 명령줄 인수로 파일 경로 받기
    if len(sys.argv) > 1:
        filename = sys.argv[1]
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
            return
        if not os.path.exists(filename):
            print(f"오류: 파일을 찾을 수 없습니다: {filename}")
            return
        process_file(filename)
    else:
        # 현재 디렉토리에서 지원되는 파일 찾기
        supported_files = sorted([f for f in os.listdir('.') if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS])
        if not supported_files:
            print("오류: 현재 디렉토리에 지원되는 파일이 없습니다.")
            print(f"지원 형식: {', '.join(SUPPORTED_EXTENSIONS)}")
            return
        if len(supported_files) == 1:
            process_file(supported_files[0])
        else:
            print(f"지원되는 파일 {len(supported_files)}개 발견:")
            for i, f in enumerate(supported_files, 1):
                print(f"  {i}. {f}")
            print()
            print("1) 하나씩 선택하여 변환")
            print("2) 모두 변환")
            choice = input("선택 (1/2): ").strip()
            print()

            if choice == "2":
                for i, f in enumerate(supported_files, 1):
                    print(f"[{i}/{len(supported_files)}] {f}")
                    try:
                        process_file(f)
                    except Exception as e:
                        print(f"오류 발생: {e}")
                    print()
            else:
                for i, f in enumerate(supported_files, 1):
                    yn = input(f"[{i}/{len(supported_files)}] {f} 변환? (Y/N): ").strip().upper()
                    if yn == "Y":
                        try:
                            process_file(f)
                        except Exception as e:
                            print(f"오류 발생: {e}")
                    else:
                        print("건너뜀.")
                    print()


if __name__ == "__main__":
    try:
        main()
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
