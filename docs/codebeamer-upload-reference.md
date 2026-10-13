# Codebeamer 업로드 조사 정리

## 목적

이 문서는 "특정 형식의 파일을 Codebeamer Tracker Item으로 업로드하는 프로그램"을 다시 만들 때
필요한 조사 결과와 현재 구현 기준을 한 곳에 정리한 재사용용 기준 문서입니다.

범위:

- 현재 저장소의 CLI/GUI 업로드 경로에서 실제로 사용 중인 규칙
- 코드와 테스트로 확인된 API, schema 해석, payload 생성 방식
- 아직 미지원이거나 후속 설계가 필요한 항목

기준 소스:

- [README](../README.md)
- [아키텍처](./architecture.md)
- [CLI 사용 가이드](./cli-guide.md)
- [필드 지원 추가 가이드](./field-support-guide.md)
- [Codebeamer client](../src/codebeamer_client.py)
- [Mapping service facade](../src/mapping_service.py)
- [Mapping reference](../src/mapping_reference.py)
- [Mapping schema](../src/mapping_schema.py)
- [Mapping option](../src/mapping_option.py)
- [Wizard facade](../src/wizard.py)
- [Wizard data](../src/wizard_data.py)
- [Wizard user lookup](../src/wizard_user_lookup.py)
- [Wizard tracker lookup](../src/wizard_tracker_lookup.py)
- [Wizard payload](../src/wizard_payload.py)
- [Wizard operations](../src/wizard_operations.py)
- [Tracker item 모델](../src/models/tracker_item.py)
- [Field value 모델](../src/models/field_values.py)
- [오프라인 통합 테스트](../tests/test_offline_payload_integration.py)

## 핵심 결론

현재 구현 기준에서 Codebeamer 업로더의 핵심은 다음 다섯 가지입니다.

1. tracker schema를 먼저 가져와 field를 해석해야 한다.
2. field 해석은 `type`을 1차 기준으로 하고 `referenceType`, `options`, `multipleValues`를 보조로 본다.
3. Excel 입력은 summary 컬럼, 들여쓰기, 멀티라인 병합 규칙이 고정돼 있다.
4. payload는 row별로 먼저 cache하고, preview와 upload가 같은 payload를 재사용한다.
5. 일반 reference field 전체를 범용으로 처리할 수 있는 것은 아니며, 현재 지원 범위와 TODO 범위를 분리해야 한다.

## schema 운영 원칙

새 프로젝트에서 schema는 정적으로 박아 두는 데이터가 아니라,
실행 시점에 대상 tracker에서 가져와야 하는 런타임 메타데이터입니다.

권장 원칙:

- source of truth 는 `GET /v3/trackers/{trackerId}/schema` 응답입니다.
- `tracker-schema.json` 같은 파일은 수동 작성 파일이 아니라 export/generated snapshot 입니다.
- snapshot은 오프라인 테스트, 계약 비교, 회귀 검증용으로 유지합니다.

즉 "실행 시 live fetch" 와 "개발/테스트용 snapshot 저장" 을 같이 가져가는 구조가 맞습니다.

## 다른 프로젝트에서 반드시 확보해야 하는 정보

다른 프로젝트에서 같은 성격의 업로더를 만들려면 최소 아래 정보가 필요합니다.

### 1. 서버/인증 정보

- `CODEBEAMER_BASE_URL`
- `CODEBEAMER_USERNAME`
- `CODEBEAMER_PASSWORD`

현재 클라이언트는 Basic Auth와 JSON 요청/응답을 전제로 합니다.

### 2. 프로젝트/트래커 식별 정보

- `project_id`
- `tracker_id`
- 필요 시 업로드 대상 root item 또는 기존 item 목록

### 3. 트래커 schema 메타데이터

각 field마다 최소 아래 속성을 확보해야 합니다.

- `id`
- `name`
- `label` 또는 `title`
- `type`
- `trackerItemField`
- `valueModel`
- `referenceType`
- `options`
- `multipleValues`
- `memberTypes`
- `columns`
- `mandatory`
- `mandatoryInStatuses`
- `hidden`

이 정보가 없으면 어떤 값을 어떤 payload 형태로 넣어야 하는지 확정할 수 없습니다.

추가 메모:

- 현재 구현은 `mandatory=true` 이거나 `mandatoryInStatuses` 가 status option 전체를 덮으면 사실상 항상 필수로 해석합니다.
- 특정 status에서만 필수인 field는 `mandatory_mode=conditional` 로 별도 표시합니다.

### 4. lookup에 필요한 디렉터리 데이터

- 사용자 이름/ID 조회 가능 여부
- 사용자 그룹 목록
- 특정 field의 role 후보 목록
- tracker item reference 입력값 규칙

### 5. 입력 파일 계약

- summary 역할 컬럼 이름
- 들여쓰기 방식
- 멀티라인 레코드 병합 규칙
- list 컬럼 기준
- TableField 헤더 규칙

### 6. workflow 제약

- 특히 `Status` field는 option 목록만으로는 충분하지 않다.
- 생성 직후 허용 가능한 상태와 transition 경로를 별도로 확인해야 한다.

## 현재 사용 중인 Codebeamer REST API

| 메서드 | 경로 | 용도 | 비고 |
| --- | --- | --- | --- |
| `GET` | `/v3/projects` | 접근 가능한 프로젝트 목록 조회 | 프로젝트 선택 단계 |
| `GET` | `/v3/projects/{projectId}/trackers` | 프로젝트 내 트래커 목록 조회 | 트래커 선택 단계 |
| `GET` | `/v3/trackers/{trackerId}` | 트래커 상세 조회 | 보조 정보 |
| `GET` | `/v3/trackers/{trackerId}/items` | 트래커 아이템 참조 목록 조회 | 기존 아이템 확인 용도 |
| `GET` | `/v3/trackers/{trackerId}/children` | 루트 자식 아이템 조회 | 루트 확인 용도 |
| `GET` | `/v3/trackers/{trackerId}/schema` | tracker schema 조회 | 가장 중요 |
| `GET` | `/v3/projects/{projectId}/members` | 프로젝트 멤버 조회 | helper 존재, 현재 핵심 흐름에서는 미사용 |
| `GET` | `/v3/users/groups` | 그룹 목록 조회 | `MemberField`의 `GROUP` 후보 |
| `GET` | `/v3/trackers/{trackerId}/fields/{fieldId}/permissions` | field permission matrix 조회 | `MemberField`의 `ROLE` 후보 |
| `GET` | `/v3/items/{itemId}/fields/{fieldId}/options` | 특정 아이템 field option 조회 | helper 존재 |
| `GET` | `/v3/items/{itemId}` | 아이템 상세 조회 | helper 존재 |
| `GET` | `/v3/users/{userId}` | 사용자 ID 조회 | 이름 조회 실패 시 fallback |
| `GET` | `/v3/users/findByName` | 사용자 이름 조회 | 사용자 lookup 기본 경로 |
| `GET` | `/v3/users/findByEmail` | 사용자 이메일 조회 | helper 존재 |
| `POST` | `/v3/users/search` | 사용자 검색 | helper 존재 |
| `POST` | `/v3/trackers/{trackerId}/items` | 신규 item 생성 | `parentItemId` query 사용 가능 |

추가 동작:

- 생성 API는 rate limit(예: `429`)일 때 재시도합니다.
- 재시도 간격은 `rate_limit_retry_delay_seconds * attempt` 입니다. 응답에 초 단위 `Retry-After`가 있으면 그보다 짧게 기다리지 않고(최대 60초), 동시에 막힌 요청이 같은 순간에 몰리지 않도록 간격에 최대 25%를 무작위로 더합니다.
- 모든 요청은 연결 10초, 응답 대기 120초(조회)·300초(생성·수정·삭제)에서 시간 초과로 끝납니다. 쓰기 요청이 응답 대기 시간을 넘기면 서버 반영 여부를 알 수 없으므로 결과를 확인한 뒤 재시도합니다.
- HTTP 세션은 클라이언트의 스레드마다 하나를 두고 다음 요청에 연결을 다시 씁니다.

## 입력 파일 형식 계약

현재 구현이 전제하는 입력 형식은 Excel 기반 계층형 시트입니다.

### 필수 구조

- 하나의 summary 컬럼이 논리 레코드 제목 역할을 한다.
- summary 셀의 들여쓰기가 parent-child 계층을 표현한다.
- 여러 물리적 행이 하나의 논리 레코드를 표현할 수 있다.
- `multipleValues=true` field에 매핑된 컬럼은 list 컬럼으로 취급한다.
- `TableField`는 `TableFieldName.ColumnName` 헤더 형식을 사용한다.

### reader 단계에서 추가되는 메타 컬럼

- `_excel_row`
- `_summary_indent`

### 병합/계층 단계에서 추가되는 메타 컬럼

- `_start_excel_row`
- `_end_excel_row`
- `_row_id`
- `depth`
- `parent_row_id`
- `upload_name`

### 들여쓰기 규칙

- Excel API에서 `IndentLevel`을 읽을 수 있으면 그것을 사용한다.
- 읽을 수 없으면 문자열 선행 공백 수를 4칸 단위로 나눠 fallback 한다.
- 계층 단계는 이전 행보다 한 번에 1단계보다 크게 증가하면 오류로 본다.

### 멀티라인 병합 규칙

- summary 값이 있는 행이 새 논리 레코드의 시작이다.
- `id` 열이 있으면 summary가 비어 있어도 앞 레코드와 다른 id가 나오는 행부터 새 레코드다. id가 비었거나 같은 행은 이어지는 행이다. summary가 빈 수정 레코드는 기존 이름을 그대로 둔다.
- 첫 summary 앞의 행은 버리지 않고 레코드로 남긴다. 새로 만드는 레코드에 summary가 없으면 `ITEM_NAME_MISSING`으로 검증에서 막는다.
- list 컬럼은 같은 논리 레코드 안에서 값들을 모아 list로 만든다.
- list가 아닌 컬럼은 기본적으로 첫 번째 non-empty 값을 유지한다.

예시 fixture:

```csv
요약,상태,승인,단계,체크리스트.결과,Owner,Related Candidate,시험 담당자,들여쓰기
REQ-001,Open,true,Draft,PASS,101,REQ-999,201,0
,,,Review,,,,,0
```

위 예시는 아래처럼 해석됩니다.

- `REQ-001` 한 건의 item
- `단계`는 `["Draft", "Review"]`
- `체크리스트.결과`는 `TableFieldValue`

## schema 해석 규칙

### 1차 기준

가장 중요한 기준은 `field.type` 입니다.

현재 구현은 아래 순서로 field를 해석합니다.

1. `type`
2. `referenceType`
3. `options`
4. `multipleValues`
5. `valueModel`

`valueModel`은 보조 신호일 뿐 단독 근거로 쓰지 않습니다.

### 내부 분류 체계

field는 아래 세 축으로 정리됩니다.

- `resolved_field_kind`
- `preconstruction_kind`
- `payload_target_kind`

#### `resolved_field_kind`

- `scalar_text`
- `scalar_bool`
- `static_option`
- `user_reference`
- `member_reference`
- `tracker_item_reference`
- `generic_reference`
- `table`
- `unsupported`

#### `preconstruction_kind`

- `none`
- `builtin_direct`
- `field_value`
- `reference`
- `reference_list`
- `table_field_value`

#### `payload_target_kind`

- `builtin_field`
- `custom_field`
- `unsupported`

### schema에서 평탄화해 보관하는 권장 필드

다른 프로젝트에서도 최소 아래 필드는 schema snapshot에 보관하는 편이 좋습니다.

- `field_id`
- `field_name`
- `field_label`
- `field_type`
- `tracker_item_field`
- `value_model`
- `reference_type`
- `member_types`
- `has_options`
- `multiple_values`
- `options`
- `mandatory`
- `mandatory_mode`
- `mandatory_status_names`
- `is_table_field`
- `table_columns`
- `resolved_field_kind`
- `resolution_strategy`
- `is_supported`
- `unsupported_reason`
- `requires_lookup`
- `lookup_target_kind`
- `preconstruction_kind`
- `preconstruction_detail`
- `payload_target_kind`
- `option_source_kind`

## 검증/상태 코드

다른 프로젝트에서도 아래 상태 코드를 그대로 유지하면 디버깅과 산출물 비교가 쉬워집니다.

### 컬럼-스키마 비교

- `OK`
- `UNMAPPED`
- `SCHEMA_FIELD_MISSING`

### option/reference 검증

- `DF_COLUMN_MISSING`
- `OPTION_MAP_MISSING`
- `OPTION_SOURCE_UNAVAILABLE`
- `FIELD_UNSUPPORTED`
- `LOOKUP_REQUIRED`
- `PRECONSTRUCTION_REQUIRED`
- `OPTION_NOT_FOUND`
- `DIRECT_PARSE_FAILED`

### lookup 결과

- `RESOLVED`
- `USER_NOT_FOUND`
- `USER_LOOKUP_FAILED`
- `USER_LOOKUP_NOT_RUN`
- `MEMBER_NOT_FOUND`
- `MEMBER_LOOKUP_AMBIGUOUS`
- `MEMBER_LOOKUP_FAILED`

### payload / upload 결과

- `PAYLOAD_READY`
- `PAYLOAD_FAILED`
- `UPLOAD_SUCCESS`
- `UPLOAD_FAILED`
- `UNRESOLVED_PARENT`

## 현재 지원 매트릭스

| schema 조건 | 내부 분류 | 현재 처리 방식 | 상태 |
| --- | --- | --- | --- |
| `TextField` 등 일반 scalar field | `scalar_text` | builtin direct 또는 custom `FieldValue` | 지원 |
| `BoolField` | `scalar_bool` | builtin bool 또는 custom `BoolFieldValue` | 지원 |
| `OptionChoiceField` + `options` | `static_option` | option name -> reference payload | 지원 |
| `UserChoiceField` | `user_reference` | 사용자 이름 우선 lookup, 숫자면 ID fallback | 지원 |
| `ReferenceField` + `referenceType=UserReference` | `user_reference` | 위와 동일 | 지원 |
| `MemberField` | `member_reference` | `USER/ROLE/GROUP` mixed lookup | 지원 |
| `TrackerItemChoiceField` | `tracker_item_reference` | tracker item ID direct parse | 지원 |
| builtin `subjects` + `TrackerItemReference` | `tracker_item_reference` | tracker item ID direct parse | 지원 |
| `TableField` | `table` | `TableFieldName.ColumnName` 헤더를 묶어 `TableFieldValue` 생성 | 지원 |
| `ReferenceField` + 일반 `referenceType` | `generic_reference` | resolver 없음, 조기 실패 | 부분 지원 |
| `ReferenceField` + `referenceType` 없음 | `generic_reference` | 어떤 reference인지 확정 불가 | 미지원 |
| `OptionChoiceField`인데 `options/referenceType` 없음 | `unsupported` | choice 계열 여부만으로는 해석 안 함 | 미지원 |
| `Status` | `static_option` 또는 builtin reference | option 이름 매핑까지만 가능 | TODO 존재 |

## 값 해석 규칙

### 정적 option field

- schema의 `options` 배열을 사용한다.
- Excel 값은 option `name`과 일치해야 한다.
- 결과는 `{id, name, type}` 형태의 reference 또는 `ChoiceFieldValue(values=[...])` 로 들어간다.
- option 이름이 중복되면 안전하지 않으므로 unsupported 처리한다.

### 사용자 field

대상:

- `UserChoiceField`
- `ReferenceField` with `referenceType=UserReference`

규칙:

1. 입력값을 문자열로 정규화한다.
2. 먼저 `GET /v3/users/findByName` 으로 이름 조회를 시도한다.
3. 실패했고 입력값이 순수 숫자면 `GET /v3/users/{id}` 로 fallback 한다.
4. 성공하면 최소 구조 `{id, name, type="UserReference"}` 로 저장한다.
5. 같은 프로젝트 안에서는 이름/ID 별칭 기준으로 캐시한다.

lookup 결과 부가 컬럼:

- `{df_col}__resolved`
- `{df_col}__user_info`
- `{df_col}__lookup_status`
- `{df_col}__lookup_error`

### `MemberField`

현재 구현은 `USER/ROLE/GROUP` 혼합 field로 처리합니다.

규칙:

- `USER`: 사용자 lookup 재사용
- `ROLE`: `GET /v3/trackers/{trackerId}/fields/{fieldId}/permissions` 에서 role 후보 추출
- `GROUP`: `GET /v3/users/groups` 에서 group 후보 추출
- 이름 기준으로 매칭하고, 결과는 `UserReference`, `RoleReference`, `GroupReference`, `UserGroupReference` 중 하나로 직렬화한다.

실패 조건:

- 후보 없음: `MEMBER_NOT_FOUND`
- 여러 후보 중복: `MEMBER_LOOKUP_AMBIGUOUS`
- API 조회 실패: `MEMBER_LOOKUP_FAILED`

### tracker item reference field

대상:

- `TrackerItemChoiceField`
- builtin `subjects`

규칙:

- `TrackerItemChoiceField` 는 tracker configuration 의 `fields` 목록에서 `referenceId == schema.field_id` 를 우선 매칭한다.
- 이름·summary query lookup은 대량 검증의 API 호출을 줄이기 위해 비활성화되어 있다.
- 입력값에서 item ID를 직접 추출한다.
- builtin `subjects` 는 현재 direct parse만 사용한다.
- 우선 순위:
  1. `dict.id`
  2. `[:123]` 패턴
  3. `[123]` 패턴
  4. 순수 숫자 문자열
  5. `123.0` 형태 숫자 문자열

결과:

- 단일 값: `{id, type="TrackerItemReference"}`
- 다중 값: 위 구조의 list

### `TableField`

규칙:

- Excel 헤더가 `TableFieldName.ColumnName` 패턴이면 table column 후보로 인식한다.
- 현재 구현은 한 row에서 table field별로 1개의 table row를 조립한다.
- 값이 하나라도 있으면 `customFields` 안에 `TableFieldValue` 로 들어간다.

예시 payload 조각:

```json
{
  "fieldId": 5,
  "name": "체크리스트",
  "type": "TableFieldValue",
  "values": [
    [
      {
        "fieldId": 501,
        "name": "결과",
        "value": "PASS",
        "type": "TextFieldValue"
      }
    ]
  ]
}
```

## payload 생성 규칙

### builtin field와 custom field 구분

`trackerItemField` 가 `TrackerItemBase`의 내장 속성과 매핑되면 builtin field로 처리합니다.

추가 규칙:

- schema의 `assignedTo` 같은 camelCase 이름은 내부에서 `assigned_to` 같은 snake_case 속성으로 정규화합니다.
- 즉 builtin 판정은 raw `trackerItemField` 문자열과 내부 dataclass 속성 이름이 완전히 같을 필요는 없습니다.

대표 builtin field:

- `name`
- `description`
- `status`
- `priority`
- `categories`
- `assignedTo`
- `subjects`
- `versions`
- `teams`

그 외 `field_id` 와 `field_name` 이 있는 field는 custom field로 처리할 수 있습니다.

### custom field에 연결된 `FieldValue`

현재 코드에 실제 구현이 연결된 value type:

- `TextFieldValue`
- `BoolFieldValue`
- `ColorFieldValue`
- `CountryFieldValue`
- `DateFieldValue`
- `DecimalFieldValue`
- `DurationFieldValue`
- `IntegerFieldValue`
- `LanguageFieldValue`
- `UrlFieldValue`
- `WikiTextFieldValue`
- `ChoiceFieldValue`
- `TableFieldValue`

### payload 생성 전 점검

payload 생성 전에 아래를 검사합니다.

- field 자체가 지원되는가
- lookup이 필요한 field인데 resolver가 실행됐는가
- direct parse가 가능한가
- option/source 규칙이 준비됐는가

문제가 있으면 payload 단계에서 늦게 깨지지 않도록 아래 코드들로 조기 실패합니다.

- `FIELD_UNSUPPORTED`
- `LOOKUP_REQUIRED`
- `DIRECT_PARSE_FAILED`
- `OPTION_RESOLUTION_FAILED`

### payload cache

- 각 `_row_id`마다 `payload_json`, `payload_status`, `payload_error`를 저장한다.
- `preview_payload()` 와 `upload()` 는 같은 `payload_df` cache를 재사용한다.
- 입력, schema, 매핑이 바뀌면 payload cache를 무효화한다.

## 업로드 실행 규칙

### parent-first 업로드

- 업로드 순서는 `_row_id` 와 `parent_row_id` 관계를 따른다.
- 실제 `parentItemId` 는 업로드 시점에 `created_map[parent_row_id]` 로 결정한다.
- 부모가 실패하면 자식은 `UNRESOLVED_PARENT` 로 남긴다.

### 에러 기록

업로드 실패 시 아래 정보를 남깁니다.

- `error_status_code`
- `error_response_json`
- `error`
- `status=UPLOAD_FAILED`

### 저장 산출물

현재 `save_state()` 가 남길 수 있는 주요 파일:

- `raw_df.csv`
- `merged_df.csv`
- `hierarchy_df.csv`
- `upload_df.csv`
- `converted_upload_df.csv`
- `payload_df.csv`
- `schema_df.csv`
- `comparison_df.csv`
- `option_check_df.csv`
- `schema.json`
- `option_maps.json`
- `payload_preview.jsonl`
- `success_df.csv`
- `failed_df.csv`
- `unresolved_df.csv`
- `failed_responses.jsonl`
- `created_map.json`

## 다른 프로젝트에서 재사용할 권장 데이터셋

다른 업로더 프로젝트에서 아래 구조를 tracker 단위 snapshot으로 보관하는 것을 권장합니다.

```json
{
  "codebeamer_upload_reference_version": "2026-06-17",
  "server_contract": {
    "base_url": "https://your-codebeamer-host/cb",
    "auth": "basic"
  },
  "project": {
    "project_id": 101
  },
  "tracker": {
    "tracker_id": 202,
    "schema_snapshot": [],
    "builtin_field_map": {},
    "table_field_headers": ["체크리스트.결과"]
  },
  "input_contract": {
    "summary_column": "요약",
    "indent_source": "Excel IndentLevel with leading-spaces fallback",
    "list_columns_are_schema_driven": true,
    "table_header_pattern": "TableFieldName.ColumnName"
  },
  "lookup_contract": {
    "user_lookup": [
      "GET /v3/users/findByName",
      "GET /v3/users/{id}"
    ],
    "member_lookup": [
      "GET /v3/users/groups",
      "GET /v3/trackers/{trackerId}/fields/{fieldId}/permissions"
    ],
    "tracker_item_reference": "direct parse"
  },
  "known_limitations": [
    "generic reference resolver 없음",
    "Status transition 후처리 미구현"
  ]
}
```

핵심은 "schema 원본"만 저장하는 것이 아니라, 해석 결과까지 함께 저장하는 것입니다.

권장 저장 항목:

- schema 원본 JSON
- flatten된 `schema_df`
- field별 `resolved_field_kind`
- field별 `preconstruction_kind`
- field별 `payload_target_kind`
- option map
- lookup 필요 여부
- 미지원 사유

## 현재 확인된 한계와 TODO

### 1. 일반 reference field 범용 resolver 부재

현재는 아래만 자동 해석됩니다.

- static option
- user reference
- member reference
- tracker item direct parse

그 외 reference type은 tracker별 별도 lookup 설계가 필요합니다.

### 2. `Status` transition 처리 미구현

현재는 `Status.options` 기준 이름 매핑은 가능하지만,
실제 workflow transition 제약을 반영한 create 후 transition 로직은 없습니다.

즉:

- "최종 상태를 생성 payload에 직접 넣어도 되는지"는 아직 보장되지 않습니다.
- 실서비스용으로는 transition API 또는 workflow 규칙 추가 조사가 필요합니다.

### 3. table row 다건 조립

선택적 `Upload Record Key` 열을 사용하면 같은 키의 연속된 원본 행을 한 upload row로 병합합니다.
각 원본 행은 `TableFieldName.ColumnName` 열의 한 table row가 되며 원본 순서와 빈 셀 위치를 보존합니다.
일반 필드는 그룹의 첫 행 값을 사용하며 다른 행의 값이 공백을 포함해 다르면 검증 오류로 차단합니다.

### 4. schema가 모호한 choice/reference field는 fallback 하지 않음

이 프로젝트는 잘못된 payload를 만들 가능성이 있으면 억지로 문자열 fallback을 하지 않습니다.
다른 프로젝트에서도 이 원칙을 유지하는 편이 안전합니다.

## 구현 시작 전 체크리스트

- [ ] 대상 tracker의 schema JSON을 확보했다.
- [ ] 각 field의 `type`, `referenceType`, `options`, `multipleValues`, `valueModel` 을 확인했다.
- [ ] summary 컬럼과 들여쓰기 규칙을 확정했다.
- [ ] list 컬럼이 schema의 `multipleValues` 와 맞는지 확인했다.
- [ ] 사용자, 그룹, role lookup 경로를 확인했다.
- [ ] tracker item reference 입력 문자열 규칙을 합의했다.
- [ ] `Status` 를 생성 시 바로 넣을지, 후처리 transition으로 옮길지 결정했다.
- [ ] 미지원 reference field가 있는지 확인했다.
- [ ] payload preview와 실제 upload가 같은 cache를 재사용하도록 설계했다.
- [ ] 실패 응답 JSON을 저장하도록 설계했다.
