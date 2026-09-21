# Windows Portable ZIP 배포

## 지원 범위

배포된 GitHub Release 자산은 Windows 10/11 x64에서 압축을 풀어 실행하는 Portable ZIP입니다.
PyInstaller `onedir` 패키지이므로 설치 프로그램이나 관리자 권한은 필요하지 않지만, ZIP 안의
`CodebeamerAutomationSuite.exe`와 `_internal` 디렉터리를 분리하면 실행할 수 없습니다.

배포 범위는 다음과 같습니다.

- Windows x64 Portable ZIP
- `CodebeamerAutomationSuite.exe`와 실행 의존 파일
- 익명 오프라인 샘플과 Windows 실행 안내
- 빌드 환경의 전체 Python 패키지 목록인 `DEPENDENCIES.txt`
- ZIP의 SHA-256 체크섬과 GitHub artifact attestation

이번 배포 방식에는 MSI, 단일 파일 EXE, Windows ARM64, macOS 패키지, 자동 업데이트와 코드 서명이
포함되지 않습니다. 사용자 설정, 자격증명, `.env`, 실제 Codebeamer 데이터와 서버 주소도 배포 파일에
포함하지 않습니다.

## 다운로드와 실행

1. GitHub의 **Releases**에서 원하는 버전을 엽니다.
2. 정식 버전의 `Codebeamer-Automation-Suite-vX.Y.Z-windows-x64.zip`과 `SHA256SUMS.txt`를 같은
   폴더에 받습니다. RC 자산은 버전 뒤에 `-rc.N`이 붙습니다.
3. 아래 절차로 SHA-256과 필요하면 attestation을 확인합니다.
4. ZIP 전체를 새 폴더에 압축 해제합니다. ZIP 내부나 임시 압축 미리보기에서 EXE를 직접 실행하지 않습니다.
5. 압축을 푼 폴더의 `CodebeamerAutomationSuite.exe`를 실행합니다.

압축을 푼 폴더에서 다음 명령을 실행하면 GUI를 열지 않고 패키지 버전을 확인할 수 있습니다.

```powershell
.\CodebeamerAutomationSuite.exe --version
```

정식 버전은 `vX.Y.Z`, 릴리스 후보는 `vX.Y.Z-rc.N` 형식을 사용합니다. 릴리스 후보는 GitHub에서
Pre-release로 표시되므로 일반 사용자에게는 정식 버전을 권장합니다.

## Excel 형식

- `.xlsx` 파일은 패키지에 포함된 Python 의존성으로 읽고 저장할 수 있습니다.
- 레거시 `.xls` 파일 처리는 Windows에 설치된 데스크톱 Microsoft Excel을 사용하는 `xlwings` 경로가
  필요합니다. Excel이 설치되지 않은 PC에서는 `.xls` 처리를 지원하지 않습니다.

`.xls`를 사용해야 하는 경우 먼저 Microsoft Excel에서 `.xlsx`로 변환하면 Excel 설치 여부에 따른 실행
차이를 줄일 수 있습니다.

## SmartScreen 경고

현재 EXE는 코드 서명하지 않습니다. 따라서 Windows SmartScreen이 `알 수 없는 게시자` 또는 앱 실행
경고를 표시할 수 있습니다. 경고가 표시되면 출처가 이 저장소의 GitHub Release인지 확인하고 SHA-256과
attestation 검증을 통과한 파일에 한해서만 실행합니다.

SmartScreen 경고가 없다는 사실만으로 파일이 안전하다고 판단하지 않으며, 다른 사이트나 재배포 링크에서
받은 ZIP은 사용하지 않습니다.

## SHA-256 확인

Release 자산을 받은 폴더에서 PowerShell을 열고 다음 명령을 실행합니다.

```powershell
Get-FileHash .\Codebeamer-Automation-Suite-v0.1.0-windows-x64.zip -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

첫 번째 명령의 `Hash` 값과 `SHA256SUMS.txt`의 해당 ZIP 값이 대소문자를 제외하고 정확히 같아야 합니다.
파일명이 다른 버전이면 두 명령의 파일명을 실제 버전에 맞게 바꿉니다. 값이 다르면 압축을 풀거나 실행하지
말고 파일을 다시 받습니다.

## GitHub attestation 확인

[GitHub CLI](https://cli.github.com/)가 설치된 환경에서는 Release ZIP이 이 저장소의 GitHub Actions에서
생성됐는지 다음과 같이 확인할 수 있습니다.

```powershell
gh attestation verify .\Codebeamer-Automation-Suite-v0.1.0-windows-x64.zip --repo Huelune/codebeamer-automation-suite
```

검증은 ZIP 자체를 대상으로 합니다. 압축을 푼 EXE를 대신 지정하거나 ZIP 내용을 수정하면 검증되지
않습니다. 공개 저장소가 아니라면 attestation을 읽을 수 있는 GitHub 계정으로 먼저 `gh auth login`을
완료해야 합니다.

## 버전과 태그 규칙

저장소 루트의 `VERSION`이 제품 버전의 단일 기준입니다. 창 제목, `--version` 출력, ZIP 이름과 Release
제목은 이 값을 사용합니다.

- 정식 Release 태그: `v0.1.0` 같은 `vX.Y.Z`
- Pre-release 태그: `v0.1.0-rc.1` 같은 `vX.Y.Z-rc.N`
- RC 태그의 기본 버전은 접미사를 제외한 `0.1.0`이며 `VERSION`도 `0.1.0`이어야 합니다.
- 다른 접미사, 생략된 버전 부분, 앞에 `v`가 없는 태그는 Release 대상으로 인정하지 않습니다.

Release를 준비할 때는 먼저 버전 변경만 담은 PR을 `main`에 병합합니다. 포함할 기능 PR도 모두 병합된 뒤
최신 `main` 커밋에 태그를 만들고 push합니다.

```bash
git switch main
git pull --ff-only origin main
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

태그가 가리키는 커밋은 반드시 `origin/main` 이력에 포함되어야 하며, 태그의 기본 버전은 `VERSION`과
일치해야 합니다. 열린 PR이나 아직 병합되지 않은 원격 브랜치의 변경은 Release에 포함되지 않습니다.
실패한 태그를 다른 커밋으로 강제 이동하지 말고 원인을 수정한 새 태그를 사용합니다.

## GitHub Actions 동작

Windows Release workflow는 pull request, 수동 실행, `main` push와 `v*` 태그 push에서 실행됩니다.
`main` push는 각각 통과한 PR이 병합 뒤에도 함께 통과하는지 확인하는 것이 목적이라 lint와 테스트만
실행하고 빌드는 건너뜁니다. 나머지 경우에는 Windows Server 2022 x64에서 전체 단위 테스트,
PyInstaller `onedir` 빌드, 패키지의 `--version`과 `--smoke-test`, ZIP 생성과 SHA-256 계산을
수행합니다.

재현 가능한 Release 빌드를 위해 다음 도구 체인을 고정합니다.

- GitHub Actions runner: `windows-2022` x64
- Python: `3.13.14`
- PyInstaller: `6.21.0`
- 직접 Python 의존성: `requirements-release.txt`에 정확한 버전으로 고정

Release 의존성을 바꿀 때는 일반 개발용 `requirements.txt`만 수정하지 말고
`requirements-release.txt`의 직접 의존성 버전도 명시적으로 검토합니다. 설치 과정에서 결정되는 전이
의존성은 매 빌드의 `pip freeze` 결과를 `DEPENDENCIES.txt`로 패키지에 보존합니다.

PR·수동 실행·태그 빌드의 Portable ZIP과 체크섬은 workflow artifact로 7일간 보관됩니다. PR과 수동
실행 artifact는 검증용이며 GitHub Release로 게시되지 않습니다.

태그 실행에서만 Release job이 이어집니다. 이 job은 다음 조건을 모두 확인합니다.

- 태그가 `vX.Y.Z` 또는 `vX.Y.Z-rc.N` 형식임
- 태그 커밋이 `origin/main`의 이력에 포함됨
- 태그 기본 버전과 `VERSION`이 일치함
- Windows 테스트, 빌드와 EXE smoke test가 성공함

조건을 통과하면 ZIP의 provenance attestation을 만들고 Draft Release에 ZIP과 `SHA256SUMS.txt`를 올린
다음 게시합니다. RC는 자동으로 Pre-release가 됩니다. 같은 태그의 게시된 Release는 덮어쓰지 않으며,
중단된 동일 태그의 Draft만 자산을 교체해 재개할 수 있습니다.

## 검증 범위와 수동 확인

자동 workflow는 고정된 Windows Server 2022 runner에서 앱 생성과 짧은 offscreen 기동까지 확인합니다.
이는 실제 데스크톱 환경의 화면, SmartScreen, 설치된 Excel 연동과 사내 Codebeamer 연결을 대체하지
않습니다.

첫 정식 Release의 검증 상태는 다음 항목을 깨끗한 Windows 10/11 x64 PC에서 직접 확인하기 전까지
`부분 검증`으로 유지합니다.

- Release ZIP 다운로드, 체크섬과 attestation 확인
- 새 폴더에 전체 압축 해제 후 EXE 실행
- 익명 오프라인 샘플 불러오기
- 일반 창과 고해상도 창, KEFICO·igloo 테마 표시
- `.xlsx` 읽기와 결과 저장
- Microsoft Excel이 설치된 환경의 `.xls` 처리
- 실제 Codebeamer 연결은 별도의 실서버 검증 절차로 확인

PR artifact로 확인한 결과와 실제 Release 자산으로 확인한 결과를 구분해 기록합니다. 코드 서명과 깨끗한
Windows 10/11 수동 검증이 끝나지 않았다면 `검증 완료` 또는 `프로덕션 배포 완료`로 기록하지 않습니다.
