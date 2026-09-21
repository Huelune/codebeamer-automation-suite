---
name: run-gui
description: PySide6 GUI를 오프스크린으로 실제 띄워서 조작하고 화면을 캡처해 확인한다. GUI 코드(`src/gui/`, `gui_main.py`)를 고치거나 리팩터링한 뒤에는 테스트가 전부 통과해도 반드시 이 스킬로 직접 눌러 보고 넘어간다. 창을 열어 봐 달라, 화면을 보여 달라, 버튼이 동작하는지 확인해 달라, 실제로 실행해 보라, 스크린샷을 찍어 달라 같은 요청에도 사용한다. 테스트가 창 클래스를 patch 하기 때문에 생성자 인자가 잘못돼도 테스트는 초록불이 되고 사용자는 크래시를 본다.
---

# GUI를 실제로 띄워서 확인하기

## 왜 필요한가

이 저장소의 GUI 테스트는 창 클래스를 통째로 `patch` 한다. 모달 창이 `exec()` 에서
멈추기 때문이다. 그 결과 **진짜 생성자가 한 번도 불리지 않는다.**

실제로 2026-09-21에 `TrackerItemDetailDialog` 의 `parent` 인자가 QWidget이 아닌
객체로 바뀐 채 `main` 에 병합됐다. 상세 창 열기 버튼을 누르면 `TypeError` 로
터지는 상태였는데 **테스트 620개가 전부 통과했다.** 오프스크린으로 띄워서 눌러
보고서야 드러났다.

`gui_main.py --smoke-test` 는 창이 뜨는지만 본다. 버튼을 누르지는 않는다.

## 빠른 시작

드라이버 스크립트를 scratchpad에 쓰고 실행한다. 프로젝트에는 남기지 않는다.

```python
import sys
sys.path.insert(0, ".claude/skills/run-gui/scripts")
from gui_harness import check, drain, make_app, offline_settings, open_modal, report, shot

from src.gui.tracker_query_service import TrackerQueryService
from src.gui.tracker_workspace import TrackerWorkspacePage

app = make_app()
settings = offline_settings()
page = TrackerWorkspacePage(
    settings_provider=lambda: settings,
    service=TrackerQueryService(),
    synchronous=True,   # 백그라운드 worker 없이 그 자리에서 끝낸다
)
page.resize(1280, 860)
page.show()
page.activate()
drain(app)

page.item_tree.setCurrentItem(page.item_tree.topLevelItem(0))
drain(app)
shot(page, "01-workspace")

raise SystemExit(report())
```

실행:

```bash
.venv/Scripts/python.exe "$SCRATCHPAD/drive_xxx.py"
```

`PYTHONIOENCODING=utf-8` 을 붙이면 한글 출력이 깨지지 않는다.

## 모달 창 열기

`exec()` 는 이벤트 루프를 돌기 때문에 그냥 부르면 스크립트가 멈춘다.
`open_modal` 이 서브클래스로 `exec` 만 덮어 가로챈다.

```python
from src.gui import tracker_detail_dialog as dialog_module

dialog = open_modal(dialog_module, "TrackerItemDetailDialog", page.detail_dialog.open_dialog)
dialog.resize(1100, 820)
dialog.show()
drain(app)
check("제목", dialog.windowTitle(), "아이템 상세 · #9001001 Vehicle requirements")
shot(dialog, "02-detail-dialog")
```

**`unittest.mock.patch.object` 로 Qt 메서드를 클래스에 직접 갈아 끼우지 않는다.**
`patch.object(SomeDialog, "exec", ...)` 는 segfault 를 낸다. 타입 객체가 망가진다.

가로챌 대상은 **그 창을 `import` 한 모듈** 이다. 정의한 모듈이 아니다.
`TrackerItemDetailDialog` 는 `wiki_content_view` 가 아니라 이것을 쓰는
`tracker_detail_dialog` 모듈에서 바꿔야 한다.

## 확인하는 방법 두 가지

**레이아웃은 캡처로 본다.** `shot()` 이 만든 PNG 를 Read 도구로 열어 본다.
빈 화면이나 무너진 배치는 바로 보인다.

**텍스트는 `check()` 로 본다.** 오프스크린에는 한글 폰트가 없어서 캡처에서
한글이 전부 네모(□)로 나온다. **이건 앱 버그가 아니다.** 제목, 표 내용,
상태 문구처럼 글자를 봐야 하는 것은 값으로 비교한다.

```python
check("이동 후 제목", dialog.windowTitle(), "아이템 상세 · #9001002 Brake system")
check("세션 현재 아이템", session.current.item_id, 9001002)
check("뒤로 가능", session.can_go_back, True)
```

마지막에 `report()` 가 실패를 모아 요약하고 종료 코드를 준다.

## 무엇을 눌러 볼 것인가

고친 코드가 지나가는 경로를 누른다. 리팩터링이면 옮긴 메서드가 전부 한 번씩은
불리도록 한다. 참고할 만한 조작:

- 계층 트리 선택 → 상세 로드
- 상세 창 열기 → 탭 전환 → 관련 아이템 이동 → 뒤로 → 앞으로
- 검색 실행 → 결과 표 선택
- Baseline 비교 → Excel 내보내기

`synchronous=True` 로 만들면 조회가 그 자리에서 끝나서 대기 코드가 필요 없다.
백그라운드 동작 자체를 보려면 `synchronous=False` 로 두고 `task_factory` 를
직접 넘겨 작업을 모았다가 원하는 시점에 실행한다.

## 여기서 버그를 찾으면

드라이버 스크립트는 일회용이다. **찾은 결함은 테스트로 옮겨 심는다.**
`open_modal` 과 같은 방식(서브클래스로 `exec` 만 덮기)을 쓰면 테스트에서도
진짜 생성자가 불린다. `tests/test_gui_tracker_workspace.py` 의
`test_detail_dialog_is_built_with_the_real_class` 가 그 예다.

고친 뒤에는 일부러 되돌려서 그 테스트가 **실패하는지** 확인한다. 실패하지
않으면 그 테스트는 아무것도 지키지 못한다.

## 정리

- 드라이버와 캡처는 scratchpad 에 둔다. 저장소에 커밋하지 않는다.
- 끝에 `drain(app)` 을 한 번 부르고 창을 닫는다. `processEvents()` 만으로는
  위젯이 파괴되지 않아 쌓인다.
