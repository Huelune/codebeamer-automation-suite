# GUI 오류 처리 감사

## 목적

PySide6 signal/slot에서 처리되지 않은 Python 예외는 기본적으로 콘솔에 traceback만 남을 수 있습니다.
이 문서는 GUI 오류가 사용자에게 전달되는 경로와 의도적으로 인라인 상태만 사용하는 경로를 구분합니다.

## 전수 점검 범위

- `src/gui`의 signal `connect`와 직접 호출되는 이벤트 핸들러
- `BackgroundTask`, `UploadWorker`, `BulkUpdateWorker` 생성·시작·완료·실패 경로
- 트래커 조회·쓰기, Baseline 비교와 Excel 내보내기
- 설정 검증·저장·가져오기·내보내기
- 배치 preset, Excel 미리보기, 매핑·검증·업로드
- 실행 기록, API 모니터와 창 종료 시 보조 저장

## 오류 표시 계약

| 오류 종류 | 사용자 표시 | 콘솔 | 상태 정리 |
| --- | --- | --- | --- |
| 입력 누락·잘못된 조건 | 관련 입력 가까이의 상태/검증 문구 | 불필요 | 입력 상태 유지 |
| 트래커 조회·쓰기·Baseline Excel 저장·배치 파일 작업 실패 | 작업 화면 상태와 오류 다이얼로그 | 서비스 정책에 따름 | busy/progress 해제 |
| worker 내부 실패 | worker의 실패 signal을 기존 화면 실패 처리기로 전달 | 불필요 | 버튼·진행 창 복구 |
| Qt 슬롯의 처리되지 않은 예외 | `예상하지 못한 오류` 다이얼로그 | 전체 traceback 유지 | 가능한 현재 화면 유지 |
| Python thread의 처리되지 않은 예외 | GUI thread로 전달한 오류 다이얼로그 | 전체 traceback 유지 | thread 종료 |
| 사용자 취소 | 취소 또는 중단 상태 | 불필요 | 버튼·진행 창 복구 |
| 창 위치·API 모니터 같은 보조 상태 실패 | 작업을 막지 않는 상태 또는 fallback | 필요 시 기록 | 주요 작업 계속 |

## 전역 예외 안전망

`src/gui/error_reporting.py`는 `QApplication` 생성 직후 설치합니다.

- `sys.excepthook`으로 Qt slot의 처리되지 않은 예외를 수신합니다.
- `threading.excepthook`으로 일반 Python thread의 처리되지 않은 예외를 수신합니다.
- 기존 hook도 호출해 개발자용 traceback을 없애지 않습니다.
- 사용자 알림에는 예외 종류와 제한된 메시지만 표시하고 password, token, authorization, cookie, session 형태의 값을 마스킹합니다.
- 오류마다 짧은 진단 ID를 표시하고, 같은 ID의 구조화 이벤트를 세션 진단 로그에 남깁니다.
- 진단 traceback은 locals와 source line을 제외한 파일·함수·행 번호만 보관합니다.
- worker thread에서 발생한 알림은 queued signal로 GUI thread에 전달합니다.
- 같은 제목과 메시지는 짧은 시간 안에 한 번만 표시합니다.
- 오류 알림 자체가 실패해도 다시 예외 hook으로 진입하지 않습니다.

## 개별 보완 사항

- Baseline 내보내기 필드 목록은 모든 상태 widget을 만든 뒤 `itemChanged`를 연결합니다.
- Baseline 내보내기의 전체 선택·전체 해제는 필드 검색으로 숨겨진 항목을 포함한 전체 목록에 적용합니다.
- 트래커 작업공간의 서비스 실패는 기존 상단 상태와 최상위 오류 알림을 함께 사용합니다.
- Baseline 목록·전체 비교·하위 조회·Excel 저장 실패도 같은 알림 경로를 사용합니다.
- Baseline Excel은 임시 파일 저장이 끝난 뒤 대상 파일을 교체하므로 저장 실패 시 기존 파일과 불완전한 임시 파일을 구분해 정리합니다.
- 배치 업로드와 일괄 수정 worker가 시작되지 못하면 비활성화한 버튼과 진행 창을 복구합니다.
- 동기식 busy helper도 worker 시작 실패를 포함해 항상 overlay를 해제합니다.
- 범용 트래커 background task 시작 실패는 지정된 failure callback으로 전달합니다.

## 의도적으로 모달 알림을 사용하지 않는 경로

- 빈 필수 입력, 잘못된 검색 조건처럼 사용자가 같은 화면에서 바로 고칠 수 있는 검증 오류
- 사용자 취소
- API 모니터의 테스트 모드 판정 실패처럼 안전한 기본값이 있는 보조 표시
- 창 종료 시 창 위치 저장 실패처럼 주요 작업 결과와 무관한 best-effort 설정

이 경로는 콘솔에만 예외가 노출되는 누락이 아니라 명시적인 fallback입니다.

## 예외 범위 기준

`except Exception`이 넓어서 문제인 경우와 넓어야 하는 경우를 구분합니다.

### 좁힌 경우

발생 가능한 예외를 코드에서 셀 수 있으면 좁힙니다.

| 대상 | 좁힌 예외 |
| --- | --- |
| `int()`, `float()` 값 변환 | `(TypeError, ValueError)` |
| 파일 읽기 + `json.loads()` | `(OSError, ValueError)` |
| 예외에 딸려 온 응답의 `.json()` | `(AttributeError, ValueError)` |
| `pd.isna()` 결측 판정 | `(TypeError, ValueError)` |

`json.JSONDecodeError`와 `UnicodeDecodeError`는 `ValueError` 하위라 별도로 적지 않습니다.
응답 객체는 형태를 보장할 수 없어 `AttributeError`를 함께 받습니다.
`pd.isna()`는 배열을 돌려줄 수 있고 그때 `bool()`이 `ValueError`를 냅니다.

### 넓게 두는 경우

아래는 예외 형태를 알 수 없거나, 좁히면 계약이 깨집니다. 좁히지 말고 근거 주석을 남깁니다.

- **전역 예외 hook 내부** (`error_reporting.py`): 여기서 다시 예외가 나면 원래 예외 보고를 잃습니다.
  이전 hook은 남의 코드일 수 있습니다.
- **worker 경계**: 모든 예외를 실패 signal로 바꿔 사용자에게 알려야 합니다.
- **주입된 콜백 호출** (`activity_recorder`, `settings_provider`, `query_executor` 등): 구현을 알 수 없습니다.
- **xlwings COM 정리** (`workbook.close()`, `app.quit()`): 데스크톱 Excel을 COM으로 다루므로
  실패가 `pywintypes.com_error`, `OSError` 등 여러 형태로 올라옵니다.
- **duck typing 호출** (`value.to_dict()`, `value.item()`): 대상 객체가 무엇인지 보장되지 않습니다.
- **best-effort 보조 저장** (창 위치, 실행 기록): 실패해도 주요 작업을 막지 않습니다.

## 회귀 검증

- 실제 `QPushButton.clicked` slot에서 예외를 발생시켜 기존 hook 기록과 사용자 알림을 모두 확인합니다.
- 일반 Python thread 예외가 GUI 알림으로 전달되는지 확인합니다.
- hook 중복 설치, 원래 hook 복원, 민감값 마스킹과 메시지 길이 제한을 확인합니다.
- 필드 선택 대화상자 초기화와 트래커 background task 시작 실패를 별도 테스트합니다.
- 전체 GUI 및 비GUI unittest를 함께 실행합니다.
