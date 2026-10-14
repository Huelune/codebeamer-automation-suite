# 샘플 데이터 및 자격증명 감사

최종 감사일: 2026-07-29

## 범위

- `data/gui-offline-sample/`의 JSON, 문서, XLSX
- `tests/fixtures/`의 JSON, CSV
- `templates/codebeamer-upload-starter/`의 template 및 sample payload
- 저장소가 추적하는 `.env`, 개인키, 인증서 파일 이름
- password, token, API key, bearer authorization 관련 문자열이 있는 추적 파일

## 결과

- 실제 `.env`, private key, certificate 파일은 추적되지 않습니다.
- `.env.example`의 URL, username, password는 모두 명시적인 교체용 placeholder입니다.
- offline schema와 조회 snapshot의 ID, 사용자, 그룹, tracker item 값은 sample 전용 값입니다.
- XLSX에는 `sample_user`, `sample_group_a`, `SAMPLE-*` 형식의 익명 값만 사용됩니다.
- 자격증명 관련 단어가 있는 소스는 환경 변수 로딩, 입력 UI, test fixture 또는 문서이며
  실제 자격증명 값은 확인되지 않았습니다.

## 자동 회귀 방지

`tests/test_sample_data_security.py`는 다음을 검사합니다.

- sample JSON에서 password/token/secret/API key 키에 실제 값이 들어가지 않았는지
- sample 텍스트와 workbook cell에 개인 이메일 주소가 들어가지 않았는지
- `.env.example`의 자격증명이 placeholder인지
- `.gitignore`가 환경 파일과 일반적인 private key/certificate 확장자를 제외하는지

자동 검사는 알려진 패턴을 다루므로, 새 sample을 추가할 때 작성자가 원본 조직명,
프로젝트명, 사용자명, item ID를 직접 익명화했는지도 함께 검토해야 합니다.
