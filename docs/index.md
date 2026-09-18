# 문서 허브

`Codebeamer Automation Suite` 문서의 시작점입니다.

## 권장 읽기 순서

1. [README](../README.md)
2. [기능 현황](./feature-status.md)
3. [아키텍처](./architecture.md)
4. [Codebeamer 업로드 조사 정리](./codebeamer-upload-reference.md)
5. [Codebeamer 프로젝트 시작 패키지](./codebeamer-project-start-kit.md)
6. [CLI 사용 가이드](./cli-guide.md)
7. [필드 지원 추가 가이드](./field-support-guide.md)
8. [GUI 사용 가이드](./gui-plan.md)
9. [트래커 작업공간 GUI 기획 및 스토리보드](./tracker-workspace-gui-storyboard.md)
10. [트래커 조회 서비스 계약](./tracker-query-service.md)
11. [트래커 아이템 단건 생성·수정·상태 전환·삭제](./tracker-item-editor.md)
12. [통합 실행 기록](./activity-history.md)
13. [Codebeamer API 모니터](./api-monitor.md)
14. [개발자 도구와 진단 패키지](./developer-tools.md)
15. [트러블슈팅](./troubleshooting.md)

## 감사·이력 문서

현재 동작을 파악하는 데 필수는 아니지만 판단 근거로 보존하는 문서입니다.

- [호환 경로 감사](./compatibility.md)
- [샘플 데이터 및 자격증명 감사](./security-audit.md)
- [GUI 오류 처리 감사](./gui-error-handling.md)
- [GUI 리팩토링 진행 및 검증 기록](./refactoring-progress.md) (완료된 작업 기록)
- [v2 변경 사항](./v2-changes.md) (완료된 작업 기록)

## 개발 환경과 검증

가상환경 생성, 의존성 설치, lint·type check·테스트 실행 명령은 [README의 빠른 시작](../README.md#빠른-시작)에 있습니다.
lint 규칙과 type check 범위는 저장소 루트 `pyproject.toml`에 정의되어 있고, GitHub Actions의
`Lint and type check`, `Regression tests` job이 같은 명령을 실행합니다.

## 문서별 역할

- [README](../README.md)
  저장소 소개, 빠른 시작, 개발 환경 준비와 현재 기본 실행 경로를 요약합니다.

- [기능 현황](./feature-status.md)
  `main` 기준으로 동작하는 핵심 기능, 화면 단위 구현 범위와 최근 보완 사항을 모아 둡니다.

- [아키텍처](./architecture.md)
  코드 구조, 모듈 책임, 상태 모델, 최신 업로드 순서도를 설명합니다.

- [Codebeamer 업로드 조사 정리](./codebeamer-upload-reference.md)
  다른 프로젝트에서 재사용할 수 있도록 Codebeamer 업로드에 필요한 API, schema 규칙, payload 규칙, 한계를 한 문서로 묶었습니다.

- [Codebeamer 프로젝트 시작 패키지](./codebeamer-project-start-kit.md)
  live tracker schema export와 시작 템플릿을 함께 사용하는 권장 시작 절차를 정리합니다.

- [CLI 사용 가이드](./cli-guide.md)
  실행 방법, Excel 입력 형식, 자동 매핑과 자동 list 컬럼 선택 흐름을 설명합니다.

- [필드 지원 추가 가이드](./field-support-guide.md)
  새로운 schema field type 또는 reference field를 지원할 때 수정해야 하는 코드 경로와 구현 순서를 설명합니다.

- [GUI 사용 가이드](./gui-plan.md)
  최상위 앱 셸, 배치 작업의 실제 단계별 사용 흐름, 테스트 모드, 다중 파일 업로드, 상단 데이터 설정, 현재 구현 범위를 정리합니다.
- [GUI 오류 처리 감사](./gui-error-handling.md)
  Qt 슬롯, 백그라운드 worker, 사용자 입력과 보조 저장 경로의 오류 표시·정리 계약을 정리합니다.
- [트래커 조회 서비스 계약](./tracker-query-service.md)
  tracker 범위 검색, 계층·상세·ID 경로 모델, pagination 차이와 익명 조회 fixture 계약을 정리합니다.
- [트래커 아이템 단건 생성·수정·상태 전환·삭제](./tracker-item-editor.md)
  schema 기반 단건 생성과 부분 수정, version 충돌 확인, Status 필드 변경과 삭제 안전장치를 정리합니다.
- [통합 실행 기록](./activity-history.md)
  단건 쓰기와 배치 결과의 로컬 저장 범위, 필터, 보안 경계와 현재 제한을 정리합니다.
- [Codebeamer API 모니터](./api-monitor.md)
  개발자용 실시간 호출 통계, 표 사용법, 재시도 표시와 메타데이터 수집 보안 경계를 정리합니다.
- [개발자 도구와 진단 패키지](./developer-tools.md)
  세션 진단 로그, 진단 ID, API 모니터 재사용, ZIP 내보내기와 개인정보 제외 계약을 정리합니다.
- [Wiki 형식 조회 렌더링](./wiki-rendering.md)
  설명과 TableField에서 명시적 Wiki 메타데이터만 렌더링하는 판정 규칙, 지원 문법과 보안 경계를 정리합니다.

- [트래커 작업공간 GUI 기획 및 스토리보드](./tracker-workspace-gui-storyboard.md)
  조회 중심 작업공간의 정보 구조, 화면 흐름, 단계별 구현 범위와 브랜치 전략을 정리한 설계 기준입니다.

- [트러블슈팅](./troubleshooting.md)
  자주 발생하는 에러와 대응 방법을 정리합니다.

- [호환 경로 감사](./compatibility.md)
  과거 entry point와 Excel wrapper의 사용 여부, 유지 근거, 제거 조건을 기록합니다.

- [샘플 데이터 및 자격증명 감사](./security-audit.md)
  offline sample과 fixture의 익명화, 자격증명 파일 추적 여부, 자동 회귀 검사를 기록합니다.

- [GUI 리팩토링 진행 및 검증 기록](./refactoring-progress.md)
  책임 분리 결과, 자동 테스트, 일반·최대화 창과 테마를 포함한 수동 GUI 검증 근거를 기록합니다.

- [v2 변경 사항](./v2-changes.md)
  예전 `v2` 도입 배경과 이후 원본 경로에 반영된 주요 개선 이력을 기록합니다.

## UML 및 흐름 문서

- [클래스/의존 관계 UML](./class-diagram.puml)
- [업로드 시퀀스 UML](./upload-sequence.puml)
- [UML 렌더링 가이드](./render-uml.md)
- 최신 mermaid 업로드 순서도는 [아키텍처 문서](./architecture.md)에 포함되어 있습니다.

## 현재 기준 권장 코드 경로

- `gui_main.py`
- `src/gui/main_window.py`
  접이식 좌측 메뉴를 포함한 최상위 앱 셸과 작업 영역 전환을 담당합니다.
- `src/gui/batch_window.py`
  기존 9단계 create/update/upsert 마법사를 보존합니다.
- `src/gui/settings_center.py`
  다중 연결 profile, 화면, 네트워크·저장소, 테스트 모드, 개발자 기능과 설정 데이터 관리를 담당합니다.
- `src/api_monitor.py`, `src/gui/api_monitor_window.py`
  API 호출 메타데이터의 제한된 메모리 수집과 실시간 통계·필터 창을 담당합니다.
- `src/diagnostics.py`, `src/gui/developer_tools_window.py`
  구조화 진단 이벤트, 안전한 ZIP 내보내기와 확장 가능한 개발자 도구 탭 창을 담당합니다.
- `src/gui/tracker_query_models.py`, `src/gui/tracker_query_service.py`
  tracker 범위 검색, pagination, 계층·상세·ID 경로의 UI 독립 조회 계약을 담당합니다.
- `src/gui/tracker_workspace.py`
  프로젝트·트래커 선택, 지연 로딩 확장형 트리, tracker 검색, ID 직접 접근과 상세 표시를 담당합니다.
- `src/gui/tracker_item_editor.py`, `src/gui/tracker_item_editor_panel.py`
  선택 필드 부분 수정, Status 필드 변경, 삭제 계약과 schema 기반 입력 UI를 담당합니다.
- `src/gui/page_batch_settings.py`
  전역 설정과 분리된 배치 작업 mode 및 Excel 해석 기준을 담당합니다.
- `cli_main.py`
  유지보수와 보조 실행 경로입니다.
- `src/mapping_service.py`
  facade이며 실제 schema/reference/option 로직은 `src/mapping_reference.py`, `src/mapping_schema.py`, `src/mapping_option.py` 로 분리되어 있습니다.
- `src/wizard.py`
  facade이며 실제 데이터 준비, lookup, option 해석, create/update payload, payload cache, 실행 로직은 책임별 모듈로 분리되어 있습니다.
- `src/models/`
- `src/gui/`
  화면과 서비스의 내부 책임은 page/window/service 하위 모듈로 분리되어 있습니다.
