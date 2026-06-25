import os
import sys
import json
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
        api_key = os.environ["COREPIN_API_KEY"]
    except KeyError:
        print("오류: COREPIN_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("설정 명령: export COREPIN_API_KEY=\"sk_live_...\"  (Windows: setx COREPIN_API_KEY \"sk_live_...\")")
        return

    BASE_URL = "https://api.corepin.ai"

    # Corepin 통합 문서 파서 지원 형식 (HWP/HWPX 포함 국내 최다 18종 중 문서 파싱 대상)
    SUPPORTED_EXTENSIONS = [
        '.hwp', '.hwpx', '.hwpml', '.xls',
        '.docx', '.pptx', '.xlsx',
        '.pdf',
        '.jpg', '.jpeg', '.png', '.heic', '.tif', '.tiff', '.webp', '.bmp',
        '.html', '.epub', '.rtf', '.csv', '.tsv', '.md', '.txt',
    ]

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_corepin.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def save_markdown(filename, markdown_content, meta=None):
        output_file = get_output_filename(filename)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        page_count = (meta or {}).get("page_count")
        if page_count:
            print(f"변환 완료! {page_count}페이지, {len(markdown_content)}글자가 저장되었습니다.")
        else:
            print(f"변환 완료! {len(markdown_content)}글자가 저장되었습니다.")
        # 스캔 PDF 자동 OCR fallback 등 서버 알림 노출
        for warn in (meta or {}).get("warnings", []) or []:
            print(f"알림: {warn}")
        if (meta or {}).get("needed_ocr"):
            print(f"OCR fallback 사용: {meta.get('ocr_pages_used', 0)}페이지")
        print(f"출력 파일: {output_file}")

    def parse_error(response):
        """Corepin 공통 에러 envelope 파싱"""
        try:
            body = response.json()
            err = body.get("error", {})
            return f"{err.get('code', response.status_code)} - {err.get('message', response.text)} (request_id: {err.get('request_id', 'N/A')})"
        except (ValueError, json.JSONDecodeError):
            return f"{response.status_code} - {response.text}"

    def process_file(filename):
        """단일 파일 문서 파싱 (/v1/doc/parse, output_format=markdown)"""
        print(f"입력 파일: {filename}")
        print("변환 중... (Corepin 통합 문서 파서, ocr_fallback ON)")

        url = f"{BASE_URL}/v1/doc/parse"
        headers = {"Authorization": f"Bearer {api_key}"}
        with open(filename, "rb") as fh:
            files = {"file": fh}
            data = {
                "output_format": "markdown",
                "ocr_fallback": "true",  # 스캔 PDF 자동 감지 시 한국어 OCR
            }
            response = requests.post(url, headers=headers, files=files, data=data, timeout=120)

        if response.status_code == 200:
            result = response.json()
            # 표 감지 시 자동 정밀 모드 (추가 비용 없음)
            if result.get("auto_escalated"):
                print("표 감지 → 자동 정밀 모드 적용됨")
            markdown_content = result.get("markdown") or result.get("text", "")
            if markdown_content:
                save_markdown(filename, markdown_content, result.get("meta"))
            else:
                print("오류: Markdown 내용을 찾을 수 없습니다.")
                print(f"응답: {result}")
        else:
            print(f"Corepin API 오류: {parse_error(response)}")

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
