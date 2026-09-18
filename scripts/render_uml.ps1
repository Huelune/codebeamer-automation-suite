#Requires -Version 5.1
<#
.SYNOPSIS
    docs/ 아래 PlantUML 소스를 PNG와 SVG로 렌더링한다.

.DESCRIPTION
    `plantuml` 명령이 PATH 에 있으면 그대로 사용하고, 없으면 Docker 이미지로
    대체한다. 둘 다 없으면 설치 방법을 안내하고 종료한다.
    렌더링 결과는 소스와 같은 `docs/` 디렉터리에 생성된다.

.PARAMETER Format
    생성할 형식. 기본값은 PNG 와 SVG 모두.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/render_uml.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/render_uml.ps1 -Format Svg
#>
[CmdletBinding()]
param(
    [ValidateSet('Png', 'Svg', 'Both')]
    [string]$Format = 'Both'
)

$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sources = @(
    'docs/class-diagram.puml',
    'docs/upload-sequence.puml'
)

foreach ($source in $sources) {
    $sourcePath = Join-Path $repositoryRoot $source
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
        throw "UML 소스를 찾을 수 없습니다: $source"
    }
}

$formatArguments = switch ($Format) {
    'Png' { @(, @()) }
    'Svg' { @(, @('-tsvg')) }
    'Both' { @(@(), @('-tsvg')) }
}

$plantuml = Get-Command plantuml -ErrorAction SilentlyContinue
$docker = Get-Command docker -ErrorAction SilentlyContinue

if ($plantuml) {
    Write-Host "plantuml 명령으로 렌더링합니다: $($plantuml.Source)"
    foreach ($extra in $formatArguments) {
        $arguments = @($extra) + $sources
        & $plantuml.Source $arguments
        if ($LASTEXITCODE -ne 0) {
            throw "plantuml 실행이 실패했습니다. 종료 코드: $LASTEXITCODE"
        }
    }
}
elseif ($docker) {
    Write-Host 'plantuml 명령이 없어 Docker 이미지(plantuml/plantuml)로 렌더링합니다.'
    $dockerPrefix = @(
        'run', '--rm',
        '-v', "$($repositoryRoot):/workspace",
        '-w', '/workspace',
        'plantuml/plantuml'
    )
    foreach ($extra in $formatArguments) {
        $arguments = $dockerPrefix + @($extra) + $sources
        & $docker.Source $arguments
        if ($LASTEXITCODE -ne 0) {
            throw "Docker 기반 plantuml 실행이 실패했습니다. 종료 코드: $LASTEXITCODE"
        }
    }
}
else {
    Write-Warning @'
plantuml 과 docker 명령을 모두 찾을 수 없어 렌더링을 건너뜁니다.
아래 중 하나를 준비한 뒤 다시 실행하세요.
  - PlantUML CLI 설치 (Java 필요)
  - Docker 설치 후 plantuml/plantuml 이미지 사용
  - VS Code PlantUML 확장으로 수동 내보내기
자세한 방법은 docs/render-uml.md 를 참고하세요.
'@
    exit 1
}

Write-Host '렌더링을 마쳤습니다. 결과는 docs/ 디렉터리를 확인하세요.'
