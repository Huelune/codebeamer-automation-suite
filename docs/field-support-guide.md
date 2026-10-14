# 필드 지원 추가 가이드

## 목적

이 문서는 새로운 Codebeamer schema field를 업로드 파이프라인에서 지원하려고 할 때,
어느 지점을 어떻게 수정해야 하는지 정리한 구현 가이드입니다.

대상 경로:

- `src/mapping_service.py` (public facade)
- `src/mapping_reference.py`
- `src/mapping_schema.py`
- `src/mapping_option.py`
- `src/wizard.py` (public facade)
- `src/wizard_data.py`
- `src/wizard_user_lookup.py`
- `src/wizard_tracker_lookup.py`
- `src/wizard_payload.py`
- `src/wizard_operations.py`
- `src/models/tracker_item.py`
- `src/models/field_values.py`
- `src/models/common.py`
- `tests/`

핵심 원칙:

- raw schema의 `type`을 1차 기준으로 본다.
- `referenceType`, `options`, `multipleValues`로 세분화한다.
- `valueModel`은 보조 신호로만 쓴다.
- 모호하면 늦게 실패하지 말고 더 일찍 `unsupported`로 드러낸다.
- 어떤 필드든 payload 생성 전에 무엇을 먼저 구성해야 하는지 명시해야 한다.

## 현재 지원 흐름 요약

현재 파이프라인은 schema field를 다음 순서로 처리합니다.

1. `flatten_schema_fields()`가 raw schema를 평탄화한다.
2. `_resolve_field_kind()`가 내부 분류를 결정한다.
3. `_resolve_preconstruction()`이 lookup 필요 여부와 payload 선구성 규칙을 결정한다.
4. `compare_upload_df_with_schema()`가 비교 결과에 위 정보를 노출한다.
5. `build_option_maps_from_schema()`와 `check_option_alignment()`가 조기 검증을 수행한다.
6. `wizard.preview_payload()`가 분류 결과를 사용해 payload를 생성하거나 조기 실패한다.
7. `TrackerItemBase.set_field_value()`가 builtin / custom / reference / field value 경로를 실제 payload에 반영한다.

즉, 새 필드 지원은 `mapping_service`만 고쳐서는 끝나지 않습니다.
최소한 schema 해석, validation, payload 생성, 테스트까지 함께 맞춰야 합니다.

## 새 필드 지원 전 확인할 정보

새 field type을 지원하려면 먼저 실제 schema 샘플에서 아래를 확인해야 합니다.

- `type`
- `referenceType`
- `options`
- `multipleValues`
- `valueModel`
- type 전용 부가 속성
  예: `memberTypes`, `columns`, `trackerItemField`

특히 아래 두 경우는 별도 설계가 필요합니다.

- 같은 `type`인데 tracker마다 의미가 달라지는 경우
- `valueModel`은 choice 계열인데 `referenceType`이나 `options`가 없는 경우

이 경우 `valueModel`만으로 억지 해석하면 나중에 잘못된 payload가 만들어질 수 있습니다.

## 구현 순서

### 1. 먼저 내부 의미를 정의한다

raw schema type을 그대로 코드 전역에 퍼뜨리지 말고,
먼저 내부 의미를 아래 세 축으로 정리합니다.

- `resolved_field_kind`
- `preconstruction_kind`
- `payload_target_kind`

필요시 함께 정해야 하는 값:

- `resolution_strategy`
- `requires_lookup`
- `lookup_target_kind`
- `preconstruction_detail`
- `unsupported_reason`

현재 내부 분류 예시:

- `scalar_text`
- `scalar_bool`
- `static_option`
- `user_reference`
- `tracker_item_reference`
- `generic_reference`
- `table`
- `unsupported`

새 필드가 기존 의미로 표현 가능하면 새 enum을 늘리지 않는 편이 낫습니다.
반대로 기존 의미로 설명이 안 되면 `src/models/common.py`에 내부 enum을 추가합니다.

권장 판단 질문:

1. 이 필드는 text/bool/table/option/reference 중 어디에 가까운가
2. 이 필드는 payload에 raw scalar를 바로 넣을 수 있는가
3. 먼저 `FieldValue`를 만들어야 하는가
4. 먼저 `Reference` 또는 `Reference` list를 만들어야 하는가
5. lookup이 필요한가
6. lookup 대상이 user인지, generic reference인지, 다른 별도 타입인지

### 2. `mapping_service`에 type 분기를 추가한다

수정 위치:

- `MappingService._resolve_field_kind()`
- 필요 시 `SchemaFieldType`

원칙:

- 반드시 `type` 분기를 먼저 추가한다.
- 그 안에서 `referenceType`, `options`, `multipleValues`를 본다.
- `valueModel`은 마지막 보조 검증으로만 사용한다.

예시 질문:

- `MemberField`를 `USER/ROLE/GROUP` mixed field로 볼 것인가
- `TrackerItemChoiceField` 입력값에서 ID를 안전하게 추출할 수 있는가
- `referenceType`이 없을 때도 안전하게 결정 가능한가

안전하게 결정할 수 없으면 이 단계에서 `unsupported`로 남겨야 합니다.

### 3. `preconstruction` 규칙을 정한다

수정 위치:

- `MappingService._resolve_preconstruction()`

반드시 아래 중 하나로 귀결되어야 합니다.

- `none`
- `builtin_direct`
- `field_value`
- `reference`
- `reference_list`
- `table_field_value`

그리고 `preconstruction_detail`에 실제 구성 대상을 남깁니다.

예시:

- `TextFieldValue`
- `BoolFieldValue`
- `ChoiceFieldValue<UserReference>`
- `UserReference`
- `ChoiceOptionReference`
- `generic reference candidate`

이 값은 문서용이 아니라 실제 디버깅과 validation 메시지에 쓰입니다.

### 4. payload target을 정한다

수정 위치:

- `MappingService._resolve_payload_target_kind()`
- 필요 시 `TrackerItemBase.has_builtin_field()`

이 필드가 어디로 들어가는지 먼저 확정해야 합니다.

- `builtin_field`
- `custom_field`
- `unsupported`

주의:

- `trackerItemField`가 있다고 항상 안전한 builtin은 아닙니다.
- 반대로 `trackerItemField`가 없어도 custom field로는 지원 가능할 수 있습니다.
- builtin으로 분류되면 `TrackerItemBase`가 실제로 해당 속성을 처리할 수 있어야 합니다.

### 5. validation과 option map을 같이 맞춘다

수정 위치:

- `MappingService.build_option_maps_from_schema()`
- `MappingService.check_option_alignment()`
- 필요 시 `_detect_option_source_kind()`

해야 할 일:

- 새 field가 `static_option`, `user_reference`, `generic_reference`, `unsupported` 중 어디인지 반영
- resolver가 아직 없으면 조용히 넘기지 말고 상태로 남김
- 조기 검출 메시지에 `unsupported_reason`, `requires_lookup`, `preconstruction_kind`를 포함

현재 상태값은 대략 아래 의미로 씁니다.

- `FIELD_UNSUPPORTED`: 현재 구현으로 안전하게 지원할 수 없음
- `LOOKUP_REQUIRED`: resolver가 필요하지만 아직 해결되지 않음
- `PRECONSTRUCTION_REQUIRED`: 정상 지원 대상이지만 payload 전에 선구성이 필요함
- `OPTION_NOT_FOUND`: schema option과 업로드 값이 맞지 않음

### 6. `wizard`에서 실제 resolver와 예외 경로를 연결한다

수정 위치:

- `CodebeamerUploadWizard.process_option_mapping()`
- `CodebeamerUploadWizard._resolve_option_field_value()`
- `CodebeamerUploadWizard.preview_payload()`
- 필요 시 별도 lookup helper

해야 할 일:

- 새 field가 lookup 대상이면 실제 resolver를 추가
- resolver 결과를 `__resolved`, 필요하면 부가 컬럼에 저장
- resolver가 없으면 payload 생성 전에 구조화된 예외로 실패
- `unsupported`는 왜 unsupported인지 메시지에 포함

현재 원칙:

- `UserReference`, `UserChoiceField`는 사용자 이름 우선 resolver가 있으므로 지원
- `MemberField`는 `USER/ROLE/GROUP` mixed resolver가 있으므로 지원
- `TrackerItemChoiceField`는 정규식 tracker item ID parser만 쓰므로 ID가 들어 있는 값만 지원(이름·summary query 조회는 비활성화)
- `generic_reference`는 resolver가 없으므로 조기 실패
- 모호한 필드는 text fallback으로 넘기지 않음

### 7. `TrackerItemBase`와 `FieldValue` 모델을 맞춘다

수정 위치:

- `TrackerItemBase._set_builtin_field()`
- `TrackerItemBase.set_field_value()`
- `TrackerItemBase._create_field_value()`
- `src/models/field_values.py`
- 필요 시 `src/models/references.py`

체크 포인트:

- builtin direct면 coercion 규칙이 있는가
- custom field면 올바른 `FieldValue` builder가 있는가
- reference면 `_build_reference()`가 필요한 타입을 만들 수 있는가
- multiple value면 list 처리 규칙이 맞는가

새 field가 새로운 `FieldValue` subclass를 요구하면
`field_values.py` registry에 맞는 모델을 추가해야 합니다.

### 8. 테스트를 반드시 추가한다

최소 테스트 위치:

- `tests/test_mapping_service.py`
- 필요 시 `tests/test_payload_preconstruction.py`
- lookup이 있으면 `tests/test_wizard_user_lookup.py` 또는 신규 테스트 파일

권장 테스트 항목:

- schema flatten 결과의 `resolved_field_kind`
- `is_supported`, `unsupported_reason`
- `requires_lookup`, `lookup_target_kind`
- `preconstruction_kind`, `preconstruction_detail`
- option map 상태
- preview 단계 조기 실패 또는 정상 payload 생성

## 구현 체크리스트

새 field 지원 시 아래를 순서대로 확인합니다.

- [ ] 실제 schema 샘플을 확보했다
- [ ] `type` 기준 해석 규칙을 문장으로 먼저 정의했다
- [ ] `resolved_field_kind`를 결정했다
- [ ] `payload_target_kind`를 결정했다
- [ ] `preconstruction_kind`와 `preconstruction_detail`을 결정했다
- [ ] lookup 필요 여부와 lookup 대상 종류를 결정했다
- [ ] resolver가 없으면 `unsupported` 또는 `LOOKUP_REQUIRED`로 조기 실패하게 했다
- [ ] `wizard.preview_payload()`에서 실제로 그 규칙을 따르는지 확인했다
- [ ] 테스트를 추가했다
- [ ] 필요하면 CLI 안내 문구도 함께 수정했다

## `MemberField` 처리 규칙

현재 구현은 `MemberField`를 `USER/ROLE/GROUP` mixed field로 지원합니다.

예시 스키마:

- `type=MemberField`
- `valueModel=ChoiceFieldValue`
- `multipleValues=true`
- `memberTypes=[USER, ROLE, GROUP]`

현재 파이프라인의 규칙:

- 입력값은 이름 기반으로 해석합니다.
- `USER` 는 `findByName` 으로 조회하고, 숫자 입력이면 `GET /v3/users/{id}` fallback 을 씁니다.
- `ROLE` 은 `GET /v3/trackers/{trackerId}/fields/{fieldId}/permissions` 에서 role 후보를 모아 이름으로 찾습니다.
- `GROUP` 은 `GET /v3/users/groups` 전체 목록을 가져와 이름으로 찾습니다.
- 결과는 `ChoiceFieldValue(values=[...])` 안에 `UserReference`, `RoleReference`, `GroupReference` / `UserGroupReference` 로 들어갑니다.

주의:

- 같은 이름이 여러 타입 또는 여러 객체에 걸쳐 겹치면 `MEMBER_LOOKUP_AMBIGUOUS` 로 실패합니다.
- 이름이 없으면 `MEMBER_NOT_FOUND` 로 실패합니다.

## `TrackerItemChoiceField` 처리 규칙

현재 구현은 `TrackerItemChoiceField` 를 입력값의 ID direct parse로 처리합니다.

규칙:

- tracker configuration 의 `fields` 목록에서 `referenceId == schema.field_id` 를 우선 매칭합니다.
- 이름·summary query lookup은 대량 검증 시 API 호출을 줄이기 위해 비활성화되어 있습니다.
- 입력값에서 tracker item ID를 직접 추출합니다.
- 단일 값 또는 list 모두 허용합니다.
- 각 값에서 `[:id]` 패턴을 먼저, 없으면 `[]` 안 첫 번째 integer를 사용합니다.
- `dict` 입력이면 `id` 값을 우선 사용합니다.
- 결과는 `TrackerItemReference(id=<int>, type="TrackerItemReference")` 로 변환합니다.

builtin `subjects` 는 현재 direct parse 규칙만 사용합니다.

주의:

- configuration의 source tracker 정보와 무관하게 ID 추출 규칙을 적용합니다.

## `Status` 처리 규칙

현재 구현은 `Status` 를 schema option 기준으로만 해석하고 있으며,
workflow transition 제약을 반영한 단계별 상태 전이는 아직 구현되지 않았습니다.

즉 현재 상태:

- `Status.options` 로 이름 매핑은 가능
- 하지만 생성 시 마지막 상태를 바로 넣는 것은 workflow-safe 하지 않음
- create 후 transition 기반 후처리로 옮겨야 함

따라서 `Status` 는 현재 TODO 로 관리합니다.

## 피해야 할 구현 방식

- `valueModel`만 보고 무조건 `ChoiceFieldValue`로 처리
- resolver가 없는데도 text fallback으로 payload를 생성
- builtin/custom 판정 없이 `setattr()`에 바로 넣기
- lookup 실패를 preview/upload 단계까지 끌고 가기
- `unsupported_reason` 없이 단순 실패시키기

이 방식들은 처음에는 빨라 보여도 실제 업로드 데이터에서 더 늦고 더 비싸게 터집니다.

## 권장 작업 순서

새 field 하나를 지원할 때는 아래 순서가 가장 안전합니다.

1. schema 샘플 확보
2. 내부 의미 정의
3. `mapping_service` 분류 추가
4. preconstruction / payload target 확정
5. validation 상태 추가 또는 연결
6. resolver / payload 생성 경로 구현
7. 테스트 추가
8. CLI와 문서 업데이트

## 관련 코드 경로

- `src/mapping_service.py` (public facade)
- `src/mapping_reference.py`
- `src/mapping_schema.py`
- `src/mapping_option.py`
- `src/wizard.py` (public facade)
- `src/wizard_data.py`
- `src/wizard_user_lookup.py`
- `src/wizard_tracker_lookup.py`
- `src/wizard_payload.py`
- `src/wizard_operations.py`
- `src/models/common.py`
- `src/models/tracker_item.py`
- `src/models/field_values.py`
- `src/models/references.py`
- `tests/test_mapping_service.py`
- `tests/test_payload_preconstruction.py`
