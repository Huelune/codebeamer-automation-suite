# 아이템 활동 이력 설계: Baseline 기준 변경량, 유형별 보기, Excel 내보내기

- 작성일: 2026-10-13
- 상태: 검토 대기
- 브랜치: `feat/changelog-baseline-comparison-export-c06da1`
- 범위: 아이템 한 건. 여러 아이템을 골라 내보내는 기능(B)은 이 문서 끝의 후속 계획으로만 다룬다.

## 1. 배경과 목표

Baseline 비교 탭의 `변경 이력` 탭과 상세 창의 이력 탭은 버전별 필드 변경만 보여 주고, 건수 외에는
"어떤 Baseline 이후 얼마나 바뀌었는지"를 요약하지 않는다. 내보내기도 없다.

이 설계로 사용자가 할 수 있어야 하는 것:

1. 기준 Baseline을 골라 그 이후 이력만 본다.
2. 이력 유형(필드 변경, 댓글, 첨부)을 골라 본다.
3. 필드별로 구간 처음 값, 구간 마지막 값, 변경 횟수, 마지막 수정자를 한눈에 본다.
4. 지금 보는 범위를 그대로 Excel로 내보낸다.

성공 기준: 비교 탭과 상세 창 어느 쪽에서든 같은 조작으로 같은 결과를 얻고, 테스트 모드에서도
전체 흐름을 확인할 수 있으며, 내보낸 Excel만으로 화면과 같은 내용을 읽을 수 있다.

## 2. 범위

포함:

- Baseline 비교 탭의 `변경 이력` 탭과 상세 창(현재·Baseline)의 `변경 이력` 탭 양쪽.
- 유형: 필드 변경, 댓글, 첨부. 관계는 비활성 선택지로 두고 이유를 보인다.
- 기준 Baseline 선택, 유형 선택, 필드별 요약 표, 시간순 트리, 상태줄 건수, Excel 내보내기.
- 테스트 모드 샘플 데이터에 첨부 항목 추가.
- 실서버 응답 구조 확인 스크립트와 `todo.md` 안내 절.

제외:

- 여러 아이템 선택 내보내기(B). 후속 계획 절 참고.
- 관계 변경 이력. 관계 API 응답에 시각이 없다.
- 텍스트 필드의 글자 수 증감 같은 양적 지표.
- Baseline 시점의 댓글·첨부 조회. 기존 차단 규칙을 유지한다.

## 3. 용어

- 활동 항목: 시각 순으로 늘어놓는 이력 한 건. 필드 변경 버전 하나, 댓글 하나, 첨부 하나가 각각 한 항목이다.
- 유형: 활동 항목의 종류. `필드 변경`, `댓글`, `첨부`.
- 구간: 화면과 내보내기에 넣을 항목을 고르는 시간·버전 범위. 기준 Baseline 선택이 정한다.
- 기준 Baseline: 구간의 시작점이 되는 Baseline. 그 생성 시각 이후만 남긴다.
- 비교 시점 사이: 비교 탭에서만 있는 구간. 비교 탭이 고른 두 시점 사이다.

## 4. 데이터 출처와 계약

| 유형 | 출처 | 서비스 | 시각 | 사용자 | 비고 |
| --- | --- | --- | --- | --- | --- |
| 필드 변경 | `GET /v3/items/{id}/history` | `TrackerItemContextService.load_history` | `modifiedAt` | `modifiedBy` | `versions[].changes[]`에 필드·이전 값·새 값 |
| 댓글 | `GET /v3/items/{id}/comments` | `TrackerCommentService.load_comments` | `createdAt`, `modifiedAt` | `createdBy` | 댓글 첨부 목록 포함 |
| 첨부 | `GET /v3/items/{id}/attachments` 또는 아이템 payload의 `attachments` | `TrackerContentService.load_attachments` | `modifiedAt`만 확인됨 | 미확인 | 현재 목록만. 지워진 첨부는 없음 |
| 관계 | `GET /v3/items/{id}/relations` | `TrackerItemContextService.load_relations` | 없음 | 없음 | 이력에 올릴 수 없어 미지원 |

미확인 사항은 4절 끝의 실서버 확인으로 메운다.

- 이력 응답 `changes[].type`에 `TrackerItemChange` 외 값이 있는지. 있으면 댓글·첨부·관계 사건이 이력 API 한 번으로 올 수 있다.
- 첨부 payload에 `createdAt`·`createdBy`가 있는지. 있으면 첨부 항목의 시각·사용자로 쓴다.

실서버 확인은 사용자가 자기 PC에서 돌린다. `scripts/inspect_item_activity_contract.py`가 아이템 ID 하나를 받아
네 API를 호출하고, 응답의 키 이름, `type` 값, 건수만 한 화면에 찍는다. 값(필드 이름, 본문, 파일명, 사용자)은
찍지 않는다. 접속 정보는 실행 중 입력받고 저장하지 않는다. 출력 규칙은 `secret`이 든 가짜 payload로 테스트한다.
`todo.md` 1절에 실행 명령, 확인할 것, 돌려줄 것을 적는다.

확인 결과에 따른 후속:

- 이력 API에 다른 사건 유형이 있으면: 그 유형을 활동 항목으로 바꾸는 변환을 추가하고, 같은 사건이 댓글·첨부 API와
  겹치면 이력 API 쪽을 쓴다. 이 문서의 조회 흐름은 바뀌지 않는다.
- 첨부에 `createdAt`·`createdBy`가 있으면: `AttachmentSummary`에 두 값을 더하고 첨부 항목의 시각·사용자로 쓴다.

## 5. 모델

새 모듈 `src/gui/item_activity.py`. Qt에 기대지 않는 순수 모델과 함수만 둔다.

```python
class ItemActivityKind(str, Enum):
    FIELD_CHANGE = "field_change"
    COMMENT = "comment"
    ATTACHMENT = "attachment"

@dataclass(frozen=True)
class ItemActivityEntry:
    kind: ItemActivityKind
    at: str                  # 서버 시각 원문
    by: str                  # 사용자 표시 이름
    version: int | None      # 필드 변경만
    title: str               # 댓글: 댓글 ID, 첨부: 파일명, 필드 변경: 빈 문자열
    changes: tuple[ItemFieldChange, ...]   # 필드 변경만
    body: str                # 댓글 본문(평문), 첨부: 크기·MIME 요약
    change_summary: str      # 필드 변경 정보가 없는 버전의 요약
    edited: bool             # 댓글이 만든 뒤 수정됐는지

@dataclass(frozen=True)
class FieldChangeSummary:
    field_name: str
    first_value: Any         # 구간에서 가장 이른 변경의 이전 값
    last_value: Any          # 구간에서 가장 늦은 변경의 새 값
    change_count: int
    last_at: str
    last_by: str

@dataclass(frozen=True)
class ItemActivitySummary:
    version_count: int
    field_change_count: int          # 필드 변경 건수(필드 단위)
    changed_field_count: int         # 바뀐 필드 수
    versions_without_changes: int    # changes가 없는 버전 수
    comment_count: int
    attachment_count: int
    fields: tuple[FieldChangeSummary, ...]
```

변환 함수:

- `history_entries(snapshot: ItemHistorySnapshot) -> tuple[ItemActivityEntry, ...]`
- `comment_entries(snapshot: ItemCommentsSnapshot) -> tuple[ItemActivityEntry, ...]`
- `attachment_entries(attachments: tuple[AttachmentSummary, ...]) -> tuple[ItemActivityEntry, ...]`
- `merge_entries(*groups) -> tuple[ItemActivityEntry, ...]`: 시각 내림차순. 같은 시각이면 필드 변경, 댓글, 첨부 순.
  시각을 해석할 수 없는 항목은 맨 뒤에 둔다.
- `summarize(entries) -> ItemActivitySummary`: 필드는 필드 ID가 있으면 ID, 없으면 이름으로 묶는다.

거르기 함수 `filter_entries(entries, *, scope: ActivityScope, kinds: set[ItemActivityKind]) -> tuple[...]`.
`ActivityScope`는 6절의 세 가지 구간 중 하나를 나타낸다.

시각 해석 `parse_server_time(text) -> datetime | None`:

- ISO 8601을 `datetime.fromisoformat`으로 읽되 끝의 `Z`는 `+00:00`으로 바꾼다.
- 시간대가 없으면 UTC로 본다. 서버가 `Z`를 붙여 주므로 실제로는 거의 쓰이지 않는다.
- 읽을 수 없으면 `None`. 구간 거르기는 `None`을 제외하고 제외 건수를 센다.

## 6. 구간 규칙

구간은 세 가지다.

| 구간 | 어디서 | 필드 변경 | 댓글·첨부 |
| --- | --- | --- | --- |
| 전체 | 양쪽 | 모든 버전 | 모든 항목 |
| 기준 Baseline 이후 | 양쪽 | `modifiedAt > baseline.createdAt` | `at > baseline.createdAt` |
| 비교 시점 사이 | 비교 탭만 | 지금 규칙. 앞 버전 제외, 뒤 버전 포함. 한쪽에만 있으면 처음부터 그 버전까지 | 두 시점의 생성 시각 사이. `현재 상태`는 상한 없음. 한쪽에만 있으면 처음부터 |

경계는 Baseline 생성 시각과 같은 항목을 Baseline에 들어간 것으로 보고 제외한다.

Baseline 생성 시각이 비어 있을 때:

- `기준 Baseline` 콤보에서 그 Baseline 항목을 비활성으로 두고 툴팁에 "생성 시각이 없어 기준으로 쓸 수 없습니다"를 적는다.
- `비교 시점 사이`에서 두 시점 중 하나가 그런 Baseline이면 필드 변경은 버전 범위로 그대로 거르고, 댓글·첨부는
  구간을 정할 수 없어 제외하며 상태줄에 "Baseline 생성 시각이 없어 댓글·첨부 구간을 정할 수 없습니다"를 적는다.

기본값:

- 비교 탭: `비교 시점 사이`.
- Baseline 상세 창: 그 Baseline이 목록에 있으면 `기준 Baseline 이후`로 그 Baseline을 고른다. 목록에 없으면 `전체`.
- 현재 아이템 상세 창: `전체`.

유형 기본값은 세 유형 모두 켠다. 관계는 꺼진 채 비활성이며 툴팁에 "서버 응답에 시각 정보가 없어 지원하지
않습니다"를 적는다.

Baseline 상세 창은 지금처럼 그 Baseline 버전 위치에 구분선을 긋고 이후 항목에 `[Baseline 이후]`를 붙인다.
`기준 Baseline 이후` 구간에서는 모든 항목이 이후이므로 구분선 없이 표시만 남긴다.

## 7. 화면

새 모듈 `src/gui/item_activity_panel.py`의 `ItemActivityPanel(QWidget)`. 비교 패널의 `history_tab`과 상세 창의
이력 탭이 지금의 상태줄·트리 대신 이 패널을 둔다. 기존 `ItemChangeHistoryView`는 이 패널 안의 트리로 남되
입력을 `ItemHistoryEntry`에서 `ItemActivityEntry`로 바꾸고 댓글·첨부 행 표시를 더한다. 버전 행과 필드 행의
모양, 구분선, `[Baseline 이후]` 표시는 지금과 같다.

구성(위에서 아래로):

1. 도구줄: `기준 Baseline` 콤보, 유형 체크 3개와 비활성 `관계` 체크, 오른쪽 끝에 `이력 Excel 내보내기` 버튼.
2. 상태줄: 조회 상태, 건수, 유형별 실패.
3. 세로 분할자: 위에 필드별 요약 표, 아래 시간순 트리. 처음 비율은 1:2.

`기준 Baseline` 콤보 항목: 비교 탭은 `비교 시점 사이`, `전체`, Baseline 목록 순. 상세 창은 `전체`, Baseline
목록 순. Baseline 항목 글자는 비교 탭의 소스 콤보와 같이 "이름 (생성 시각)"이다.

필드별 요약 표 열: `필드`, `구간 처음 값`, `구간 마지막 값`, `변경 횟수`, `마지막 수정`. 값은
`display_tracker_value`로 글자로 바꾸고 칸은 300자, 툴팁은 4000자에서 줄인다. 변경 횟수 내림차순이 기본
정렬이고 열 제목으로 바꿀 수 있다. 필드 변경 유형을 끄면 표를 비우고 "필드 변경 유형을 켜면 필드별 요약을
보입니다"를 적는다.

시간순 트리 행:

- 필드 변경: 지금 모양. `버전 N · 시각 · 사용자 · 필드 K개`, 아래에 필드·이전 값·새 값.
- 댓글: `댓글 · 시각 · 작성자 (수정됨)`, 아래 한 행에 본문 첫 300자. 댓글 첨부가 있으면 그다음 행에 파일명 목록.
- 첨부: `첨부 · 시각 · 파일명 · 크기`. 사용자는 계약 확인 뒤 있으면 붙인다.

상태줄 글자:

- 받는 중: `#ID · 필드 변경·댓글 조회 중`처럼 받는 유형만 적는다.
- 받은 뒤: `#ID · 버전 N건 · 필드 변경 M건 · 바뀐 필드 K개 · 댓글 C건 · 첨부 A건`. 꺼진 유형은 적지 않는다.
  `changes`가 없는 버전이 있으면 ` · 필드 변경 정보 없는 버전 X건`을 붙인다. 시각을 읽지 못해 제외한 항목이
  있으면 ` · 시각 없는 항목 Y건 제외`를 붙인다.
- 유형 실패: `댓글 조회 실패: <서비스 메시지>`를 끝에 붙이고 그 유형의 `다시 시도` 버튼을 보인다.

`이력 Excel 내보내기` 버튼은 켜진 유형이 모두 도착했고 걸러진 항목이 하나 이상일 때만 켠다.

## 8. 조회 흐름

패널은 조회를 직접 하지 않는다. 생성자로 `request_kind(kind: ItemActivityKind, force: bool)` 콜백을 받고,
받은 데이터를 `set_source(kind, data)` 또는 `set_source_error(kind, message)`로 돌려받는다.

패널이 조회를 요청하는 때:

- 탭이 보이는 상태에서 아이템이 바뀌었을 때, 켜진 유형 중 아직 받지 않은 유형.
- 유형 체크를 켰을 때, 그 유형을 아직 받지 않았으면.
- `다시 시도`를 눌렀을 때 그 유형을 `force=True`로.

기준 Baseline이나 유형 체크를 바꾸는 것은 받아 둔 데이터를 다시 거르기만 하고 요청을 내지 않는다.

늦은 응답: `set_source`는 아이템 ID를 함께 받아 지금 아이템과 다르면 버린다. 지금 규칙과 같다.

### 비교 탭

`BaselineWorkspacePanel`이 `comment_service`, `content_service`를 더 받는다(생성자 인자, 작업공간이 넘긴다).

| 유형 | 호출 | 비고 |
| --- | --- | --- |
| 필드 변경 | `context_service.load_history(settings, item_id, max_version)` | 지금 그대로 |
| 댓글 | `comment_service.load_comments(settings, item_id, max_version)` | `baseline_id=None`. 전체 이력이므로 현재 댓글 |
| 첨부 | `content_service.load_attachments(settings, item_id, raw_payload=뒤 시점 raw)` | payload에 첨부가 있으면 요청 없음 |

각 호출은 `host.submit`에 `baseline_item_activity:<kind>` 키로 따로 올린다. 한 유형의 실패는 그 유형만
실패로 표시한다.

### 상세 창

상세 창은 지금처럼 `context_tab_requested("history", force)`로 이력을 받고, 댓글은 댓글 탭과 같은
`comments_requested(force)`를 쓴다. `set_comments`가 댓글 탭과 활동 패널 양쪽에 넣는다. 첨부는 창을 열 때
받은 `attachments`를 바로 넣고, 상세 새로고침으로 바뀌면 다시 넣는다.

Baseline 목록은 작업공간이 트래커를 고를 때 받은 것을 보관해 두고(`TrackerWorkspacePage`에 마지막 목록을
들고 있는다), `DetailDialogController.open_dialog`가 생성자 인자 `baselines`로 상세 창에 넘긴다. 목록을 아직 받지
못했으면 빈 튜플이고 콤보에는 `전체`만 남는다.

첨부의 `raw_payload`는 비교 탭에서 두 시점 중 더 늦은 시점의 아이템 raw를 쓰고, 한쪽에만 있으면 그것을 쓴다.

Baseline 상세 창은 댓글 탭을 지금처럼 막아 두되, 활동 패널의 댓글 유형은 `baseline_id=None`으로 현재 댓글을
받는다. 이력이 시점과 관계없는 전체 이력인 것과 같은 이유다. 10절 참고.

## 9. Excel 내보내기

새 모듈 `src/gui/item_activity_export.py`.

```python
@dataclass(frozen=True)
class ItemActivityExportRequest:
    item_id: int
    item_name: str
    tracker_name: str
    scope_label: str             # 예: "Baseline 2026-Q3 (2026-07-15T09:00:00Z) 이후"
    kind_labels: tuple[str, ...] # 켜진 유형 이름
    entries: tuple[ItemActivityEntry, ...]   # 걸러진 항목
    summary: ItemActivitySummary
    baseline_boundary: int | None            # Baseline 상세 창의 Baseline 버전

def export_item_activity_xlsx(request, output_path) -> ItemActivityExportSummary
def create_item_activity_workbook(request, *, generated_at=None) -> tuple[Workbook, ItemActivityExportSummary]
```

시트:

1. `요약`: 아이템 ID·이름, 트래커, 구간, 유형, 생성 시각, 버전 수, 필드 변경 건수, 바뀐 필드 수,
   필드 변경 정보 없는 버전 수, 댓글 수, 첨부 수, 긴 값 분할 안내.
2. `필드별 요약`: 7절의 표와 같은 열.
3. `이력`: `순번`, `유형`, `버전`, `시각`, `사용자`, `대상`, `이전 값`, `새 값`, `구간`. 필드 변경은 필드마다
   한 행이고 같은 버전은 `버전`·`시각`·`사용자` 칸을 세로로 합친다. 댓글은 `대상`에 댓글 ID, `새 값`에 본문.
   첨부는 `대상`에 파일명, `새 값`에 크기·MIME. `구간`은 Baseline 상세 창에서만 `Baseline 이후`를 적는다.
4. `긴 값 전체보기`: 셀 한도를 넘는 값을 기존 `excel_long_value` 규칙으로 나눈다. 행은 `순번`, `유형`, `대상`,
   `어느 칸`(이전 값/새 값), `부분`, `전체 내용`, `이동`. 이력 시트의 해당 칸에는 미리보기와 내부 링크를 둔다.

서식은 `excel_export_style`의 머리글·테두리·글꼴을 그대로 쓴다. 수식으로 읽힐 수 있는 머리글자는 기존처럼
작은따옴표를 붙인다.

저장 흐름:

- 비교 탭: 패널의 `export_requested(request)` 콜백 → 작업공간이 파일 대화상자(`item_history_{item_id}.xlsx`)
  → `host.submit("baseline_item_activity_export", ...)` → 완료·실패를 패널 상태줄과 작업공간 상태줄에 적는다.
- 상세 창: 새 시그널 `history_export_requested(object)` → `DetailDialogController`가 같은 순서로 처리한다.

실행 기록: `ActivityOperation.ITEM_HISTORY_EXPORT = "item_history_export"`, 라벨 `변경 이력 Excel 내보내기`.
세부에는 아이템 ID, 유형 수, 항목 수, 긴 값 수만 넣는다.

## 10. Baseline 상세 창의 댓글·첨부

기존 규칙은 "Baseline 상세는 과거 댓글 revision 계약 확인 전 현재 댓글을 대신 표시하지 않음"이다. 이 설계는 그
규칙을 다음과 같이 지킨다.

- 댓글 탭은 그대로 막는다.
- 활동 패널의 댓글·첨부는 "아이템 전체 이력의 일부"로 넣고, Baseline 버전 뒤의 항목에는 `[Baseline 이후]`를
  붙인다. 즉 Baseline 시점 댓글로 보이지 않는다.
- Excel `구간` 열도 같은 표시를 가진다.
- 상태줄에 "댓글·첨부는 현재 목록이며 Baseline 시점 내용이 아닙니다"를 한 번 적는다.

## 11. 오류 처리

- 유형별 조회 실패는 그 유형만 실패로 표시하고 나머지는 보인다. 메시지는 서비스가 주는 종류별 문구를 쓴다.
- 시각을 읽지 못한 항목은 `전체` 구간에서는 맨 뒤에 보이고, 다른 구간에서는 제외하며 건수를 적는다.
- Excel 저장 실패는 기존 `BaselineExportError`와 같은 방식으로 `ItemActivityExportError`를 내고, 임시 파일을
  지운다.
- 셀 한도 초과는 긴 값 시트로 넘기고, 행 한도 초과는 아이템 ID와 함께 실패로 알린다.

## 12. 테스트 계획

| 영역 | 파일 | 확인 |
| --- | --- | --- |
| 모델 | `tests/test_gui_item_activity.py` | 변환, 병합 순서, 세 구간 거르기, 경계값, 시각 해석, 필드별 요약, `changes` 없는 버전 |
| 패널 | `tests/test_gui_item_activity_panel.py` | 콤보·체크 기본값, 요청 시점, 늦은 응답 무시, 상태줄 글자, 요약 표 정렬, 내보내기 버튼 조건, 관계 비활성 |
| 트리 | `tests/test_gui_item_change_history_view.py` | 댓글·첨부 행 모양 추가 |
| 내보내기 | `tests/test_gui_item_activity_export.py` | 시트 구성, 열, 합친 칸, 긴 값 분할과 링크, 수식 방지 |
| 비교 탭 | `tests/test_gui_tracker_workspace.py` | 유형별 요청 기록, 첨부 payload 재사용, 실패 유형 격리, 내보내기 백그라운드 흐름과 실행 기록 |
| 상세 창 | `tests/test_gui_tracker_item_detail_dialog.py` | 댓글 공유, 첨부 즉시 표시, Baseline 창 표시 규칙 |
| 계약 확인 | `tests/test_inspect_item_activity_contract.py` | `secret`이 든 가짜 payload로 출력에 값이 없는지, 한 화면 길이 |

GUI 테스트는 창 클래스를 patch 하므로 끝나면 `run-gui` 스킬로 비교 탭과 상세 창을 실제로 띄워 유형 체크,
Baseline 선택, 내보내기까지 눌러 본다. 테스트 모드 샘플에는 첨부를 넣어 세 유형이 모두 보이게 한다.

## 13. 문서 갱신

- `docs/feature-status.md`: Baseline 비교와 상세 창 항목에 활동 이력·유형·내보내기 추가.
- `docs/tracker-query-service.md`: 이력·댓글·첨부가 활동 이력으로 합쳐지는 규칙과 구간 규칙.
- `docs/activity-history.md`: 새 실행 기록 종류.
- `README.md`: Baseline 비교 절에 한 줄.
- `todo.md`: 1절 실서버 확인.

## 14. 후속 계획 B: 여러 아이템 선택 내보내기

이 문서 범위 밖이지만 모델과 내보내기 코드를 그대로 쓰도록 미리 맞춘다.

- 전체 비교 결과 표에 체크 열을 두고 현재 필터 전체 선택·해제 버튼을 둔다. 행 선택은 지금처럼 상세를 바꾸고
  체크만 내보내기 대상이다.
- `선택 아이템 이력 내보내기`는 아이템 수 × 켜진 유형 수만큼 요청이 나가므로 확인 대화상자에 요청 수를 보인다.
  세션 캐시에 있는 것은 다시 받지 않는다.
- 순서대로 받으며 진행 수와 취소를 두고, 일부 실패는 요약 시트에 `조회 실패` 행으로 남긴다.
- Excel은 아이템별 요약 시트, 필드별 요약 시트(아이템 열 추가), 이력 시트(아이템 열 추가)로 구성한다.
- A가 `main`에 들어간 뒤 별도 브랜치에서 스펙을 쓰고 시작한다.

## 15. 결정 사항 요약

| 결정 | 선택 | 이유 |
| --- | --- | --- |
| 유형 출처 | 이력·댓글·첨부 API를 각각 받아 화면에서 합침 | 검증된 엔드포인트만 사용. 이력 API 단일 응답은 미확인 |
| 관계 유형 | 미지원, 비활성 체크 | 응답에 시각 없음. 참조 변경은 필드 변경으로 드러남 |
| Baseline 이후 판정 | Baseline 생성 시각과 항목 시각 비교 | 아이템별 Baseline 시점 버전 조회 불필요. Baseline 정의와 일치 |
| 비교 시점 사이의 필드 변경 | 지금처럼 버전 범위 | 정확하고 이미 검증됨 |
| 첨부 시각 | `modifiedAt` | 지금 확인된 유일한 시각. 계약 확인 뒤 `createdAt`로 교체 가능 |
| 저장 실행 | 백그라운드 작업 + 실행 기록 | 기존 내보내기와 같은 사용자 경험 |
| 새 모듈 | `item_activity.py`, `item_activity_panel.py`, `item_activity_export.py` | 모델·화면·Excel을 나눠 각각 테스트 |

## 16. 열린 질문

없음. 실서버 확인 결과는 4절의 후속 규칙대로 반영한다.
