# UML 렌더링 가이드

이 저장소의 UML 문서는 PlantUML 소스 파일로 제공됩니다.

대상 파일:
- `docs/class-diagram.puml`
- `docs/upload-sequence.puml`

## 권장 방법

PlantUML이 설치되어 있다면 아래 스크립트를 사용하는 방법을 권장합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/render_uml.ps1
```

이 스크립트는 아래 파일을 한 번에 렌더링합니다.
- `docs/class-diagram.puml`
- `docs/upload-sequence.puml`

생성 형식:
- PNG
- SVG

## 방법 1. VS Code 확장 사용

권장 상황:
- 로컬에서 빠르게 다이어그램을 확인하고 싶을 때

예시 확장:
- PlantUML

일반적인 흐름:
1. VS Code에서 `.puml` 파일 열기
2. PlantUML 미리보기 실행
3. PNG 또는 SVG로 내보내기

## 방법 2. PlantUML CLI 사용

PlantUML과 Java가 준비되어 있다면 다음처럼 직접 렌더링할 수 있습니다.

PNG 생성:

```bash
plantuml docs/class-diagram.puml docs/upload-sequence.puml
```

SVG 생성:

```bash
plantuml -tsvg docs/class-diagram.puml docs/upload-sequence.puml
```

## 방법 3. Docker 사용

로컬 Java 설치 없이 렌더링하고 싶다면 Docker 이미지 사용도 가능합니다.

예시:

```bash
docker run --rm -v %cd%:/workspace -w /workspace plantuml/plantuml docs/class-diagram.puml docs/upload-sequence.puml
```

SVG 예시:

```bash
docker run --rm -v %cd%:/workspace -w /workspace plantuml/plantuml -tsvg docs/class-diagram.puml docs/upload-sequence.puml
```

## 출력 위치

기본적으로 같은 디렉터리에 결과 파일이 생성됩니다.

예:
- `docs/class-diagram.png`
- `docs/upload-sequence.png`
- `docs/class-diagram.svg`
- `docs/upload-sequence.svg`

## 스크립트 동작

`scripts/render_uml.ps1`은 다음 순서로 렌더링 도구를 찾습니다.

1. PATH의 `plantuml` 명령
2. `docker` 명령 (`plantuml/plantuml` 이미지)

둘 다 없으면 설치 방법을 안내하고 종료 코드 1로 끝납니다. 렌더링 결과는 소스와 같은 `docs/`
디렉터리에 생성됩니다.

PNG만 또는 SVG만 만들려면 `-Format Png` 또는 `-Format Svg`를 사용합니다. 기본값은 둘 다입니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/render_uml.ps1 -Format Svg
```

현재 저장소에는 렌더링 결과 이미지를 커밋하지 않습니다. 필요할 때 위 명령으로 생성합니다.

## 관리 팁

- UML 소스는 수정 이력이 남기 쉬운 `.puml` 형태로 유지
- 문서 링크에는 가능하면 원본 `.puml` 과 렌더링 결과를 함께 제공
- 구조 변경 시 클래스 다이어그램과 시퀀스 다이어그램을 함께 갱신
