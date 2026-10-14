# Codebeamer API 모니터

## 목적

API 모니터는 온라인 모드에서 발생하는 Codebeamer HTTP 호출의 상태와 응답 지연을
개발자 도구 창의 `API 모니터` 탭에서 실시간으로 확인합니다. 서버 응답 내용을 검사하는
도구가 아니라, 어떤 종류의 호출이 느리거나 실패하는지 빠르게 구분하는 용도입니다.

## 사용 방법

1. `설정 > 개발자`로 이동합니다.
2. `API 모니터 사용`을 켭니다.
3. 필요하면 `느린 요청 기준`을 100~60,000ms 사이에서 조정합니다.
4. 설정을 `저장`한 뒤 `적용`합니다.
5. `개발자 도구 열기`를 누르고 `API 모니터` 탭을 선택합니다.

기능을 켠 상태로 앱을 다시 시작하면 개발자 도구의 API 모니터 탭이 자동으로 열립니다. 창만 닫아도
수집은 계속되며, 새 요청 수집을 중단하려면 설정을 끄고 적용해야 합니다. 설정을
꺼도 현재 메모리에 남아 있는 행은 자동으로 삭제하지 않습니다.

## 화면 구성

상단 통계와 표는 최근 최대 500개 HTTP 시도 기준입니다.

- 완료 요청과 현재 진행 중 요청 수
- 성공률과 실패 수
- 평균, P50, P95, 최대 응답 지연
- 최근 1분 동안 시작된 요청 수
- HTTP 429 수, 재시도 수, 느린 요청 수

성공률은 논리 작업이 아니라 실제 HTTP 시도 행을 기준으로 계산합니다. 예를 들어
첫 요청이 429이고 다음 시도가 성공하면 `재시도`와 `성공`이 각각 한 행으로 기록됩니다.
소요 시간은 네트워크와 서버 처리를 포함해 요청 시작부터 응답 해석까지 측정한
종단 간 지연 시간이며 전송 대역폭을 뜻하지 않습니다.

표에는 다음 메타데이터만 표시합니다.

- 시작 시각
- `get_item`, `update_item` 같은 제어된 요청 종류
- HTTP method
- 식별자가 제거된 API 경로
- status code
- 소요 시간
- 성공, 실패 또는 재시도 결과와 제어된 오류 분류
- 현재 시도 번호와 최대 시도 수
- 같은 논리 작업의 진단 로그와 연결하는 짧은 진단 ID

요청 종류·경로 검색, method, status 대역, 결과, 느린 요청 필터를 함께 사용할 수
있습니다. `화면 업데이트 일시정지`는 표시만 멈추며 수집은 계속합니다. 선택 행
복사는 현재 표에 표시된 안전한 메타데이터만 탭 구분 텍스트로 복사합니다.

## 데이터 및 보안 경계

모니터 데이터는 프로세스 메모리의 고정 길이 버퍼에만 보관하며 파일로 저장하지
않습니다. 아래 정보는 이벤트 모델에 필드 자체가 없으므로 수집할 수 없습니다.

- 요청·응답 본문
- Authorization, Cookie를 포함한 모든 header
- 비밀번호, token, session 값
- query parameter와 그 값
- Codebeamer host 이름과 전체 URL
- 서버가 반환한 원본 오류 문자열

숫자 ID, UUID와 긴 16진수 식별자 형태의 경로 segment는 `{id}`로 바꿉니다. 첨부·그림 다운로드는
서버 context 경로와 첨부 파일 이름이 경로에 들어 있으므로 `/v3` API는 `/v3` 이후만, `displayDocument`는
`/displayDocument/{name}`, 그 밖의 다운로드 경로는 `/{resource}`로만 남깁니다. 오류는
`Timeout`, `Connection`, `RateLimit`, `HTTP`, `Parse`, `Unknown` 중 하나로만
분류합니다. `기록 지우기`는 완료된 메모리 행만 지우며 현재 진행 중인 요청이나
수집 설정은 바꾸지 않습니다.

## 테스트 모드

테스트 모드는 offline snapshot client를 사용하므로 외부 Codebeamer API 호출이
발생하지 않습니다. 모니터를 켠 상태라도 창에는 `수집 대기` 안내가 표시되고 API
행은 추가되지 않습니다.

## 구현 경계

- `src/api_monitor.py`: Qt와 독립된 thread-safe 이벤트 버퍼, 경로 정규화와 통계
- `src/codebeamer_client.py`: 공통 GET/POST/PUT/DELETE 계측과 재시도 문맥
- `src/gui/api_monitor_window.py`: 200ms polling 기반 재사용 panel과 기존 window wrapper
- `src/gui/developer_tools_window.py`: 진단 로그와 API panel을 담는 별도 개발자 도구 창
- `src/gui/settings_center.py`: 개발자 설정과 창 열기 동작
- `src/gui/main_window.py`: 앱 시작·설정 적용·종료 생명주기

작업 thread는 Qt widget을 직접 갱신하지 않습니다. HTTP 계층은 thread-safe 서비스에
이벤트만 기록하고, API panel의 `QTimer`가 snapshot을 읽어 GUI thread에서 표시합니다.
