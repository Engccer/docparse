"""LlamaParse v2 파서 (docparse).

  python llamaparse_parse.py [--tier T] [--lang L] [--instructions FILE] [--credits] "<파일>"
  → <파일>_llamaparse.md

실패 계약(2026-08-31): 응답에 markdown_full·text_full이 모두 비면 출력 파일을 만들지
않고 종료 코드 1(종전에는 "(내용 없음)" 7글자 파일이 완료본으로 남았다). 실행 시작
시 같은 이름의 이전 출력을 지운다.
"""
import os
import sys
import traceback
import argparse


def main():
    """반환값이 종료 코드다(0 성공 / 1 실패)."""
    # 지원 형식 (LlamaParse는 130+ 포맷 지원)
    SUPPORTED_EXTS = {
        '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif',
        '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls',
        '.html', '.htm', '.txt', '.csv', '.rtf', '.epub',
    }

    TIERS = ['fast', 'cost_effective', 'agentic', 'agentic_plus']

    parser = argparse.ArgumentParser(
        description="LlamaParse v2: 문서를 Markdown으로 변환합니다.",
        epilog="환경변수: LLAMAPARSE_API_KEY. 기본 옵션: 연속 표 병합, 링크 주석. "
               "티어별 크레딧/페이지: fast(1), cost_effective(3), agentic(10), agentic_plus(45).",
        allow_abbrev=False,
    )
    parser.add_argument("files", nargs="*", help="입력 파일 (생략 시 현재 폴더에서 자동 탐색)")
    parser.add_argument("--tier", choices=TIERS, default="agentic", help="파싱 티어 (기본: agentic)")
    parser.add_argument("--lang", default="ko", help="OCR 언어 코드 (기본: ko)")
    parser.add_argument("--instructions", metavar="FILE", help="UTF-8 파싱 지시 파일 (agentic·agentic_plus에서 적용)")
    parser.add_argument("--credits", action="store_true", help="남은 크레딧 및 갱신일 확인")
    args = parser.parse_intermixed_args()
    tier, language, check_credits = args.tier, args.lang, args.credits
    files_to_process = args.files
    if not language.strip():
        parser.error("--lang에는 비어 있지 않은 언어 코드를 지정해야 합니다")

    # 명시한 입력 전체를 검사한 뒤에만 크레딧 조회·파싱을 시작한다.
    for input_file in files_to_process:
        ext = os.path.splitext(input_file)[1].lower()
        if ext not in SUPPORTED_EXTS:
            print(f"오류: 지원하지 않는 파일 형식입니다: {ext}")
            print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXTS))}")
            return 1
        if not os.path.isfile(input_file):
            print(f"오류: 파일을 찾을 수 없습니다: {input_file}")
            return 1

    custom_prompt = None
    if args.instructions is not None:
        if not os.path.isfile(args.instructions):
            print(f"오류: --instructions 파일을 찾을 수 없습니다: {args.instructions}")
            return 1
        with open(args.instructions, "r", encoding="utf-8") as f:
            custom_prompt = f.read().strip()
        if not custom_prompt:
            print(f"오류: --instructions 파일이 비어 있습니다: {args.instructions}")
            return 1

    supported_files = []
    if not files_to_process and not check_credits:
        supported_files = sorted([
            f for f in os.listdir('.')
            if os.path.isfile(f) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
        ])
        if not supported_files:
            print("오류: 현재 디렉토리에 지원되는 파일이 없습니다.")
            print(f"지원 형식: {', '.join(sorted(SUPPORTED_EXTS))}")
            return 1

    api_key = os.environ.get("LLAMAPARSE_API_KEY")
    if not api_key:
        print("오류: LLAMAPARSE_API_KEY 환경 변수가 설정되지 않았습니다.")
        print('설정 명령: setx LLAMAPARSE_API_KEY "your-api-key"')
        return 1

    try:
        from llama_cloud import Client
    except ImportError as e:
        print("오류: llama-cloud 패키지를 찾을 수 없습니다.")
        print("설치 명령: pip install llama-cloud")
        print(f"상세: {e}")
        return 1

    client = Client(api_key=api_key)

    def get_output_filename(input_file):
        """입력 파일 경로를 기반으로 출력 파일 경로 생성"""
        dir_path = os.path.dirname(input_file)
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_name = f"{base_name}_llamaparse.md"
        if dir_path:
            return os.path.join(dir_path, output_name)
        return output_name

    def clear_stale_output(output_file):
        if os.path.exists(output_file):
            os.remove(output_file)
            print(f"기존 출력 제거: {output_file}")

    def estimate_credits(input_file, tier):
        """파일 페이지 수 추정 및 크레딧 계산"""
        credits_per_page = {'fast': 1, 'cost_effective': 3, 'agentic': 10, 'agentic_plus': 45}
        try:
            import fitz
            doc = fitz.open(input_file)
            pages = len(doc)
            doc.close()
        except Exception:
            pages = None
        if pages:
            cost = pages * credits_per_page.get(tier, 10)
            return pages, cost
        return None, None

    def process_file(input_file, tier='agentic', language='ko', custom_prompt=None):
        """단일 파일 문서 파싱 (LlamaParse API v2). 출력 파일을 만들었으면 True."""
        print(f"입력 파일: {input_file}")
        output_file = get_output_filename(input_file)
        clear_stale_output(output_file)

        # 파일 크기 확인
        file_size = os.path.getsize(input_file)
        file_size_mb = file_size / (1024 * 1024)
        print(f"파일 크기: {file_size_mb:.1f} MB")
        print(f"파싱 티어: {tier} / 언어: {language}")
        if custom_prompt:
            preview = custom_prompt.replace('\n', ' ')[:80]
            print(f"커스텀 지시: {preview}...")

        # 크레딧 추정
        pages, cost = estimate_credits(input_file, tier)
        if pages:
            print(f"페이지 수: {pages} / 예상 크레딧: {cost}")

        print("변환 중...")

        # v2 최적 옵션 구성
        processing_options = {
            'ocr_parameters': {
                'languages': [language]
            }
        }
        output_options = {
            'markdown': {
                'annotate_links': True,
                'tables': {
                    'output_tables_as_markdown': True,
                    'merge_continued_tables': True,
                }
            }
        }

        # 커스텀 지시 (agentic·agentic_plus 티어에서만 유효)
        parse_kwargs = {}
        if custom_prompt:
            if tier in ('agentic', 'agentic_plus'):
                parse_kwargs['agentic_options'] = {'custom_prompt': custom_prompt}
            else:
                print(f"[경고] --instructions는 agentic/agentic_plus 티어에서만 적용됩니다. 현재 티어({tier})에서는 무시됩니다.")

        # 파일 업로드 및 파싱 (동기, 완료까지 폴링)
        with open(input_file, "rb") as f:
            result = client.parsing.parse(
                tier=tier,
                version="latest",
                upload_file=f,
                expand=["markdown_full", "text_full"],
                verbose=True,
                processing_options=processing_options,
                output_options=output_options,
                **parse_kwargs,
            )

        # 결과 추출: 둘 다 비면 실패(빈 자리표시자 파일을 완료본으로 남기지 않는다)
        markdown_content = getattr(result, 'markdown_full', None) or getattr(result, 'text_full', None)
        if not markdown_content or not markdown_content.strip():
            status = getattr(result, 'status', None)
            print(f"오류: 응답에 내용이 없습니다(status={status}). 출력 파일을 만들지 않았습니다.")
            return False

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        print(f"변환 완료! {len(markdown_content)}글자가 저장되었습니다.")
        print(f"출력 파일: {output_file}")
        return True

    if check_credits:
        try:
            import httpx
            headers = {'Authorization': f'Bearer {api_key}'}
            r = httpx.get('https://api.cloud.llamaindex.ai/api/v1/projects', headers=headers, timeout=10)
            org_id = r.json()[0]['organization_id']
            r = httpx.get(f'https://api.cloud.llamaindex.ai/api/v1/organizations/{org_id}/usage', headers=headers, timeout=10)
            data = r.json()
            plan = data['plan']
            usage = data['usage']
            print(f"플랜: {plan['name']}")
            print(f"빌링 기간: {plan['current_billing_period']['start_date'][:10]} ~ {plan['current_billing_period']['end_date'][:10]}")
            for grant in usage.get('active_free_credits_usage', []):
                print(f"크레딧: {grant['remaining_balance']:,} / {grant['starting_balance']:,} (갱신: {grant['expires_at'][:10]})")
        except Exception as e:
            print(f"크레딧 조회 실패: {e}")
            if not files_to_process:
                return 1
        if not files_to_process:
            return 0

    if files_to_process:
        all_ok = True
        for input_file in files_to_process:
            all_ok = process_file(input_file, tier, language, custom_prompt) and all_ok
        return 0 if all_ok else 1

    if len(supported_files) == 1:
        return 0 if process_file(supported_files[0], tier, language, custom_prompt) else 1

    print(f"지원되는 파일 {len(supported_files)}개 발견:")
    for idx, f in enumerate(supported_files, 1):
        print(f"  {idx}. {f}")
    print()
    print("1) 하나씩 선택하여 변환")
    print("2) 모두 변환")
    choice = input("선택 (1/2): ").strip()
    print()

    all_ok = True
    for idx, f in enumerate(supported_files, 1):
        if choice != "2":
            yn = input(f"[{idx}/{len(supported_files)}] {f} 변환? (Y/N): ").strip().upper()
            if yn != "Y":
                print("건너뜀.")
                print()
                continue
        else:
            print(f"[{idx}/{len(supported_files)}] {f}")
        try:
            all_ok = process_file(f, tier, language, custom_prompt) and all_ok
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
