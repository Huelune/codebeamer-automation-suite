# 트래커 조회 서비스 계약

## 현재 상태

이 문서는 읽기 전용 데이터 계층과 이를 사용하는 `TrackerWorkspacePage`의 경계를 설명합니다.
확장형 트리, tracker 범위 검색, ID 직접 접근과 상세 화면이 이 계약을 사용합니다.

현재 구현된 범위:

- 프로젝트와 트래커 목록 정규화
- 트래커 최상위 아이템과 아이템의 직접 하위 목록 전체 수집
- 간편, 조건 조합, CbQL 검색을 하나의 `TrackerQuery`로 표현
- 선택 tracker ID를 모든 검색 CbQL에 강제로 결합
- 아이템 상세, builtin/custom field, 부모·자식 요약과 원본 JSON 정규화
- 설명 format과 custom/TableField 값 모델을 보존해 화면이 명시적 Wiki 형식만 렌더링할 수 있게 함
- ID 직접 접근용 프로젝트·트래커 컨텍스트와 parent 조상 경로 조회
- 계층 pagination 전체 수집과 검색 pagination 응답·사용자 요청값의 분리 보존
- 배열 또는 객체로 반환되는 tracker schema 응답 정규화
- 인증, 권한, 없음, 요청 제한, 잘못된 조건, 네트워크, 서버 오류 분류
- credential 계열 키의 원본 JSON 마스킹
- 두 tracker를 포함한 익명 테스트 모드 snapshot
- 트래커 Baseline 목록과 현재/Baseline별 전체 query 결과 비교
- 신규·삭제·변경·동일 전체 결과 캐시와 선택 아이템 상세 재사용
- 트래커 전체 query와 최상위 목록을 결합한 계층 Excel snapshot
- Baseline 전체 query만으로 재구성한 단일 시점 계층과 읽기 전용 상세

쓰기, 상태 전환, 관계·댓글·첨부·이력은 이 서비스의 범위가 아닙니다. Wiki 렌더링, 첨부 목록과
인증 바이너리 다운로드는 별도 `TrackerContentService`가 담당합니다. 현재 아이템의 관계·참조와 변경 이력은
`TrackerItemContextService`가 담당하며 상세 창에서 각 탭을 처음 열 때만 조회합니다. 현재 아이템 댓글 목록은
`TrackerCommentService`가 정규화하고 본문·첨부 리소스는 content service를 재사용합니다.
단건 생성, 선택 필드 수정, Status 필드 변경과 삭제는 [트래커 아이템 단건 생성·수정·Status 필드 변경·삭제](./tracker-item-editor.md)의
별도 서비스 계약을 사용합니다.

## 온라인 API 경계

| 기능 | V3 endpoint | 구현 위치 |
| --- | --- | --- |
| 트래커 아이템 참조 | `GET /v3/trackers/{trackerId}/items` | `CodebeamerClient.get_tracker_items_page()` |
| 트래커 최상위 아이템 | `GET /v3/trackers/{trackerId}/children` | `CodebeamerClient.get_tracker_children_page()` |
| 직접 하위 아이템 | `GET /v3/items/{itemId}/children` | `CodebeamerClient.get_item_children_page()` |
| 조건 검색 | `GET /v3/items/query` | `CodebeamerClient.search_items()` |
| Baseline 목록 | `GET /v3/trackers/{trackerId}/baselines` | `CodebeamerClient.get_tracker_baselines()` |
| Baseline 전체 비교 | `GET /v3/items/query?baselineId={baselineId}` | `TrackerQueryService.compare_tracker_at_sources()` |
| Baseline 단일 계층 | `GET /v3/items/query?baselineId={baselineId}` | `TrackerQueryService.load_baseline_hierarchy_snapshot()` |
| 상세 | `GET /v3/items/{itemId}` | `CodebeamerClient.get_item()` |
| 관계·참조 | `GET /v3/items/{itemId}/relations` | `TrackerItemContextService.load_relations()` |
| 변경 이력 | `GET /v3/items/{itemId}/history` | `TrackerItemContextService.load_history()` |
| 댓글 | `GET /v3/items/{itemId}/comments` | `TrackerCommentService.load_comments()` |
| schema | `GET /v3/trackers/{trackerId}/schema` | `CodebeamerClient.get_tracker_schema()` |
| Wiki HTML | `POST /v3/projects/{projectId}/wiki2html` | `TrackerContentService.render_wiki()` |
| 첨부 목록 | 서버 Swagger 확인 필요 | `TrackerContentService.load_attachments()` |

관계 응답은 하위·상위 참조와 들어오는·나가는 association 네 그룹을 그대로 보존합니다. 관계 ID는 서버
버전에 따라 숫자 또는 문자열일 수 있으므로 문자열 식별자로 유지하고, `itemRevision.id`가 양의 정수로
확인된 항목만 상세 이동을 허용합니다. 목록을 표시하기 위한 관계별 추가 상세 요청은 하지 않습니다.
관계·이력 캐시는 연결 설정, item ID와 version으로 구분하며 설정 변경과 명시적 상세 새로고침 때
무효화합니다. Baseline 상세에서는 현재 상태 endpoint를 호출하지 않습니다.

댓글은 상세 창의 댓글 탭을 처음 열 때만 현재 item ID와 version 기준으로 조회합니다. `replyTo`가 확인된
댓글은 부모 아래에 시간순으로 묶고, Wiki 형식 본문은 기존 HTML 정제와 로컬 fallback을 사용합니다.
이미지 첨부만 기존 10MB/개·50MB/아이템 한도 안에서 자동으로 받고 다른 첨부는 사용자가 저장을 선택할
때만 받습니다. Baseline에서는 현재 댓글 endpoint를 호출하지 않습니다.

PTC 문서의 목록 응답은 `page`, `pageSize`, `total`을 포함하지만, 서버 버전과 endpoint에 따라
요청한 페이지가 실제로 적용되지 않고 전체 결과가 반환될 수 있습니다. 계층 조회는 최대 500개씩 요청하고
`total`에 도달할 때까지 중복 ID를 제외하며 모든 서버 페이지를 합칩니다. 화면에는 페이지 구분 없이 하나의
스크롤 트리로 전달합니다. 검색의 `PageResult`는 서버 응답값과 `requested_page`, `requested_page_size`를
함께 저장하고 `server_honored_pagination`을 별도로 제공합니다.

`GET /v3/trackers/{trackerId}/schema`는 Codebeamer 버전에 따라 필드 정의 배열 또는 필드 컨테이너 객체를
반환할 수 있습니다. 조회 서비스는 배열을 `{"id": trackerId, "fields": [...]}`로 정규화해 생성·수정
서비스가 동일한 계약을 사용하도록 합니다.

Baseline 목록은 응답의 `page`, `pageSize`, `total`, `references`를 해석해 `total`에 도달할 때까지
모든 페이지를 수집하고 Baseline ID가 중복된 항목은 한 번만 유지합니다. `total`에 도달하지 않은
상태에서 서버가 같은 페이지를 반복하거나 빈 페이지를 반환하면 일부 목록을 정상 결과로 가장하지 않고 오류로
처리합니다. 배열을 직접 반환하는 기존 서버 응답은 호환 경로로만 유지합니다. 전체 비교는 기준과 비교 대상에 대해
`tracker.id = <trackerId> ORDER BY item.id ASC` query를 각각 끝까지 순회하고, Baseline 대상에만
`baselineId`를 전달합니다. 이 경로는 필드 비교에 필요한 상세 `items` 응답만 허용하며 `itemRefs`로
조용히 대체하지 않습니다. 모든 페이지가 성공한 뒤에만 화면 캐시를 교체합니다.

### Baseline 저장본

Baseline 내용은 만든 뒤 바뀌지 않으므로, Baseline 시점 전체 `items` 응답을 PC에 저장해 다시 씁니다
(`src/gui/baseline_cache.py`의 `BaselineItemCache`).

- 위치는 사용자 설정 폴더의 `baseline_cache/`이고, 실행 기록·일괄 수정 기록과 같은 수준의 평문 gzip JSON입니다.
- 서버 주소·사용자·트래커·Baseline·조회 조건(CBQL과 정렬)이 모두 같을 때만 같은 저장본입니다. 계정마다
  볼 수 있는 아이템이 다르므로 사용자별로 나누고, 조회 방식이 바뀌면 예전 저장본을 쓰지 않습니다.
- 서버가 준 원본 `items`를 그대로 저장하고 읽을 때 다시 해석합니다. 파일 안의 형식 번호나 조건이 다르거나
  파일이 깨졌으면 쓰지 않고, 깨진 파일은 지웁니다.
- Baseline 단일 계층과 전체 비교의 Baseline 쪽만 저장본을 씁니다. 현재 상태와 테스트 모드는 저장하지 않습니다.
- 전체가 500MB를 넘으면 가장 오래 쓰지 않은 저장본부터 지우고, 설정 > 데이터 관리에서 사용량을 보고 비울 수 있습니다.
- 저장은 부가 기능이라 폴더를 만들 수 없거나 쓰기에 실패해도 조회를 끊지 않습니다.
- 응답에 담긴 사용자·선택지·참조 아이템 이름이 조회 시점 값이라면, 저장본에는 받은 시점의 이름이 남습니다.
  계층 탭의 `Baseline 계층 다시 불러오기`로 새로 받아 덮어쓸 수 있습니다.

참고:

- [PTC Tracker Item Operations](https://support.ptc.com/help/codebeamer/r3.2/en/codebeamer/developers_guide/swagger/11375769.html)
- [PTC Retrieve Child Tracker Items](https://support.ptc.com/help/codebeamer/r2.2/en/codebeamer/developers_guide/dg_retrieving_list_of_child_tracker_items.html)
- [PTC cbQL Order](https://support.ptc.com/help/codebeamer/r3.2/en/codebeamer/user_guide/ug_cbql_order.html)
- [PTC Pagination](https://support.ptc.com/help/codebeamer/r2.2/en/codebeamer/developers_guide/dg_pagination.html)

## 검색 범위 보장

`TrackerQuery.build_cbql()`은 사용자 조건을 항상 아래 형태로 감쌉니다.

```text
tracker.id = <현재 tracker ID> AND (<사용자 조건>) ORDER BY <검증된 정렬식>
```

- 간편 검색은 ID/요약, 상태, 담당자를 조합합니다.
- 조건 조합은 그룹 내부 AND, 그룹 사이 OR만 지원합니다.
- 빈 조건 조합은 tracker 전체 조회로 바꾸지 않고 실행을 차단합니다.
- CbQL 모드는 조건식과 `ORDER BY`만 받으며 `SELECT`, `GROUP BY`, 다중 문장을 차단합니다.
- 서버가 다른 tracker의 아이템을 반환하면 결과에서 숨기지 않고 서비스 오류로 처리합니다.

## 화면용 모델

- `ProjectSummary`, `TrackerSummary`: 컨텍스트 선택기
- `TrackerQuery`, `TrackerQueryCondition`, `TrackerQueryGroup`: 검색 조건
- `TrackerItemSummary`: 트리와 검색 결과의 최소 표시 데이터
- `TrackerItemDetail`: builtin/custom field, parent/children, 마스킹된 원본 응답
- `TrackerFieldValue.raw_value`: Wiki와 TableField의 형식·행·열 판정에 사용하는 필드 원본 구조
- `TrackerItemContext`: ID 직접 접근으로 확인한 프로젝트·트래커와 상세
- `PageResult`: 서버와 요청 pagination 메타데이터
- `TrackerQueryServiceError`: 사용자 대응이 가능한 오류 분류

Qt widget은 서버 원본 dict를 직접 탐색하지 않고 위 모델만 사용해야 합니다.

## 테스트 모드 조회 snapshot

설정의 `조회 데이터 Snapshot`은 version 1 JSON 객체이며 다음 목록을 포함합니다.

```json
{
  "version": 1,
  "projects": [],
  "trackers": [],
  "items": []
}
```

규칙:

- project, tracker, item ID는 양의 정수이며 각 범위에서 중복될 수 없습니다.
- tracker는 `projectId`, item은 `trackerId`를 반드시 참조합니다.
- `parentId`가 있으면 같은 tracker의 기존 item이어야 합니다.
- snapshot이 없으면 배치 Dry Run은 계속 사용할 수 있지만 트래커 작업공간 조회는 명시적으로 차단합니다.
- 테스트 모드 CbQL evaluator가 해석하지 못하는 표현식은 결과를 가장하지 않고 `invalid_query`로 처리합니다.

기본 fixture는 `data/gui-offline-sample/offline_tracker_items.json`입니다.

## 작업공간 화면 연결

- `src/gui/tracker_workspace.py`의 `TrackerWorkspacePage`가 화면 계약을 담당합니다.
- 최상위 전체 목록은 tracker별로, 직접 하위 전체 목록은 parent item ID별로 화면 세션에서 캐시합니다.
- 노드를 처음 펼칠 때만 `load_all_child_items()`를 호출합니다.
- 계층 또는 검색 결과 행 선택은 `load_detail()`을 별도 백그라운드 요청으로 실행합니다.
- Baseline 비교는 기준을 변경하면 기존 전체 캐시를 무효화하지만 자동으로 서버를 호출하지 않습니다. 사용자가 `전체 비교 실행` 또는 `전체 비교 다시 불러오기`의 경고를 확인한 경우에만 조회하며, Baseline 쪽은 저장본이 있으면 그것을 쓰고 현재 쪽은 매번 받습니다. 탭 이동, 결과 정렬, 결과 유형·ID/이름·변경 필드 AND 필터와 아이템 선택은 서버를 다시 호출하지 않습니다.
- 변경 필드 필터는 기존 아이템에서 실제로 값이 달라진 경우와 신규·삭제 아이템의 해당 필드 존재 여부를 같은 내부 필드 키로 판정합니다. 상세 비교는 필터와 무관하게 선택 아이템의 전체 필드를 표시하고 Excel은 현재 필터 결과만 사용합니다.
- 사용자 정의 필드는 `custom:<id>`를 내부 식별자로 유지합니다. 표시 이름과 TableField 열은 tracker schema를 우선하며, 이름이 없으면 응답 `name`, `사용자 정의 필드 #ID` 순서로 보완합니다.
- 계층 Excel 내보내기는 `tracker.id = <trackerId> ORDER BY item.id ASC` 전체 `items`와 최상위 목록, schema만 사용합니다. `parent`, `children`, `ordinal`로 부모·형제 순서를 재구성하며 아이템별 상세 또는 하위 API를 호출하지 않습니다.
- 최상위 누락, 미연결 item, 중복 부모, 순환이나 tracker 외부 참조가 있으면 일부 계층을 정상 파일로 가장하지 않고 저장을 중단합니다. 내부 `custom:<id>` key는 필드 선택 화면과 Excel에 노출하지 않습니다.
- 계층 Excel의 고정 열은 ID, Summary, 계층 단계, 상위 아이템 ID입니다. 일반 schema 필드는 기본 선택하고 TableField는 기본 해제하며, 선택 시 내부 행·열 순서를 보존합니다.
- 계층 Excel의 TrackerItemChoiceField는 참조 ID나 tracker 정보 없이 각 참조 아이템의 `name`만 줄 단위로 표시합니다.
- 기본 계층 탭에서 Baseline을 선택하면 저장본이 있을 때는 서버에 묻지 않고 바로 열고, 없으면 사용자가 계층 조회 버튼을 누른 경우에만 해당 시점의 전체 `items` 페이지를 수집해 저장합니다. 이미 연 Baseline에서 `Baseline 계층 다시 불러오기`를 누르면 저장본을 무시하고 새로 받아 덮어씁니다. 저장본으로 연 계층은 트리 위 상태 줄에 받은 시각을 표시합니다. root는 parent가 없는 item에서 도출하고, children의 명시 순서와 ordinal/ID fallback으로 트리를 구성합니다. 이 과정에서 현재 시점 root/children API나 아이템별 상세 API를 사용하지 않습니다.
- Baseline 트리의 상세는 동일한 `baselineId`를 유지하며 읽기 전용으로 표시합니다. 관계 충돌, 순환, 누락 참조 또는 tracker 외부 참조가 있으면 현재 계층으로 대체하지 않고 조회를 중단합니다.
- Baseline 단일 계층 Excel은 먼저 조회해 캐시한 `TrackerHierarchySnapshot`과 tracker schema를 기존 계층 workbook 생성기에 전달합니다. 필드 선택과 TableField 행 구조, TrackerItemChoiceField 이름 표시 규칙을 그대로 유지하며 내보내기 때문에 전체 query나 아이템별 상세를 다시 호출하지 않습니다. 내보내기 정보 시트에는 Baseline 이름과 ID를 기록합니다.
- tracker 검색은 선택 tracker ID로 `TrackerQuery`를 만들며 빈 검색 조건은 화면에서 차단합니다.
- ID 바로 열기는 `resolve_item_context()` 후 `load_ancestor_path()`를 호출해 선택 컨텍스트와 경로를 함께 전환합니다.
- 설정·선택이 바뀐 뒤 늦게 끝난 요청이 화면을 덮지 않도록 작업 종류별 request token과 현재 tracker/item을 비교합니다.
- Wiki 캐시는 연결, project, item, version, Baseline과 원문 digest를 함께 사용합니다. 현재와 Baseline
  상세는 같은 item ID여도 캐시와 첨부를 공유하지 않으며 명시적 상세 새로고침은 해당 item의 content
  캐시를 비웁니다.
