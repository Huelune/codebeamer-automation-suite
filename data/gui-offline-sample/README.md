# GUI 오프라인 테스트용 예시 데이터

이 폴더는 GUI `테스트 모드`를 서버 없이 검증할 때 바로 사용할 수 있는 샘플 세트입니다.

포함 파일:

- `offline_schema.json`
  - 오프라인 트래커 schema snapshot
- `offline_tracker_items.json`
  - 두 tracker의 최상위·하위 아이템, 상세 필드와 검색 결과를 포함한 익명 조회 snapshot
- `files/SAMPLE_MODULE_A_TC_001.xlsx`
  - 정상 Dry Run 예시 1
- `files/SAMPLE_MODULE_B_TC_002.xlsx`
  - 정상 Dry Run 예시 2
- `files/SAMPLE_LOOKUP_TC_003.xlsx`
  - lookup 실패와 검증 이슈를 의도적으로 보여주는 예시

권장 빠른 테스트 순서:

1. GUI 실행 후 설정 화면에서 `테스트` 토글을 켭니다.
2. `Schema Snapshot`에 `data/gui-offline-sample/offline_schema.json`을 선택합니다.
3. `조회 데이터 Snapshot`에 `data/gui-offline-sample/offline_tracker_items.json`을 선택합니다.
4. `트래커 작업공간`에서 프로젝트와 트래커가 자동으로 채워지는지 확인하고 계층 노드를 펼칩니다.
   - `수정` 탭은 schema 기반 입력 구조와 Status options를 표시합니다.
   - 테스트 모드이므로 저장, 상태 필드 변경과 삭제 버튼은 비활성화됩니다.
5. 배치 작업의 프로젝트 단계로 이동하면 테스트 프로젝트와 트래커가 자동으로 채워집니다.
6. 파일 단계에서 `SAMPLE_MODULE_A_TC_001.xlsx`, `SAMPLE_MODULE_B_TC_002.xlsx`를 함께 선택합니다.
7. `Sheet Name`은 `Upload`, `Header Row`는 `1`로 맞추고 `선택 시트 미리보기`를 누릅니다.
   미리보기에서 `Summary Column`을 `Summary`로 고른 뒤 `전체 데이터 불러오기`를 누릅니다.
8. 상단 데이터 단계는 두 가지 중 하나로 진행합니다.
   - 루트 parent item이 필요 없으면 `파일별 최상단 폴더 생성`을 끄고 넘어갑니다.
   - 루트 parent item을 만들고 싶으면 기본 summary source를 파일명으로 두고, 필요 시 정규식 미리보기만 확인합니다.
9. 첫 Dry Run에서는 아래 컬럼 위주로 매핑하면 서버 lookup 없이 끝까지 확인할 수 있습니다.
   - `Summary`
   - `Description`
   - `Priority`
   - `Approved`
   - `Verification Stage`
   - `Test Steps.Action`
   - `Test Steps.Expected result`
   - `Test Steps.Critical`
   - `Related Requirement`
10. `Related Requirement`는 기본 regex ID 추출 방식으로 처리합니다. 이름·summary query 조회는 지원하지 않습니다.
   - 샘플 값은 `[REQ:9001001]` 같은 형식이라 기본 regex로 바로 인식됩니다.
11. `Owner`, `Review Team`은 오프라인 snapshot에 사용자/그룹 디렉터리가 없으므로 첫 성공 경로에서는 매핑하지 않는 편이 맞습니다.
12. 업로드 단계에서는 `Dry Run`을 켠 상태로만 진행할 수 있습니다.

조회 snapshot의 tracker 범위:

- `Offline Requirements` (`24680001`): 2개 최상위 아이템과 2단계 하위 구조
- `Offline Test Cases` (`24680002`): 별도 최상위·하위 구조
- 같은 검색어를 두 tracker에서 실행해 결과가 현재 tracker 밖으로 섞이지 않는지 확인할 수 있습니다.

이슈 화면 확인용 샘플:

- `files/SAMPLE_LOOKUP_TC_003.xlsx`
  - `Owner`, `Review Team`에 실제 값이 들어 있어 lookup 실패와 차단 경고를 확인하기 좋습니다.
  - `Related Requirement`에는 ID 없이 이름만 적은 값이 있어, 정규식으로 ID를 뽑지 못해 차단되는 흐름을 볼 수 있습니다.

파일명 파싱 테스트 팁:

- 정규식 대상의 기본값은 확장자를 뺀 파일명입니다. 정규식 없이도 summary에 `SAMPLE_MODULE_A_TC_001`처럼 들어갑니다.
- 샘플 파일명은 `SAMPLE_<MODULE>_TC_<번호>.xlsx` 규칙이라 미리보기 검증에도 적합합니다.
- 예: `^SAMPLE_(?P<module>[A-Z_]+)_TC_(?P<case_no>\d+)$`
  - `SAMPLE_MODULE_A_TC_001.xlsx` 에서는 `module=MODULE_A`, `case_no=001`
