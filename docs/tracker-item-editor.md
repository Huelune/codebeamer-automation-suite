# 트래커 아이템 단건 생성·수정·Status 필드 변경·삭제

## 목적

`TrackerWorkspacePage`는 선택한 tracker schema를 기준으로 단건 생성 입력 UI를 만들고,
`수정` 탭에서는 체크한 필드만 부분 업데이트합니다. Status 필드 변경과 삭제는 일반 필드 저장과 분리합니다.
관계, 댓글, 첨부와 이력 편집은 아직 이 범위에 포함하지 않습니다.

## API 계약

| 기능 | V3 endpoint | 구현 위치 |
| --- | --- | --- |
| 단건 생성 | `POST /v3/trackers/{trackerId}/items` | `TrackerItemEditorService.create_item()` |
| 선택 아이템의 하위 생성 | 위 endpoint와 `parentItemId` query | `TrackerItemEditorService.create_item()` |
| 선택 필드 수정 | `PUT /v3/items/{itemId}/fields` | `CodebeamerClient.update_item_fields()` |
| Status 필드 변경 | `PUT /v3/items/{itemId}/fields`의 Status `ChoiceFieldValue` | `TrackerItemEditorService.change_status_field()` |
| 아이템 삭제 | `DELETE /v3/items/{itemId}` | `CodebeamerClient.delete_item()` |

전체 리소스용 `PUT /v3/items/{itemId}`는 요청 본문에 없는 상태를 지울 수 있으므로 작업공간 편집에서는
사용하지 않습니다. PTC 문서가 안내하는 `fieldValues` 부분 업데이트만 사용합니다.

참고:

- [PTC Creating a Tracker Item](https://support.ptc.com/help/codebeamer/r3.2/en/codebeamer/developers_guide/swagger/11375769.html)
- [PTC Modifying Tracker Items](https://support.ptc.com/help/codebeamer/r3.0/en/codebeamer/developers_guide/swagger/dg_modifying_a_tracker_item.html)
- [PTC Making a Tracker Item Status Transition](https://support.ptc.com/help/codebeamer/r2.2/en/codebeamer/developers_guide/dg_making_tracker_item_status_transition.html)
- [PTC Deleting a Tracker Item](https://support.ptc.com/help/codebeamer/r2.2/en/codebeamer/developers_guide/dg_deleting_tracker_item.html)

## 단건 생성 흐름

1. 프로젝트와 트래커를 선택합니다.
2. 컨텍스트 영역의 `새 아이템`을 누릅니다.
3. 최상위 생성을 유지하거나, 현재 선택 아이템이 같은 tracker에 속하면 그 아이템의 하위 생성을 선택합니다.
4. 필수 필드는 항상 포함된 상태로 입력하고, 선택 필드는 `포함`을 체크한 항목만 입력합니다.
   생성 화면의 `전체 화면` 버튼으로 입력 표를 넓게 사용할 수 있습니다.
5. 생성 화면이 schema 기준으로 필수값, option, 단일·다중 참조 형식을 검증합니다.
6. 서비스가 하위 생성의 상위 아이템이 현재 tracker에 속하는지 다시 확인한 뒤 생성 API를 호출합니다.
7. 생성된 ID로 상세를 다시 조회하고, 새 노드를 계층 트리에 선택한 상태로 추가해 오른쪽 상세를 엽니다.

생성 위치는 실수로 잘못된 계층에 넣는 일을 줄이기 위해 `최상위 아이템`을 기본값으로 사용합니다.
Status는 생성 payload에 넣지 않고 서버 기본 상태로 생성합니다. 다른 상태가 필요하면 생성 후 `수정` 탭의
별도 Status 필드 변경을 사용합니다. 관계와 댓글 입력은 단건 생성 화면에 아직 포함하지 않습니다.

생성할 수 없는 필드는 입력 표에서 숨깁니다. schema가 필수로 지정한 필드 중 현재 UI가 지원하지 않는
유형이 있으면 상단 경고에 필드명을 표시하고 생성 버튼을 비활성화합니다.
서버 응답에 생성 ID가 없으면 중복 생성을 피하도록 tracker 확인을 안내합니다. 생성 ID는 받았지만 상세
재조회만 실패한 경우에는 생성 완료 사실과 확인 가능한 ID를 함께 표시합니다.

## 편집 흐름

1. 계층 또는 검색 결과에서 아이템을 선택합니다.
2. 상세 패널의 `수정` 탭을 엽니다.
3. 화면이 현재 tracker schema를 조회해 필드별 입력 widget을 만듭니다.
   수정할 수 없는 필드는 입력 표에서 숨기며, `새 창에서 크게 수정`으로 현재 입력 상태를 유지한 채
   별도 창이나 전체 화면에서 작업할 수 있습니다.
4. 변경할 필드만 `수정` 열에서 체크합니다.
5. 현재 값과 새 값을 같은 행에서 비교하고 `선택한 필드 저장`을 누릅니다.
6. 서비스가 저장 직전에 현재 item version을 다시 조회합니다.
7. version이 같으면 체크한 필드의 `FieldValue`만 전송하고 상세를 다시 불러옵니다.
8. 새 상세는 트리와 검색 결과에 즉시 반영되고 해당 tracker의 화면 캐시는 무효화됩니다.

다른 사용자의 수정으로 version이 달라졌으면 저장·Status 필드 변경·삭제를 실행하지 않고 최신 상세 재조회를
요청합니다. 사용자는 상세 상단의 `상세 새로고침`으로 최신 version과 값을 다시 불러올 수 있습니다.
이 확인은 쓰기 직전 충돌을 줄이지만 서버 lock을 획득하는 원자적 보장은 아닙니다.

## 필드 지원 범위

| schema 종류 | 입력 방식 | 동작 |
| --- | --- | --- |
| Text | 한 줄 입력 | `TextFieldValue.value` |
| Description 계열 Text | 여러 줄 입력 | `TextFieldValue.value` |
| Bool | `예` / `아니요` | `BoolFieldValue.value` |
| Integer / Decimal | 숫자 입력 | schema `valueModel.value` |
| Date / DateTime | ISO 형식 입력 | schema `valueModel.value` |
| 정적 Choice option | 단일 또는 여러 선택 | `ChoiceFieldValue.values` |
| referenceType이 명확한 Reference | 한 줄에 참조 ID 하나 | 해당 reference type의 `values` |
| TableField | 전용 행·열 편집기 | 중첩된 `TableFieldValue.values` |
| Status | 별도 필드 변경 선택기 | Status `ChoiceFieldValue.values` |

TableField 편집기는 다음 안전 규칙을 적용합니다.

- 행 추가·복제·삭제·순서 변경과 가로·세로 스크롤, 열 너비·행 높이 조절, 전체 화면을 지원합니다.
- Wiki/Text, Bool, Integer/Decimal, Date/DateTime, 정적 Choice 열을 schema의 `valueModel`로 저장합니다.
- 숨김 셀과 지원하지 않는 기존 셀은 원본 행에 그대로 보존합니다. 행 복제 시에는 화면에서 편집 가능한
  열만 복제해 숨김 ID를 새 행에 복사하지 않습니다.
- 참조 열은 읽기 전용이며, `ReferredTestStep`이 포함된 행은 삭제·복제·순서 변경을 막습니다.
- 기존 행을 모두 지우려면 별도 확인을 요구합니다.

다음 필드와 열은 잘못된 payload를 만들지 않도록 입력 화면에서 숨기거나 읽기 전용으로 유지합니다.

- 새 아이템 생성의 `TableField`
- `MemberField`: user, role, group 유형이 섞여 있고 schema에서 단일 reference type을 결정할 수 없는 경우
- 동적 option이지만 option/reference type을 확인할 수 없는 필드
- hidden, read-only, server 관리 필드

필수 필드를 비우거나, 단일값 필드에 여러 참조를 입력하거나, schema에 없는 option을 선택하면 서버에
요청하기 전에 차단합니다.

날짜 필드는 업로드와 같은 규칙으로 `YYYY-MM-DDTHH:MM:SS.fff` 형식으로 바꿔 보내고, 읽을 수 없는 값은 필드 이름과 함께 저장 전에 막습니다(`docs/field-support-guide.md`의 날짜 필드 처리 규칙).

## Status 필드 변경

- Status는 일반 필드 일괄 저장에 포함하지 않습니다.
- schema의 Status options를 표시하고 현재 상태와 다른 값 하나만 선택할 수 있습니다.
- 현재 구현은 `PUT /v3/items/{itemId}/fields`를 사용하는 단순 필드 변경이며 가능한 workflow transition을 조회하거나 실행하지 않습니다.
- 따라서 화면에 보이는 option이 실제 workflow에서 허용된 전환임을 보장하지 않습니다. 서버가 거부하면 오류를 표시하고 기존 상세를 유지합니다.

실제 workflow transition 조회·필수 입력 검증·실행과 배치 create 후 Status 후처리는 대상 서버 Swagger
계약을 확인한 뒤 별도 기능으로 구현합니다. 현재 필드 변경을 workflow transition으로 재사용하지 않습니다.

## 삭제 안전장치

- 온라인 모드에서만 삭제 버튼을 활성화합니다.
- 확인창에 대상 ID, 이름과 직접 하위 아이템 수를 표시합니다.
- 사용자가 아이템 ID를 정확히 다시 입력해야 `영구 삭제` 버튼이 활성화됩니다.
- 저장과 같은 version 재확인을 통과한 뒤 `DELETE`를 호출합니다.
- 성공하면 현재 트리·검색 결과에서 행을 제거하고 상세 및 tracker 캐시를 비웁니다.

삭제는 복구 기능을 제공하지 않습니다. 관계·연결 데이터 처리 방식은 서버 정책에 따르며, 관계 자체를
개별 삭제하는 기능은 이번 범위에 포함하지 않습니다.

## 테스트 모드

테스트 모드에서는 schema 기반 입력 구조와 현재값 표시, TableField 전용 편집 화면까지 확인할 수 있습니다.
다음 동작은 모두
비활성화되며 서비스 계층에서도 한 번 더 차단합니다.

- 선택 필드 저장
- Status 필드 변경
- 아이템 삭제
- 새 아이템 생성

이중 차단으로 UI 상태와 무관하게 offline snapshot이 실제 쓰기 경로로 사용되지 않도록 유지합니다.
