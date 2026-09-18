from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from typing import Any

from src.upload_policy import UPLOAD_MODE_UPDATE as GUI_UPLOAD_MODE_UPDATE
from src.upload_policy import normalize_upload_mode as normalize_gui_upload_mode
from src.upload_policy import upload_mode_action_label as gui_upload_mode_action_label

from .settings_store import GuiSettings
from .settings_store import GuiWorkflowPreset
from .window_support import UploadProgressState
from .window_support import _merge_root_item_page_configs
from .window_support import _merge_window_preferences


if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    from .service_core import GuiCodebeamerService
    from .service_core import GuiExcelService
    from .settings_store import GuiSettingsStore
    from .upload_service import GuiUploadPipelineService
    from .window_support import GuiSessionState

    class _WindowWorkflowMixinComposition(QMainWindow):
        """WindowWorkflowMixin 이 조립된 뒤에야 쓸 수 있는 이름들의 선언이다.

        `BatchUploadWindow` 가 QMainWindow 와 함께 조립한다.
        Qt 메서드(statusBar)는 QMainWindow 상속으로 해결한다.
        런타임에는 object 이므로 실제 상속 관계는 바뀌지 않는다.
        """

        # 조립 클래스가 설정하는 속성이다.
        codebeamer_service: GuiCodebeamerService
        excel_service: GuiExcelService
        file_page: Any
        mapping_page: Any
        pipeline_service: GuiUploadPipelineService
        project_page: Any
        qt: dict[str, Any]
        result_page: Any
        root_item_field_page: Any
        root_item_structure_page: Any
        session_state: GuiSessionState
        settings_page: Any
        settings_store: GuiSettingsStore
        upload_page: Any
        validation_page: Any
        workflow_preset_combo: Any

        # 형제 믹스인이 제공하는 메서드다. 시그니처는 정의 위치에서 옮겼다.
        def _apply_theme(self, theme_name: str | None) -> str:
            ...

        def _attach_navigation(
            self, page, previous_page=None, next_page=None, next_handler=None, restart_handler=None
        ) -> None: ...

        def _run_with_busy(self, message: str, func, *args, **kwargs):
            ...

        def _show_error_dialog(self, title: str, message: str) -> None:
            ...

        def _show_info_dialog(self, title: str, message: str) -> None:
            ...

        def _show_page(self, page) -> None:
            ...

else:
    _WindowWorkflowMixinComposition = object


class WindowWorkflowMixin(_WindowWorkflowMixinComposition):
    def _on_settings_changed(self, settings: GuiSettings | None) -> GuiSettings:
        if settings is None:
            return self.session_state.settings
        normalized_theme = self._apply_theme(settings.theme_name)
        self.session_state.settings = replace(
            settings,
            theme_name=normalized_theme,
        )
        if hasattr(self, "workflow_preset_combo"):
            self._refresh_workflow_preset_choices()
        self.statusBar().showMessage("설정 상태를 갱신했습니다.")
        return self.session_state.settings

    def _on_file_state_changed(self, file_state: dict[str, object]) -> None:
        self.session_state.file_state = file_state
        self.statusBar().showMessage("파일 선택 상태를 갱신했습니다.")

    def _test_connection(self, settings: GuiSettings) -> list[dict[str, object]]:
        busy_message = (
            "테스트 프로젝트 목록을 불러오는 중입니다."
            if bool(getattr(settings, "offline_mode", False))
            else "프로젝트 목록을 불러오는 중입니다."
        )
        projects = self._run_with_busy(
            busy_message,
            self.codebeamer_service.test_connection_and_load_projects,
            settings,
        )
        self.session_state.settings = settings
        self.session_state.projects = projects
        self.statusBar().showMessage(
            "테스트 프로젝트 목록을 불러왔습니다."
            if bool(getattr(settings, "offline_mode", False))
            else "연결 테스트와 프로젝트 조회가 완료되었습니다."
        )
        return projects

    def _load_trackers(self, settings: GuiSettings, project_id: int) -> list[dict[str, object]]:
        trackers = self._run_with_busy(
            "트래커 목록을 불러오는 중입니다.",
            self.codebeamer_service.load_trackers,
            settings,
            project_id,
        )
        self.session_state.settings = settings
        self.session_state.trackers = trackers
        self.statusBar().showMessage("트래커 목록을 불러왔습니다.")
        return trackers

    def _load_file_preview(
        self,
        file_path: str,
        *,
        file_paths: list[str] | None = None,
        sheet_name: str,
        header_row: int,
        summary_column: str,
    ):
        preview = self._run_with_busy(
            "Excel 시트와 미리보기를 불러오는 중입니다.",
            self.excel_service.load_preview,
            file_path,
            file_paths=file_paths,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_column=summary_column,
        )
        self.statusBar().showMessage("Excel 미리보기를 불러왔습니다.")
        return preview

    def _load_file_metadata(self, file_path: str):
        metadata = self._run_with_busy(
            "Excel 시트 정보를 불러오는 중입니다.",
            self.excel_service.load_metadata,
            file_path,
        )
        self.statusBar().showMessage("Excel 시트 정보를 불러왔습니다.")
        return metadata

    def _load_sheet_preview(
        self,
        file_path: str,
        *,
        sheet_name: str,
        header_row: int,
        summary_column: str,
    ):
        preview = self._run_with_busy(
            "선택한 Excel 시트의 일부 행을 불러오는 중입니다.",
            self.excel_service.load_sheet_preview,
            file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_column=summary_column,
        )
        self.statusBar().showMessage("선택한 시트의 미리보기를 불러왔습니다.")
        return preview

    def _load_full_file_data(
        self,
        file_path: str,
        *,
        file_paths: list[str] | None,
        sheet_name: str,
        header_row: int,
        summary_column: str,
        sheet_preview=None,
    ):
        preview = self._run_with_busy(
            "선택한 모든 Excel 파일의 전체 데이터를 불러오는 중입니다.",
            self.excel_service.load_full_data,
            file_path,
            file_paths=file_paths,
            sheet_name=sheet_name,
            header_row=header_row,
            summary_column=summary_column,
            sheet_preview=sheet_preview,
        )
        self.statusBar().showMessage(
            "기존 전체 데이터를 재사용했습니다."
            if bool(getattr(preview, "cache_hit", False))
            else "선택한 모든 Excel 파일의 전체 데이터를 불러왔습니다."
        )
        return preview

    def _current_settings_snapshot(self) -> GuiSettings:
        settings = replace(self.session_state.settings)
        get_settings = getattr(self.settings_page, "get_settings", None)
        if callable(get_settings):
            settings = replace(get_settings())

        get_selection = getattr(self.project_page, "get_selection", None)
        if callable(get_selection):
            selection = dict(get_selection() or {})
            settings.default_project_id = str(selection.get("project_id") or settings.default_project_id or "")
            settings.default_tracker_id = str(selection.get("tracker_id") or settings.default_tracker_id or "")

        file_state = self._current_file_state_snapshot()
        file_paths = [
            str(path).strip()
            for path in file_state.get("file_paths") or []
            if str(path).strip()
        ]
        if file_paths:
            settings.last_file_path = file_paths[0]
        return settings

    def _current_file_state_snapshot(self) -> dict[str, object]:
        current_state = dict(self.session_state.file_state or {})
        get_state = getattr(self.file_page, "get_state", None)
        if callable(get_state):
            current_state.update(dict(get_state() or {}))
        return current_state

    def _apply_workflow_preset_to_mapping_context(self, mapping_context, preset: GuiWorkflowPreset) -> None:
        """`apply_workflow_preset_to_mapping_context` 변경을 적용한다."""
        self.pipeline_service.apply_saved_workflow_values(
            mapping_context,
            root_item_config=dict(preset.root_item_config or {}),
            selected_mapping=dict(preset.selected_mapping or {}),
            selected_mapping_modes=dict(preset.selected_mapping_modes or {}),
            selected_default_values=dict(preset.selected_default_values or {}),
            selected_default_value_modes=dict(preset.selected_default_value_modes or {}),
            selected_tracker_item_settings=dict(preset.selected_tracker_item_settings or {}),
        )

    def _collect_workflow_preset(
        self,
        *,
        preset_id: str = "",
        name: str = "기본 설정",
        is_default: bool = False,
    ) -> GuiWorkflowPreset:
        """`collect_workflow_preset` 정보를 수집한다."""
        settings = self._current_settings_snapshot()
        file_state = self._current_file_state_snapshot()
        file_options = {
            "sheet_name": str(file_state.get("sheet_name") or settings.excel_sheet_name or "0"),
            "header_row": int(file_state.get("header_row") or settings.excel_header_row or 1),
            "summary_column": str(file_state.get("summary_column") or settings.summary_column or "Summary"),
        }

        root_item_config: dict[str, object] = {}
        mapping_context = self.session_state.mapping_context
        if mapping_context is not None:
            root_item_config = dict(getattr(mapping_context, "root_item_config", {}) or {})
        current_page = getattr(self, "_current_page", None)
        if (
            current_page
            in {getattr(self, "root_item_structure_page", None), getattr(self, "root_item_field_page", None)}
            and mapping_context is not None
        ):
            structure_config = (
                self.root_item_structure_page.get_config()
                if callable(getattr(self.root_item_structure_page, "get_config", None))
                else None
            )
            field_config = (
                self.root_item_field_page.get_config()
                if callable(getattr(self.root_item_field_page, "get_config", None))
                else None
            )
            root_item_config = _merge_root_item_page_configs(
                root_item_config,
                structure_config=structure_config,
                field_config=field_config,
            )

        selected_mapping: dict[str, str] = {}
        selected_mapping_modes: dict[str, dict[str, bool]] = {}
        selected_default_values: dict[str, str] = {}
        selected_default_value_modes: dict[str, dict[str, bool]] = {}
        selected_tracker_item_settings: dict[str, dict[str, object]] = {}
        if callable(getattr(self.mapping_page, "get_selected_mapping", None)):
            selected_mapping = dict(self.mapping_page.get_selected_mapping() or {})
        if callable(getattr(self.mapping_page, "get_selected_mapping_modes", None)):
            selected_mapping_modes = dict(self.mapping_page.get_selected_mapping_modes() or {})
        if callable(getattr(self.mapping_page, "get_selected_default_values", None)):
            selected_default_values = dict(self.mapping_page.get_selected_default_values() or {})
        if callable(getattr(self.mapping_page, "get_selected_default_value_modes", None)):
            selected_default_value_modes = dict(self.mapping_page.get_selected_default_value_modes() or {})
        if callable(getattr(self.mapping_page, "get_selected_tracker_item_settings", None)):
            selected_tracker_item_settings = dict(self.mapping_page.get_selected_tracker_item_settings() or {})

        if not selected_mapping and mapping_context is not None:
            selected_mapping = dict(getattr(mapping_context, "selected_mapping", {}) or {})
        if not selected_mapping_modes and mapping_context is not None:
            selected_mapping_modes = dict(getattr(mapping_context, "selected_mapping_modes", {}) or {})
        if not selected_default_values and mapping_context is not None:
            selected_default_values = dict(getattr(mapping_context, "selected_default_values", {}) or {})
        if not selected_default_value_modes and mapping_context is not None:
            selected_default_value_modes = dict(getattr(mapping_context, "selected_default_value_modes", {}) or {})
        if not selected_tracker_item_settings and mapping_context is not None:
            selected_tracker_item_settings = dict(getattr(mapping_context, "selected_tracker_item_settings", {}) or {})

        return GuiWorkflowPreset(
            preset_id=str(preset_id or ""),
            name=str(name or "기본 설정").strip() or "기본 설정",
            connection_scope=self.settings_store.workflow_connection_scope(settings),
            project_id=str(settings.default_project_id or ""),
            tracker_id=str(settings.default_tracker_id or ""),
            is_default=bool(is_default),
            settings=settings,
            file_options=file_options,
            root_item_config=root_item_config,
            selected_mapping=selected_mapping,
            selected_mapping_modes=selected_mapping_modes,
            selected_default_values=selected_default_values,
            selected_default_value_modes=selected_default_value_modes,
            selected_tracker_item_settings=selected_tracker_item_settings,
        )

    def _current_workflow_scope(self) -> tuple[str, str, str]:
        settings = self._current_settings_snapshot()
        return (
            self.settings_store.workflow_connection_scope(settings),
            str(settings.default_project_id or "").strip(),
            str(settings.default_tracker_id or "").strip(),
        )

    def _refresh_workflow_preset_choices(self, selected_id: str | None = None) -> None:
        combo = getattr(self, "workflow_preset_combo", None)
        if combo is None:
            return
        previous_id = str(
            selected_id
            if selected_id is not None
            else (combo.currentData() or "")
        )
        connection_scope, project_id, tracker_id = self._current_workflow_scope()
        presets = (
            self.settings_store.list_tracker_workflow_presets(
                connection_scope=connection_scope,
                project_id=project_id,
                tracker_id=tracker_id,
            )
            if connection_scope and project_id and tracker_id
            else []
        )
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("저장 설정 선택", "")
        legacy_preset = self.settings_store.load_workflow_preset()
        if legacy_preset is not None and self._preset_matches_settings(
            legacy_preset,
            self._current_settings_snapshot(),
        ):
            combo.addItem("기존 전체 설정 가져오기", "__legacy__")
        for preset in presets:
            label = f"{preset.name} · 기본" if preset.is_default else preset.name
            combo.addItem(label, preset.preset_id)
        target_index = combo.findData(previous_id) if previous_id else -1
        if target_index < 0:
            default_preset = next(
                (preset for preset in presets if preset.is_default),
                None,
            )
            if default_preset is not None:
                target_index = combo.findData(default_preset.preset_id)
        combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        combo.blockSignals(False)
        self._sync_workflow_preset_action_state()

    def _sync_workflow_preset_action_state(self, _index: int | None = None) -> None:
        combo = getattr(self, "workflow_preset_combo", None)
        selected_id = "" if combo is None else str(combo.currentData() or "")
        has_named_selection = bool(selected_id) and selected_id != "__legacy__"
        rename_button = getattr(self, "rename_workflow_button", None)
        default_button = getattr(self, "default_workflow_button", None)
        delete_button = getattr(self, "delete_workflow_button", None)
        if rename_button is not None:
            rename_button.setEnabled(has_named_selection)
        if default_button is not None:
            selected = (
                self.settings_store.get_tracker_workflow_preset(selected_id)
                if has_named_selection
                else None
            )
            default_button.setEnabled(
                selected is not None and not selected.is_default
            )
        if delete_button is not None:
            delete_button.setEnabled(has_named_selection)

    def _preset_matches_settings(
        self,
        preset: GuiWorkflowPreset,
        settings: GuiSettings,
    ) -> bool:
        connection_scope = str(preset.connection_scope or "").strip()
        project_id = str(preset.project_id or "").strip()
        tracker_id = str(preset.tracker_id or "").strip()
        if not connection_scope and not project_id and not tracker_id:
            return True
        return (
            (not connection_scope or connection_scope == self.settings_store.workflow_connection_scope(settings))
            and (not project_id or project_id == str(settings.default_project_id or "").strip())
            and (not tracker_id or tracker_id == str(settings.default_tracker_id or "").strip())
        )

    def _apply_workflow_preset(self, preset: GuiWorkflowPreset, *, startup: bool = False) -> None:
        """`apply_workflow_preset` 변경을 적용한다."""
        if startup and not self._preset_matches_settings(
            preset,
            self.session_state.settings,
        ):
            self.session_state.workflow_preset = None
            self.statusBar().showMessage(
                "마지막 전체 설정은 다른 트래커용이므로 자동 적용하지 않았습니다."
            )
            return
        self.session_state.workflow_preset = preset
        is_named_preset = bool(str(preset.connection_scope or "").strip())
        if is_named_preset:
            current = self.session_state.settings
            self.session_state.settings = replace(
                current,
                upload_mode=normalize_gui_upload_mode(preset.settings.upload_mode),
                excel_header_row=max(int(preset.settings.excel_header_row or 1), 1),
                summary_column=str(preset.settings.summary_column or "Summary"),
                excel_sheet_name=str(preset.settings.excel_sheet_name or "0"),
            )
            self._apply_theme(current.theme_name)
        elif self.settings_store.app_settings_path.exists():
            current = self.session_state.settings
            self.session_state.settings = replace(
                current,
                upload_mode=normalize_gui_upload_mode(preset.settings.upload_mode),
                excel_header_row=max(int(preset.settings.excel_header_row or 1), 1),
                summary_column=str(preset.settings.summary_column or "Summary"),
                excel_sheet_name=str(preset.settings.excel_sheet_name or "0"),
                last_file_path=str(preset.settings.last_file_path or current.last_file_path or ""),
            )
            self._apply_theme(current.theme_name)
        else:
            normalized_theme = self._apply_theme(preset.settings.theme_name)
            self.session_state.settings = _merge_window_preferences(
                self.session_state.settings,
                replace(preset.settings, theme_name=normalized_theme),
            )

        set_settings = getattr(self.settings_page, "set_settings", None)
        if callable(set_settings):
            set_settings(replace(self.session_state.settings))

        load_selection = getattr(self.project_page, "load_selection", None)
        if callable(load_selection):
            load_selection(
                self.session_state.settings.default_project_id, self.session_state.settings.default_tracker_id
            )

        load_file_state = getattr(self.file_page, "load_state", None)
        if callable(load_file_state):
            load_file_state(dict(preset.file_options or {}))
        else:
            self.session_state.file_state.update(dict(preset.file_options or {}))

        # 파일 옵션이나 업로드 모드가 달라질 수 있으므로 기존 raw data와
        # mapping context 위에 저장 매핑을 덮지 않는다. 파일 단계에서 명시적으로
        # 전체 데이터를 다시 불러온 뒤 새 context에 preset을 적용한다.
        self.session_state.mapping_context = None
        self.session_state.validation_context = None
        self.session_state.upload_result = None
        self._show_page(self.file_page)

        message = (
            "저장된 전체 설정을 자동으로 불러왔습니다."
            if startup
            else (
                "전체 설정을 불러왔습니다. 시트 미리보기와 전체 데이터 로드를 "
                "다시 실행하세요."
            )
        )
        self.statusBar().showMessage(message)

    def _save_workflow_preset(self) -> None:
        selected_id = str(self.workflow_preset_combo.currentData() or "")
        if not selected_id or selected_id == "__legacy__":
            self._save_workflow_preset_as()
            return
        try:
            existing = self.settings_store.get_tracker_workflow_preset(selected_id)
            if existing is None:
                raise ValueError("선택한 저장 설정을 찾을 수 없습니다.")
            preset = self._save_named_workflow_preset(
                preset_id=existing.preset_id,
                name=existing.name,
                is_default=existing.is_default,
            )
        except Exception as exc:
            self.statusBar().showMessage(str(exc))
            self._show_error_dialog("전체 설정 저장 실패", str(exc))
            return
        self.statusBar().showMessage(f"'{preset.name}' 전체 설정을 갱신했습니다.")
        self._show_info_dialog(
            "전체 설정 저장",
            f"'{preset.name}' 전체 설정을 갱신했습니다.",
        )

    def _request_workflow_preset_name(
        self,
        *,
        title: str,
        initial_name: str = "",
    ) -> str | None:
        value, accepted = self.qt["QInputDialog"].getText(
            self,
            title,
            "저장 설정 이름",
            text=str(initial_name or ""),
        )
        if not accepted:
            return None
        name = str(value or "").strip()
        if not name:
            raise ValueError("저장 설정 이름을 입력해야 합니다.")
        return name

    def _save_named_workflow_preset(
        self,
        *,
        preset_id: str,
        name: str,
        is_default: bool = False,
    ) -> GuiWorkflowPreset:
        preset = self._collect_workflow_preset(
            preset_id=preset_id,
            name=name,
            is_default=is_default,
        )
        saved = self.settings_store.save_tracker_workflow_preset(preset)
        self.session_state.workflow_preset = saved
        self._refresh_workflow_preset_choices(saved.preset_id)
        return saved

    def _save_workflow_preset_as(self) -> None:
        try:
            name = self._request_workflow_preset_name(title="전체 설정 새로 저장")
            if name is None:
                return
            preset = self._save_named_workflow_preset(preset_id="", name=name)
        except Exception as exc:
            self.statusBar().showMessage(str(exc))
            self._show_error_dialog("전체 설정 저장 실패", str(exc))
            return
        self.statusBar().showMessage(f"'{preset.name}' 전체 설정을 저장했습니다.")
        self._show_info_dialog(
            "전체 설정 저장",
            f"현재 트래커에 '{preset.name}' 전체 설정을 저장했습니다.",
        )

    def _load_workflow_preset(self) -> None:
        try:
            selected_id = str(self.workflow_preset_combo.currentData() or "")
            if not selected_id:
                self._show_error_dialog("전체 설정 선택", "불러올 전체 설정을 선택하세요.")
                return
            preset = (
                self.settings_store.load_workflow_preset()
                if selected_id == "__legacy__"
                else self.settings_store.get_tracker_workflow_preset(selected_id)
            )
            if preset is None:
                self._show_error_dialog("전체 설정 없음", "저장된 전체 설정이 없습니다.")
                return
            if not self._preset_matches_settings(preset, self._current_settings_snapshot()):
                raise ValueError("현재 프로젝트와 트래커에 속한 저장 설정이 아닙니다.")
            self._apply_workflow_preset(preset)
            self._refresh_workflow_preset_choices(
                preset.preset_id if selected_id != "__legacy__" else "__legacy__"
            )
        except Exception as exc:
            self.statusBar().showMessage(str(exc))
            self._show_error_dialog("전체 설정 불러오기 실패", str(exc))
            return
        self._show_info_dialog(
            "전체 설정 불러오기",
            "전체 설정을 불러왔습니다. 파일과 매핑을 확인한 뒤 다시 검증하세요.",
        )

    def _rename_workflow_preset(self) -> None:
        selected_id = str(self.workflow_preset_combo.currentData() or "")
        if not selected_id or selected_id == "__legacy__":
            self._show_error_dialog("전체 설정 선택", "이름을 바꿀 저장 설정을 선택하세요.")
            return
        try:
            preset = self.settings_store.get_tracker_workflow_preset(selected_id)
            if preset is None:
                raise ValueError("선택한 저장 설정을 찾을 수 없습니다.")
            new_name = self._request_workflow_preset_name(
                title="전체 설정 이름 변경",
                initial_name=preset.name,
            )
            if new_name is None:
                return
            saved = self.settings_store.save_tracker_workflow_preset(
                replace(preset, name=new_name)
            )
            if (
                self.session_state.workflow_preset is not None
                and self.session_state.workflow_preset.preset_id == selected_id
            ):
                self.session_state.workflow_preset = saved
            self._refresh_workflow_preset_choices(saved.preset_id)
        except Exception as exc:
            self.statusBar().showMessage(str(exc))
            self._show_error_dialog("전체 설정 이름 변경 실패", str(exc))
            return
        self.statusBar().showMessage(f"저장 설정 이름을 '{saved.name}'으로 변경했습니다.")

    def _set_default_workflow_preset(self) -> None:
        selected_id = str(self.workflow_preset_combo.currentData() or "")
        if not selected_id or selected_id == "__legacy__":
            self._show_error_dialog("전체 설정 선택", "기본으로 지정할 저장 설정을 선택하세요.")
            return
        try:
            preset = self.settings_store.get_tracker_workflow_preset(selected_id)
            if preset is None:
                raise ValueError("선택한 저장 설정을 찾을 수 없습니다.")
            saved = self.settings_store.save_tracker_workflow_preset(
                replace(preset, is_default=True)
            )
            if (
                self.session_state.workflow_preset is not None
                and self.session_state.workflow_preset.preset_id == selected_id
            ):
                self.session_state.workflow_preset = saved
            self._refresh_workflow_preset_choices(saved.preset_id)
        except Exception as exc:
            self.statusBar().showMessage(str(exc))
            self._show_error_dialog("기본 전체 설정 지정 실패", str(exc))
            return
        self.statusBar().showMessage(f"'{saved.name}'을 기본 전체 설정으로 지정했습니다.")

    def _confirm_workflow_preset_delete(self, name: str) -> bool:
        QMessageBox = self.qt["QMessageBox"]
        answer = QMessageBox.question(
            self,
            "전체 설정 삭제",
            f"'{name}' 저장 설정을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _delete_workflow_preset(self) -> None:
        selected_id = str(self.workflow_preset_combo.currentData() or "")
        if not selected_id or selected_id == "__legacy__":
            self._show_error_dialog("전체 설정 선택", "삭제할 저장 설정을 선택하세요.")
            return
        try:
            preset = self.settings_store.get_tracker_workflow_preset(selected_id)
            if preset is None:
                raise ValueError("선택한 저장 설정을 찾을 수 없습니다.")
            if not self._confirm_workflow_preset_delete(preset.name):
                return
            if not self.settings_store.delete_tracker_workflow_preset(selected_id):
                raise ValueError("선택한 저장 설정을 삭제하지 못했습니다.")
            if (
                self.session_state.workflow_preset is not None
                and self.session_state.workflow_preset.preset_id == selected_id
            ):
                self.session_state.workflow_preset = None
            self._refresh_workflow_preset_choices()
        except Exception as exc:
            self.statusBar().showMessage(str(exc))
            self._show_error_dialog("전체 설정 삭제 실패", str(exc))
            return
        self.statusBar().showMessage(f"'{preset.name}' 저장 설정을 삭제했습니다.")
        self._show_info_dialog("전체 설정 삭제", f"'{preset.name}' 저장 설정을 삭제했습니다.")

    def _show_mapping_page(self) -> None:
        self._show_page(self.mapping_page)

    def _preview_root_item_config(self, root_item_config: dict[str, object]):
        """`preview_root_item_config` 미리보기를 계산한다."""
        if self.session_state.mapping_context is None:
            raise ValueError("루트 데이터 컨텍스트가 준비되지 않았습니다.")
        return self.pipeline_service.build_root_item_preview_context(
            self.session_state.mapping_context,
            root_item_config,
        )

    def _enter_validation_page(self) -> None:
        self._show_page(self.validation_page)

    def _enter_upload_page(self) -> None:
        self.upload_page.reset(0)
        if self.session_state.settings.offline_mode:
            self.upload_page.dry_run_checkbox.setChecked(True)
            self.upload_page.dry_run_checkbox.setEnabled(False)
            self.upload_page.status_label.setText("테스트 모드에서는 Dry Run만 실행할 수 있습니다.")
        else:
            self.upload_page.dry_run_checkbox.setEnabled(True)
            action_label = gui_upload_mode_action_label(
                getattr(self.session_state.settings, "upload_mode", None)
            )
            self.upload_page.status_label.setText(f"{action_label} 준비 완료")
        self._show_page(self.upload_page)

    def _enter_result_page(self) -> None:
        if self.session_state.upload_result is not None:
            self.result_page.set_results(self.session_state.upload_result)
        self._show_page(self.result_page)

    def _restart_upload_flow(self) -> None:
        self.session_state.validation_context = None
        self.session_state.upload_result = None
        self.upload_progress = UploadProgressState()
        self._show_page(self.project_page)

    def _on_prepare_root_item_context(self) -> None:
        settings = self.session_state.settings
        if not settings.default_project_id or not settings.default_tracker_id:
            raise ValueError("프로젝트와 트래커를 먼저 선택해야 합니다.")
        mapping_context = self._run_with_busy(
            "매핑 대상 컬럼과 스키마를 준비하는 중입니다.",
            self.pipeline_service.prepare_mapping_context,
            settings,
            self.session_state.file_state,
        )
        if (
            self.session_state.workflow_preset is not None
            and self._preset_matches_settings(
                self.session_state.workflow_preset,
                settings,
            )
        ):
            self._apply_workflow_preset_to_mapping_context(
                mapping_context,
                self.session_state.workflow_preset,
            )
        self.session_state.mapping_context = mapping_context
        upload_mode = normalize_gui_upload_mode(mapping_context.upload_mode)
        if upload_mode == GUI_UPLOAD_MODE_UPDATE:
            self._attach_navigation(
                self.mapping_page,
                previous_page=self.file_page,
                next_page=self.validation_page,
                next_handler=self._enter_validation_page,
            )
            self.mapping_page.load_context(
                self.session_state.mapping_context.upload_mode,
                self.session_state.mapping_context.upload_columns,
                self.session_state.mapping_context.schema_df,
                self.session_state.mapping_context.selected_mapping,
                self.session_state.mapping_context.selected_mapping_modes,
                self.session_state.mapping_context.default_value_candidates,
                self.session_state.mapping_context.selected_default_values,
                self.session_state.mapping_context.selected_default_value_modes,
                self.session_state.mapping_context.selected_tracker_item_settings,
                self.session_state.mapping_context.wizard.state.upload_df,
            )
            self._show_page(self.mapping_page)
            return

        self._attach_navigation(
            self.mapping_page,
            previous_page=self.root_item_field_page,
            next_page=self.validation_page,
            next_handler=self._enter_validation_page,
        )
        root_preview_context = self.pipeline_service.build_root_item_preview_context(
            mapping_context,
            mapping_context.root_item_config,
        )
        self.root_item_structure_page.load_context(root_preview_context)
        self.root_item_field_page.load_context(root_preview_context)
        self._show_page(self.root_item_structure_page)

    def _on_confirm_root_item_structure_config(self) -> None:
        if self.session_state.mapping_context is None:
            raise ValueError("매핑 컨텍스트가 준비되지 않았습니다.")
        root_item_config = _merge_root_item_page_configs(
            self.session_state.mapping_context.root_item_config,
            structure_config=(
                self.root_item_structure_page.get_config()
                if callable(getattr(self.root_item_structure_page, "get_config", None))
                else None
            ),
            field_config=(
                self.root_item_field_page.get_config()
                if callable(getattr(self.root_item_field_page, "get_config", None))
                else None
            ),
        )
        self.session_state.mapping_context.root_item_config = root_item_config
        root_preview_context = self.pipeline_service.build_root_item_preview_context(
            self.session_state.mapping_context,
            self.session_state.mapping_context.root_item_config,
        )
        self.root_item_field_page.load_context(root_preview_context)
        self._show_page(self.root_item_field_page)

    def _on_confirm_root_item_field_config(self) -> None:
        if self.session_state.mapping_context is None:
            raise ValueError("매핑 컨텍스트가 준비되지 않았습니다.")
        self.session_state.mapping_context.root_item_config = self.root_item_field_page.get_config()
        self.mapping_page.load_context(
            self.session_state.mapping_context.upload_mode,
            self.session_state.mapping_context.upload_columns,
            self.session_state.mapping_context.schema_df,
            self.session_state.mapping_context.selected_mapping,
            self.session_state.mapping_context.selected_mapping_modes,
            self.session_state.mapping_context.default_value_candidates,
            self.session_state.mapping_context.selected_default_values,
            self.session_state.mapping_context.selected_default_value_modes,
            self.session_state.mapping_context.selected_tracker_item_settings,
            self.session_state.mapping_context.wizard.state.upload_df,
        )
        self._show_page(self.mapping_page)

    def _validate_mapping(
        self,
        selected_mapping: dict[str, str],
        selected_mapping_modes: dict[str, dict[str, bool]],
        selected_default_values: dict[str, str],
        selected_default_value_modes: dict[str, dict[str, bool]],
        selected_tracker_item_settings: dict[str, dict[str, object]],
    ) -> None:
        """`validate_mapping` 입력을 검증한다."""
        if self.session_state.mapping_context is None:
            raise ValueError("매핑 컨텍스트가 준비되지 않았습니다.")
        validation_context = self._run_with_busy(
            "매핑을 검증하고 payload를 준비하는 중입니다.",
            self.pipeline_service.validate_mapping,
            self.session_state.mapping_context,
            selected_mapping,
            selected_default_values,
            selected_tracker_item_settings,
            selected_mapping_modes=selected_mapping_modes,
            selected_default_value_modes=selected_default_value_modes,
        )
        self.session_state.validation_context = validation_context
        self.validation_page.set_results(
            validation_context.issue_df,
            validation_context.has_blocking_issues,
            validation_context.summary_stats,
        )
