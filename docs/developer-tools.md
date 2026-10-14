# 개발자 도구와 진단 패키지

## 목적

`설정 > 개발자 > 개발자 도구 열기`는 일반 사용자 화면에 개발 세부 정보를
노출하지 않으면서 오류와 API 호출 상태를 확인하는 별도 non-modal 창입니다.

- `진단 로그`: 논리 작업과 오류의 안전한 메타데이터를 한 세션에서 확인합니다.
- `API 모니터`: 기존 HTTP 호출 상태·지연 통계를 같은 창에서 확인합니다.
- `Excel 도구`: 원본을 덮어쓰지 않고 파일 구조를 검사하거나 값 전용 파일로 변환합니다.
- `Payload`: 현재 배치 검증 세션에서 만든 payload를 행별로 확인합니다.
- `스키마·캐시`: 현재 트래커 필드 지원 현황·스키마 차이와 조회 캐시 개수를 확인합니다.
- `읽기 전용 Query`: 고정된 `/v3/items/query` 요청만 미리 보고 실행합니다.

`실행 기록`은 쓰기·배치 작업의 영속 최종 결과이고, 배치 화면의 실시간 로그는 현재
업로드 행별 상세입니다. 개발자 도구는 두 화면을 복제하지 않으며, 서버 원본 오류
응답이나 Excel 셀 값을 수집하지 않습니다.

Excel·Payload·Schema 탭은 사용자가 명시적으로 현재 파일 또는 배치 세션을 선택했을
때만 값을 화면에 읽어 옵니다. 이 값은 진단 이벤트, 진단 ZIP 또는 영속 로그로
복제하지 않습니다.

## Excel 검사와 안전 변환

`Excel 도구`는 다음 파일을 지원합니다.

| 입력 | 검사 | 값 전용 `.xlsx` | 값 전용 `.csv` | 제한 |
| --- | --- | --- | --- | --- |
| `.xlsx` | 지원 | 지원 | 지원 | 수식은 저장된 계산 결과가 있어야 함 |
| `.xlsm` | 지원 | 지원 | 지원 | 출력에서 매크로를 보존하지 않음 |
| `.xls` | 조건부 | 조건부 | 조건부 | Microsoft Excel과 xlwings 필요 |
| `.csv` | 지원 | 지원 | 지원 | UTF-8/CP949와 한 글자 구분자 선택 |

`.xltx`와 `.xltm`은 지원하지 않습니다. 검사 결과는 빈·중복 헤더, Summary 누락,
TableField 형태 헤더, 병합·숨김 영역, 수식 오류, XML 제어문자와 Excel 셀 길이
제한을 표시합니다. 변환은 원본과 같은 경로를 거부하고 임시 출력 검증 후 대상
파일을 교체합니다. 수식으로 해석될 수 있는 텍스트는 문자열로 보호하며, 긴 값을
임의로 자르지 않고 작업을 중단합니다. 날짜·시간·기간은 Excel 셀 타입을 유지하며,
선행 공백·탭·개행 뒤의 수식 시작 문자도 CSV에서 문자열로 보호합니다. `.xls`는
업로드 전처리를 거치지 않고 사용 영역의 빈 행·열과 지정한 헤더 위치를 보존합니다.

## Payload·스키마·캐시·Query

- Payload 탭은 현재 검증 결과의 파일·행 ID, 상태, 작업과 대상 ID를 표시하고 선택
  행의 JSON을 보기 좋게 정렬합니다. 다중 파일의 같은 행 ID는 파일과 함께 구분하며,
  credential 계열 키와 오류 문자열의 인증값·URL은 표시 전에 제거합니다. 대규모
  세션은 UI 응답성을 위해 앞의 500행만 표에 표시합니다.
- 스키마 탭은 필드 유형, 필수 여부, 다중값 여부, 지원 여부와 미지원 사유를
  표시합니다. 현재 snapshot을 세션 기준으로 잡은 뒤 다시 불러온 schema와
  추가·삭제·변경을 비교할 수 있습니다.
- 캐시 탭은 사용자·멤버·그룹·역할·Tracker Item·기존 아이템 조회 캐시의 개수만
  보여 줍니다. 키와 값은 표시하지 않으며, 선택 삭제 전에 재조회 발생 가능성을
  경고합니다.
- Query 탭은 트래커 ID, 선택적 Baseline ID, CbQL과 페이지 크기만 받아 실제
  `GET /v3/items/query` query parameter를 미리 보여 줍니다.
  임의 endpoint와 쓰기 method는 입력할 수 없고 현재 트래커 범위를 강제로
  포함하는 `TrackerQuery` 검증을 통과한 요청만 실행합니다.

## 진단 로그

진단 이벤트는 다음 정보만 포함합니다.

- 시각, 수준, 출처와 제어된 이벤트 종류
- 논리 작업을 연결하는 무작위 진단 ID
- 제어된 메시지, 건수와 소요 시간 같은 제한된 상세 정보
- 미처리 예외의 종류와 파일·함수·행 번호만 포함한 stack frame

세션 메모리의 고정 길이 버퍼에 최근 최대 2,000건을 보관하며 앱을 종료하면
사라집니다. 표는 최신 최대 500건만 렌더링하며 전체 2,000건은 필터와 진단 ZIP
snapshot에 유지합니다. `화면 업데이트 일시정지`는 표만 멈추고 수집을 계속합니다.
`세션 로그 지우기`는 실행 기록이나 API 모니터 행을 지우지 않습니다.

Python `ContextVar`는 새 worker thread에 자동으로 전달된다고 가정하지 않습니다.
공통 background·업로드·일괄 수정 worker는 실행 시작 시 진단 ID와 operation context를
만들고 완료·실패 이벤트를 남깁니다. Tracker와 Baseline 작업은 제출 종류에 맞는
출처로 구분하며 같은 context 안의 API 재시도는 모두 같은 진단 ID를 사용합니다.

## 오류 알림

Qt slot 또는 Python thread의 미처리 예외는 다음 세 경로로 전달됩니다.

1. 기존 Python exception hook을 호출해 콘솔 traceback을 유지합니다.
2. 사용자에게 민감값이 제거된 오류와 짧은 진단 ID를 표시합니다.
3. 개발자 도구에는 locals와 source line을 제외한 구조화 이벤트를 남깁니다.

진단 observer 또는 오류 다이얼로그가 실패해도 다시 전역 hook으로 진입하지 않습니다.
같은 오류의 짧은 시간 내 모달 중복 억제도 유지합니다.

## 진단 패키지

`진단 패키지 내보내기`는 현재 snapshot을 ZIP으로 저장합니다.

| 파일 | 내용 |
| --- | --- |
| `manifest.json` | 형식 버전, 생성 시각, 건수, redaction 정책과 파일 checksum |
| `diagnostics.ndjson` | 메시지 원문을 일반화하고 허용된 건수만 남긴 세션 진단 메타데이터 |
| `api-events.ndjson` | 정규화된 API 호출 메타데이터 |
| `activity-summary.json` | 실행 기록의 작업 종류·결과와 허용된 건수 요약 |
| `environment.json` | OS·Python과 지정된 주요 의존성 버전 |
| `README.txt` | 포함·제외 범위 안내 |

대상 경로 옆 임시 ZIP을 먼저 완성한 후 교체합니다. 저장 실패 시 기존 파일은
보존하고 불완전한 임시 파일은 제거합니다. 내보내기 snapshot을 먼저 확정하므로
내보내기 완료 로그가 자신이 생성한 ZIP에 재귀적으로 포함되지 않습니다.

## 보안 경계

다음 정보는 진단 이벤트 모델과 ZIP에 포함하지 않습니다.

- Base URL, username, password, token, cookie, session과 인증 header
- HTTP 요청·응답 body, query 값과 서버 원본 오류 문자열
- Excel 파일명·절대 경로·시트 또는 셀 값
- 프로젝트·트래커·아이템 이름과 field payload
- Baseline 기준·비교 필드 값
- 원본 GUI 설정, credential과 bulk 실행 파일

민감 키, Basic/Bearer 값, URL, 이메일과 사용자 경로는 저장 전에 마스킹합니다.
API 경로의 숫자 ID, UUID와 긴 hex 식별자는 `{id}`로 바꾸고 query는 제거합니다.
첨부·그림 다운로드 경로는 서버 context 경로와 첨부 파일 이름을 빼고 `/v3` 이후나 `/displayDocument/{name}`처럼
정해 둔 모양으로만 남깁니다.

## 구현 경계

- `src/diagnostics.py`: Qt 독립 thread-safe 버퍼, operation context, 마스킹과 ZIP 생성
- `src/gui/developer_tools_window.py`: 진단 로그와 API 모니터를 담는 확장 가능한 탭 창
- `src/gui/developer_tool_panels.py`: Excel, Payload, Schema·Cache와 읽기 전용 Query 화면
- `src/gui/developer_excel_tools.py`: Excel 검사와 원자적 값 전용 변환
- `src/gui/developer_data_tools.py`: payload 마스킹, schema diff와 cache 통계·삭제 정책
- `src/gui/api_monitor_window.py`: 재사용 가능한 `ApiMonitorPanel`과 기존 window wrapper
- `src/gui/error_reporting.py`: 진단 ID를 포함한 전역 오류 observer와 기존 hook 유지
- `src/gui/main_window.py`: 창 singleton, 설정 적용 진단과 앱 생명주기 연결

추가 개발자 도구는 독립 `QWidget`으로 구현한 후
`DeveloperToolsWindow.add_tool_tab(widget, label)`로 연결합니다. 이 구조는 각 도구가
진단 서비스나 API 모니터 구현을 복제하지 않도록 합니다.
