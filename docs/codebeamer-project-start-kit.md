# Codebeamer 프로젝트 시작 패키지

## 목적

이 문서는 새 Codebeamer 업로드 프로젝트를 시작할 때 필요한 최소 패키지와 생성 절차를 정리합니다.

핵심 원칙은 두 가지입니다.

1. tracker schema는 실행 시점에 대상 tracker에서 가져옵니다.
2. 가져온 schema는 snapshot으로 저장해 테스트와 계약 비교에 재사용합니다.

즉, runtime source of truth 는 live tracker schema이고,
`tracker-schema.json` 같은 파일은 그 결과를 고정해 두는 생성 산출물입니다.

## 왜 schema snapshot도 필요한가

실행 시 live schema를 직접 읽는 것만으로는 아래 문제가 남습니다.

- 서버 접근 없이 오프라인 테스트를 할 수 없습니다.
- tracker 설정이 바뀌었을 때 무엇이 달라졌는지 비교하기 어렵습니다.
- 새 프로젝트 초기 구현에서 field 해석 결과를 리뷰하기 어렵습니다.

그래서 권장 방식은 아래입니다.

1. 실행 시 `GET /v3/trackers/{trackerId}/schema` 로 schema를 읽음
2. 그 결과를 `tracker-schema.json` 과 `tracker-schema-flat.*` 로 저장
3. 구현, 테스트, 코드리뷰는 저장된 snapshot을 기준으로 반복
4. 필요할 때 live schema를 다시 export 해서 diff 확인

## 시작 패키지 구성

템플릿 디렉터리:

- [templates/codebeamer-upload-starter/README.md](../templates/codebeamer-upload-starter/README.md)
- [templates/codebeamer-upload-starter/project-context.template.json](../templates/codebeamer-upload-starter/project-context.template.json)
- [templates/codebeamer-upload-starter/input-contract.template.json](../templates/codebeamer-upload-starter/input-contract.template.json)
- [templates/codebeamer-upload-starter/mapping.template.json](../templates/codebeamer-upload-starter/mapping.template.json)
- [templates/codebeamer-upload-starter/lookup-policy.template.json](../templates/codebeamer-upload-starter/lookup-policy.template.json)
- [templates/codebeamer-upload-starter/notes.template.md](../templates/codebeamer-upload-starter/notes.template.md)
- [templates/codebeamer-upload-starter/payload-preview.sample.jsonl](../templates/codebeamer-upload-starter/payload-preview.sample.jsonl)

live tracker export 도구:

- [export_tracker_contract.py](../export_tracker_contract.py)

## export 결과물

`export_tracker_contract.py` 는 아래 파일을 생성합니다.

- `tracker-schema.json`
- `tracker-schema-flat.json`
- `tracker-schema-flat.csv`
- `tracker-contract.json`

또한 시작 템플릿 파일들을 같은 디렉터리에 복사합니다. 이미 있는 템플릿 파일은 덮어쓰지 않습니다.

## 권장 사용 순서

1. 대상 project/tracker를 정합니다.
2. 아래 명령으로 시작 패키지를 생성합니다.

```bash
py -3 export_tracker_contract.py --project-id <PROJECT_ID> --tracker-id <TRACKER_ID>
```

3. 생성된 디렉터리에서 `project-context.template.json`, `input-contract.template.json`, `mapping.template.json` 을 채웁니다.
4. 샘플 입력 파일 1개를 준비합니다.
5. 샘플 row 1개에 대한 payload preview를 저장합니다.
6. 그 다음 실제 업로더 구현을 시작합니다.

## 어떤 파일이 수동 작성이고 어떤 파일이 생성 파일인가

수동 작성:

- `project-context.template.json`
- `input-contract.template.json`
- `mapping.template.json`
- `lookup-policy.template.json`
- `notes.template.md`

생성 파일:

- `tracker-schema.json`
- `tracker-schema-flat.json`
- `tracker-schema-flat.csv`
- `tracker-contract.json`

운영 중 생성 또는 갱신:

- `payload-preview.sample.jsonl`

## 관련 문서

- [Codebeamer 업로드 조사 정리](./codebeamer-upload-reference.md)
- [아키텍처](./architecture.md)
- [CLI 사용 가이드](./cli-guide.md)
