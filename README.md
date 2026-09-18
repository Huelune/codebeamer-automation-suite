# Codebeamer Automation Suite

Excel 기반 계층형 데이터를 Codebeamer Tracker Item으로 변환하고 업로드하는 자동화 도구입니다.

현재 기본 실행 경로는 `gui_main.py`이며, `cli_main.py`는 유지보수와 보조 실행에 사용합니다.
예전 `v2` 경로의 개선 사항은 원본 모듈에 반영되어 있고, GUI도 같은 업로드 파이프라인을 재사용합니다.

## 주요 기능

- Excel 계층 데이터를 tracker schema에 맞춰 매핑하고 parent-first 순서로 업로드합니다. create/update/upsert 모드를 지원합니다.
- `UserChoiceField`, `MemberField`, `TrackerItemChoiceField`, `TableField` 등 reference 계열 필드를 이름·정규식·payload 구조를 유지한 채 변환합니다.
- 트래커 작업공간에서 계층 조회, tracker 범위 검색, 단건 생성·수정·삭제, 페이지를 넘는 일괄 수정을 수행합니다.
- 현재 상태와 Baseline을 비교하고 계층·비교 결과를 Excel로 내보냅니다.
- 여러 연결 프로필, 비밀번호 저장 방식 선택, 오프라인 테스트 모드, 진단 로그와 API 모니터를 제공합니다.

기능별 상세 목록과 화면 단위 구현 범위는 [기능 현황](./docs/feature-status.md)에 있습니다.

## 권장 실행 명령

```bash
py -3 gui_main.py
```

CLI 보조 실행:

```bash
py -3 cli_main.py
```

## Windows Portable ZIP

배포된 GitHub Release 자산은 Windows 10/11 x64용 Portable ZIP입니다. 정식 버전의
`Codebeamer-Automation-Suite-vX.Y.Z-windows-x64.zip`을 받은 뒤 ZIP 전체를 새 폴더에 풀고
`CodebeamerAutomationSuite.exe`를 실행합니다. PyInstaller `onedir` 패키지이므로 EXE와 `_internal`
디렉터리를 분리하면 실행할 수 없습니다.

- `.xlsx`는 패키지에 포함된 의존성으로 지원합니다.
- `.xls` 처리는 Windows에 설치된 데스크톱 Microsoft Excel이 필요합니다.
- 현재 EXE는 코드 서명하지 않아 Windows SmartScreen 경고가 표시될 수 있습니다.
- Release의 `SHA256SUMS.txt`와 GitHub attestation을 확인한 파일만 실행합니다.
- PR·수동 실행 artifact는 7일간 보관되는 검증용 결과이며 GitHub Release가 아닙니다.

정식 태그는 `vX.Y.Z`, 릴리스 후보는 `vX.Y.Z-rc.N` 형식입니다. 태그 커밋이 `main` 이력에 포함되고
태그의 기본 버전이 `VERSION`과 일치할 때만 Release가 게시됩니다. 따라서 아직 병합되지 않은 PR은
배포에 포함되지 않습니다. 실제 `v0.1.0` 태그와 첫 Release는 파이프라인과 포함 기능을 `main`에 병합한
뒤 별도 배포 작업에서 생성합니다.

다운로드, 압축 해제, 체크섬·attestation 확인, 버전 변경과 태그 생성 절차 및 현재 검증 한계는
[Windows Portable ZIP 배포 가이드](./docs/windows-release.md)에 정리했습니다.

## GUI 오프라인 예시 데이터

GUI의 최상위 `설정 > 테스트 모드`에서 사용할 수 있는 샘플 세트는 `data/gui-offline-sample/` 에 있습니다.

- `offline_schema.json`
- `offline_tracker_configuration.json`
- `offline_tracker_items.json`
- `files/SAMPLE_MODULE_A_TC_001.xlsx`
- `files/SAMPLE_MODULE_B_TC_002.xlsx`
- `files/SAMPLE_LOOKUP_TC_003.xlsx`

사용 순서와 매핑 팁은 [data/gui-offline-sample/README.md](./data/gui-offline-sample/README.md)에 정리했습니다.

## 프로젝트 구조

- `gui_main.py`: 현재 기본 GUI 실행 경로
- `cli_main.py`: 유지보수와 보조 실행용 대화형 CLI
- `main.py`: 과거 엔트리 포인트, 현재 비권장
- `src/codebeamer_client.py`: Codebeamer REST API 클라이언트
- `src/api_monitor.py`: 최근 API 호출 메타데이터의 thread-safe 메모리 버퍼와 통계
- `src/diagnostics.py`: 세션 진단 이벤트, 진단 ID context, 민감정보 마스킹과 진단 ZIP 생성
- `src/gui/developer_tools_window.py`: 진단 로그와 재사용 API 모니터를 담는 확장 가능한 개발자 도구 창
- `src/excel_reader.py`: Excel 파일을 raw DataFrame으로 읽는 입력 계층
- `src/hierarchy_processor.py`: raw DataFrame을 merged/hierarchy/upload DataFrame으로 후처리
- `src/excel_processor.py`: 기존 import 호환용 통합 래퍼
- `src/cli_excel_utils.py`: 기존 CLI Excel helper import 호환 래퍼
- `src/upload_policy.py`: create/update/upsert 모드, 작업 범위, 루트 허용 여부, 공통 검증 상태 정책
- `src/mapping_service.py`: schema 해석용 façade
  내부 구현은 `src/mapping_reference.py`, `src/mapping_schema.py`, `src/mapping_option.py` 로 분리
- `src/wizard.py`: 업로드 오케스트레이션 façade
  내부 구현은 데이터, lookup, option 해석, create/update payload, payload cache, 실행 서비스로 분리
- `src/models/`: reference, field value, tracker item, user info, wizard state 모델
- `src/gui/`: PySide6 기반 앱 셸, 단계형 배치 GUI, 서비스 계층, upload worker
  `main_window.py`는 최상위 작업 영역을 전환하고 `batch_window.py`는 기존 9단계 마법사를 보존하며, 세부 구현은 `page_*`, `window_*`, `service_*` 모듈로 분리
- `data/gui-offline-sample/`: GUI 테스트 모드용 snapshot, 다중 Excel 샘플, 사용 안내
- `docs/`: 사용 가이드와 아키텍처 문서
- `output/`: 실행 결과 산출물 저장 디렉터리

호환 wrapper의 유지·제거 기준은 [호환 경로 감사](./docs/compatibility.md)에 정리되어 있습니다.

## 빠른 시작

1. 가상환경 생성과 의존성 설치

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --requirement requirements.txt
.venv\Scripts\python.exe -m pip install --requirement requirements-dev.txt
```

`requirements.txt`는 개발용 런타임 의존성이고, 릴리스 빌드와 같은 고정 버전으로 재현하려면
`requirements-release.txt`를 사용합니다. `requirements-dev.txt`는 lint와 type check 도구입니다.

2. `.env` 설정

```env
CODEBEAMER_BASE_URL=https://your-codebeamer-host/cb
CODEBEAMER_USERNAME=your_username
CODEBEAMER_PASSWORD=your_password
DEFAULT_PROJECT_ID=
DEFAULT_TRACKER_ID=
EXCEL_HEADER_ROW=1
EXCEL_SHEET_NAME=0
LOG_LEVEL=INFO
OUTPUT_DIR=output
```

3. 실행

```powershell
.venv\Scripts\python.exe gui_main.py
```

4. 검증

```powershell
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

`QT_QPA_PLATFORM=offscreen`을 설정하면 GUI 테스트가 창을 띄우지 않고 실행됩니다.
lint 규칙과 type check 범위는 `pyproject.toml`에 있고, CI의 `Lint and type check`,
`Regression tests` job이 같은 명령을 실행합니다.

## 현재 처리 흐름

1. Codebeamer에서 프로젝트, 트래커, schema 메타데이터를 조회합니다.
2. Excel 헤더와 schema를 비교해 컬럼 매핑을 확인합니다.
3. `multipleValues=true` 필드에 매핑된 Excel 컬럼을 자동으로 list 컬럼으로 선택합니다.
4. Excel reader가 raw dataframe과 `_excel_row`, `_summary_indent` 메타정보를 생성합니다.
5. hierarchy processor가 멀티라인 병합과 parent-child 계층 구성을 수행합니다.
6. 정적 option 필드는 reference payload로 변환합니다.
7. 사용자 선택 필드는 사용자 이름을 우선 조회하고, 숫자 입력일 때만 사용자 ID fallback 을 사용합니다.
8. `MemberField` 는 `USER/ROLE/GROUP` 후보를 이름으로 찾아 mixed reference 로 변환합니다.
9. `TrackerItemChoiceField` 는 configuration 정보와 관계없이 입력값에서 정규식으로 ID를 추출합니다. 이름·summary 조회는 비활성화되어 있습니다.
10. GUI 상단 데이터 설정이 켜져 있으면 파일별 루트 parent item payload 를 먼저 준비합니다.
11. row별 payload를 먼저 cache하고 preview와 upload가 같은 payload를 재사용합니다.
12. 업로드 시점에는 파일별 루트 parent item을 먼저 만들고, 이후 child row 의 `parentItemId` 를 `created_map[parent_row_id]` 또는 루트 item 기준으로 결정합니다.
13. `Status` 는 transition 기반 후처리로 옮겨야 하므로 현재 TODO 로 남겨두고 있습니다.
14. 실행 결과와 중간 dataframe, schema, payload cache, 검증 결과를 `output/`에 저장할 수 있습니다.

## 문서

전체 목록과 읽기 순서는 [문서 허브](./docs/index.md)에 있습니다. 자주 찾는 문서만 아래에 둡니다.

- [기능 현황](./docs/feature-status.md)
- [아키텍처](./docs/architecture.md)
- [GUI 사용 가이드](./docs/gui-plan.md)
- [CLI 사용 가이드](./docs/cli-guide.md)
- [Windows Portable ZIP 배포 가이드](./docs/windows-release.md)
- [트러블슈팅](./docs/troubleshooting.md)

## UML 렌더링

PlantUML이 준비된 환경에서는 아래 스크립트로 UML 이미지를 생성할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/render_uml.ps1
```

생성 대상:
- `docs/class-diagram.png`
- `docs/class-diagram.svg`
- `docs/upload-sequence.png`
- `docs/upload-sequence.svg`

## 참고 사항

- `TableField` 컬럼은 `TableFieldName.ColumnName` 형식의 Excel 헤더를 기준으로 감지합니다.
- 한 아이템에 여러 `TableField` 행을 넣을 때는 각 원본 행에 같은 `Upload Record Key`를 연속해서 입력합니다. 일반 필드는 그룹의 첫 행 값을 사용하며 다른 행의 값이 다르면 공백 차이도 업로드 전에 오류로 차단합니다.
- 정적 option이 없는 일반 reference 필드는 아직 자동 lookup을 모두 지원하지 않습니다.
- 사용자 관련 필드는 이름을 우선 사용하고, 숫자 입력일 때만 사용자 ID fallback 을 사용합니다.
- `MemberField` 의 `ROLE` 은 field permission matrix, `GROUP` 은 `/v3/users/groups` 전체 목록에서 이름으로 찾습니다.
- `TrackerItemChoiceField` 는 tracker configuration 의 `fields` 목록에서 `referenceId == schema.field_id` 로 매칭 정보를 확인할 수 있지만, 업로드·검증에서는 항상 입력값의 ID 추출만 사용합니다.
- 위 source tracker를 찾지 못하거나 offline snapshot 만 사용하는 경우에는 기본 정규식 ID 추출 방식으로 동작합니다.
- 테스트 모드에서는 실제 업로드를 막고 Dry Run만 허용합니다.
- `Status` 는 workflow transition 제약을 반영해야 하므로 현재 TODO 입니다.
- `save_state()`는 `payload_df.csv`, `payload_preview.jsonl`을 포함해 payload cache 상태도 함께 저장합니다.
