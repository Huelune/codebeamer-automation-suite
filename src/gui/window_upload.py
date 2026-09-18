from __future__ import annotations

import time
from pathlib import Path

from src.upload_policy import upload_mode_action_label as gui_upload_mode_action_label

from .activity_history import ActivityOperation
from .activity_history import ActivityRecord
from .activity_history import ActivityResult
from .upload_workbook_tools import UploadWorkbookService
from .window_support import UploadProgressState
from .window_support import _format_clock_text
from .window_support import _format_duration_text
from .window_support import _format_upload_eta_text
from .window_support import _format_upload_progress_text
from .worker import UploadWorker


class WindowUploadMixin:
    def _connect_upload_workbook_actions(self) -> None:
        """검증/결과 페이지의 Excel 도구와 실패 재시도 동작을 연결한다."""
        self.upload_workbook_service = UploadWorkbookService()
        self.validation_page.request_export_validation = (
            self._export_validation_report
        )
        self.validation_page.request_export_template = (
            self._export_tracker_upload_template
        )
        self.result_page.request_export_failed = self._export_failed_upload_report
        self.result_page.request_retry_failed = self._start_failed_upload_retry

    @staticmethod
    def _xlsx_output_path(path: str) -> str:
        normalized = str(path or "").strip()
        if normalized and not normalized.lower().endswith(".xlsx"):
            normalized += ".xlsx"
        return normalized

    def _select_workbook_output_path(self, title: str, filename: str) -> str:
        from PySide6.QtWidgets import QFileDialog

        output_dir = Path(self.session_state.settings.output_dir).expanduser()
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(output_dir / filename),
            "Excel 통합 문서 (*.xlsx)",
        )
        return self._xlsx_output_path(selected_path)

    def _export_validation_report(self) -> None:
        validation_context = self.session_state.validation_context
        if validation_context is None:
            self._show_error_dialog(
                "검증 결과 내보내기",
                "먼저 매핑 검증을 실행하세요.",
            )
            return
        output_path = self._select_workbook_output_path(
            "검증 결과 Excel 내보내기",
            "validation_report.xlsx",
        )
        if not output_path:
            return
        try:
            result = self._run_with_busy(
                "검증 결과 Excel을 만드는 중입니다.",
                self.upload_workbook_service.export_validation_report,
                validation_context.issue_df,
                validation_context.summary_stats,
                output_path,
            )
        except Exception as exc:
            message = str(exc) or "검증 결과를 저장하지 못했습니다."
            self.validation_page.status_label.setText(message)
            self._show_error_dialog("검증 결과 내보내기 실패", message)
            return
        self._show_info_dialog(
            "검증 결과 내보내기",
            f"검증 결과 {result.row_count}건을 저장했습니다.\n{result.output_path}",
        )

    def _export_tracker_upload_template(self) -> None:
        mapping_context = self.session_state.mapping_context
        if mapping_context is None:
            self._show_error_dialog(
                "업로드 템플릿 내보내기",
                "트래커와 파일을 선택해 매핑 정보를 먼저 준비하세요.",
            )
            return
        tracker_id = str(
            getattr(self.session_state.settings, "default_tracker_id", "") or ""
        ).strip()
        filename = (
            f"tracker_{tracker_id}_upload_template.xlsx"
            if tracker_id
            else "tracker_upload_template.xlsx"
        )
        output_path = self._select_workbook_output_path(
            "트래커 업로드 템플릿 내보내기",
            filename,
        )
        if not output_path:
            return
        try:
            result = self._run_with_busy(
                "트래커 업로드 템플릿을 만드는 중입니다.",
                self.upload_workbook_service.export_tracker_template,
                mapping_context.schema_df,
                output_path,
                upload_mode=mapping_context.upload_mode,
                summary_column=mapping_context.summary_column,
            )
        except Exception as exc:
            message = str(exc) or "업로드 템플릿을 저장하지 못했습니다."
            self._show_error_dialog("업로드 템플릿 내보내기 실패", message)
            return
        self._show_info_dialog(
            "업로드 템플릿 내보내기",
            f"트래커 필드 {result.column_count}개를 포함한 템플릿을 저장했습니다.\n{result.output_path}",
        )

    def _export_failed_upload_report(self) -> None:
        upload_result = self.session_state.upload_result or {}
        failed_df = upload_result.get("failed_df")
        unresolved_df = upload_result.get("unresolved_df")
        if (
            (failed_df is None or getattr(failed_df, "empty", True))
            and (unresolved_df is None or getattr(unresolved_df, "empty", True))
        ):
            self._show_error_dialog(
                "실패 보고서 내보내기",
                "내보낼 실패 또는 미해결 항목이 없습니다.",
            )
            return
        output_path = self._select_workbook_output_path(
            "실패 보고서 Excel 내보내기",
            "upload_failed_report.xlsx",
        )
        if not output_path:
            return
        try:
            result = self._run_with_busy(
                "실패 보고서 Excel을 만드는 중입니다.",
                self.upload_workbook_service.export_failed_upload_report,
                failed_df,
                unresolved_df,
                output_path,
            )
        except Exception as exc:
            message = str(exc) or "실패 보고서를 저장하지 못했습니다."
            self.result_page.status_label.setText(message)
            self._show_error_dialog("실패 보고서 내보내기 실패", message)
            return
        self.result_page.status_label.setText(
            f"실패/미해결 보고서 {result.row_count}건을 저장했습니다."
        )
        self._show_info_dialog(
            "실패 보고서 내보내기",
            f"실패/미해결 결과 {result.row_count}건을 저장했습니다.\n{result.output_path}",
        )

    def _start_failed_upload_retry(self) -> None:
        if self.upload_worker is not None:
            self._show_error_dialog(
                "실패 항목 재시도",
                "현재 실행 중인 업로드가 끝난 뒤 재시도하세요.",
            )
            return
        upload_result = self.session_state.upload_result or {}
        retry_context = upload_result.get("retry_context")
        retry_target_count = int(
            getattr(retry_context, "retry_target_count", 0) or 0
        )
        if retry_target_count <= 0:
            message = str(upload_result.get("retry_unavailable_reason") or "") or (
                "자동 재시도할 수 있는 실패 항목이 없습니다. "
                "파일 준비, 매핑 또는 데이터 오류는 검증 단계에서 수정하세요."
            )
            self.result_page.status_label.setText(message)
            self._show_error_dialog("실패 항목 재시도", message)
            return

        QMessageBox = self.qt["QMessageBox"]
        answer = QMessageBox.question(
            self,
            "실패 항목 재시도",
            (
                f"현재 세션에서 실패하거나 상위 항목이 미해결인 {retry_target_count}건만 다시 실행합니다.\n"
                "이미 성공한 항목과 파일 로딩·매핑 과정은 다시 실행하지 않습니다. 계속할까요?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        output_dir = str(Path(self.session_state.settings.output_dir))
        self.upload_page.reset(retry_target_count)
        self._activity_dry_run = bool(retry_context.dry_run)
        self._retry_in_progress = True
        self.upload_progress = UploadProgressState(
            retry_count=retry_target_count,
            batch_started_at=time.perf_counter(),
        )
        self.upload_worker = UploadWorker(
            self.pipeline_service,
            settings=self.session_state.settings,
            file_state=self.session_state.file_state,
            mapping_context=self.session_state.mapping_context,
            dry_run=bool(retry_context.dry_run),
            continue_on_error=self.upload_page.continue_checkbox.isChecked(),
            output_dir=output_dir,
            retry_context=retry_context,
        )
        self.upload_worker.progress_changed.connect(self._on_upload_progress)
        self.upload_worker.upload_event.connect(self._on_upload_event)
        self.upload_worker.upload_finished.connect(self._on_upload_finished)
        self.upload_worker.upload_failed.connect(self._on_upload_failed)
        self.result_page.retry_failed_button.setEnabled(False)
        self.result_page.status_label.setText(
            f"실패/미해결 {retry_target_count}건을 재시도하는 중입니다."
        )
        self.upload_page.start_button.setEnabled(False)
        self.upload_page.pause_button.setEnabled(True)
        self.upload_page.cancel_button.setEnabled(True)
        self.upload_page.status_label.setText("실패 항목 재시도 중")
        self._show_page(self.upload_page)
        try:
            self.upload_worker.start()
        except Exception as exc:
            self._on_upload_failed(str(exc) or "실패 항목 재시도를 시작하지 못했습니다.")

    def _start_upload(self) -> None:
        if self.session_state.mapping_context is None:
            self.upload_page.status_label.setText("업로드 컨텍스트가 없습니다.")
            return
        if self.session_state.settings.offline_mode and not self.upload_page.dry_run_checkbox.isChecked():
            message = "테스트 모드에서는 Dry Run만 실행할 수 있습니다."
            self.upload_page.status_label.setText(message)
            self._show_error_dialog("테스트 모드 업로드 제한", message)
            return
        output_dir = str(Path(self.session_state.settings.output_dir))
        self.upload_page.reset(0)
        self._activity_dry_run = bool(self.upload_page.dry_run_checkbox.isChecked())
        self.upload_progress = UploadProgressState(
            batch_started_at=time.perf_counter()
        )
        self._retry_in_progress = False
        self.upload_worker = UploadWorker(
            self.pipeline_service,
            settings=self.session_state.settings,
            file_state=self.session_state.file_state,
            mapping_context=self.session_state.mapping_context,
            dry_run=self.upload_page.dry_run_checkbox.isChecked(),
            continue_on_error=self.upload_page.continue_checkbox.isChecked(),
            output_dir=output_dir,
        )
        self.upload_worker.progress_changed.connect(self._on_upload_progress)
        self.upload_worker.upload_event.connect(self._on_upload_event)
        self.upload_worker.upload_finished.connect(self._on_upload_finished)
        self.upload_worker.upload_failed.connect(self._on_upload_failed)
        self.upload_page.start_button.setEnabled(False)
        self.upload_page.pause_button.setEnabled(True)
        self.upload_page.cancel_button.setEnabled(True)
        action_label = gui_upload_mode_action_label(
            getattr(self.session_state.settings, "upload_mode", None)
        )
        self.upload_page.status_label.setText(f"{action_label} 실행 중")
        try:
            self.upload_worker.start()
        except Exception as exc:
            self._on_upload_failed(str(exc) or "업로드 작업을 시작하지 못했습니다.")

    def _pause_upload(self) -> None:
        if self.upload_worker is not None:
            self.upload_worker.request_pause()
            self.upload_page.pause_button.setEnabled(False)
            self.upload_page.resume_button.setEnabled(True)
            self.upload_page.status_label.setText("일시정지 요청됨")

    def _resume_upload(self) -> None:
        if self.upload_worker is not None:
            self.upload_worker.request_resume()
            self.upload_page.pause_button.setEnabled(True)
            self.upload_page.resume_button.setEnabled(False)
            self.upload_page.status_label.setText("업로드 재개")

    def _cancel_upload(self) -> None:
        if self.upload_worker is not None:
            self.upload_worker.request_cancel()
            self.upload_page.status_label.setText("중단 요청됨")

    @staticmethod
    def _format_clock(timestamp: float | None = None) -> str:
        return _format_clock_text(timestamp)

    @staticmethod
    def _format_duration(seconds: float | None) -> str:
        return _format_duration_text(seconds)

    @staticmethod
    def _upload_event_key(event: dict[str, object]) -> str:
        source_file_path = str(event.get("source_file_path") or "").strip()
        row_id = event.get("row_id")
        if row_id is None:
            return f"{source_file_path}::__root__::{str(event.get('upload_name') or '').strip()}"
        return f"{source_file_path}::{row_id}"

    @staticmethod
    def _display_item_name(file_label: str, upload_name: str) -> str:
        prefix = f"[{file_label}] "
        if file_label and upload_name.startswith(prefix):
            return upload_name[len(prefix):].strip() or upload_name
        return upload_name or "-"

    @staticmethod
    def _normalize_phase_key(phase: object) -> str:
        normalized = str(phase or "").strip().lower()
        if normalized == "create":
            return "insert"
        return normalized

    @classmethod
    def _phase_display_name(cls, phase: object) -> str:
        phase_key = cls._normalize_phase_key(phase)
        if phase_key == "insert":
            return "생성"
        if phase_key == "update":
            return "수정"
        return "-"

    @staticmethod
    def _count_phase_rows(df, phase: str) -> int:
        if df is None or getattr(df, "empty", True) or "phase" not in df.columns:
            return 0
        phase_series = df["phase"].fillna("").astype(str).str.lower()
        return int(phase_series.eq(phase).sum())

    @staticmethod
    def _activity_entity_name(values, entity_id: int | None) -> str:
        if entity_id is None:
            return ""
        for value in values or []:
            if isinstance(value, dict):
                raw_id = (
                    value.get("id")
                    or value.get("projectId")
                    or value.get("trackerId")
                )
                name = value.get("name") or value.get("label") or ""
            else:
                raw_id = (
                    getattr(value, "id", None)
                    or getattr(value, "project_id", None)
                    or getattr(value, "tracker_id", None)
                )
                name = getattr(value, "name", "")
            try:
                if int(raw_id) != int(entity_id):
                    continue
            except (TypeError, ValueError):
                continue
            return str(name or "")
        return ""

    @staticmethod
    def _activity_positive_int(value) -> int | None:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    def _record_batch_activity(
        self,
        result: ActivityResult,
        *,
        summary: str,
        success_count: int,
        failed_count: int,
        unresolved_count: int,
    ) -> None:
        settings = self.session_state.settings
        project_id = self._activity_positive_int(settings.default_project_id)
        tracker_id = self._activity_positive_int(settings.default_tracker_id)
        mapping_context = self.session_state.mapping_context
        file_count = (
            len(mapping_context.file_paths) if mapping_context is not None else 0
        )
        upload_mode = str(
            (
                getattr(mapping_context, "upload_mode", "")
                if mapping_context is not None
                else ""
            )
            or getattr(settings, "upload_mode", "")
            or ""
        )
        elapsed = (
            None
            if self.upload_progress.batch_started_at is None
            else max(time.perf_counter() - self.upload_progress.batch_started_at, 0.0)
        )
        action_label = gui_upload_mode_action_label(
            upload_mode
        )
        self._record_activity(
            ActivityRecord.create(
                ActivityOperation.BATCH_UPLOAD,
                result,
                source="batch_upload",
                summary=summary,
                project_id=project_id,
                project_name=self._activity_entity_name(
                    self.session_state.projects,
                    project_id,
                ),
                tracker_id=tracker_id,
                tracker_name=self._activity_entity_name(
                    self.session_state.trackers,
                    tracker_id,
                ),
                item_name=f"{action_label} · {file_count}개 파일",
                details={
                    "upload_mode": upload_mode,
                    "dry_run": bool(getattr(self, "_activity_dry_run", False)),
                    "file_count": file_count,
                    "success_count": int(success_count),
                    "failed_count": int(failed_count),
                    "unresolved_count": int(unresolved_count),
                    "duration_seconds": None if elapsed is None else round(elapsed, 3),
                    "phase_totals": dict(self.upload_progress.phase_totals),
                    "phase_counts": dict(self.upload_progress.phase_counts),
                },
            )
        )

    def _append_timestamped_log(self, message: str) -> None:
        text = str(message or "").strip()
        if not text:
            return
        self.upload_page.log_view.appendPlainText(f"{self._format_clock()} | {text}")

    def _update_upload_counter(self) -> None:
        progress = self.upload_progress
        self.upload_page.counter_label.setText(
            f"성공 {progress.success_count} / 실패 {progress.failed_count} / 재시도 {progress.retry_count}"
        )
        completed_count = progress.success_count + progress.failed_count
        self.upload_page.total_label.setText(
            f"총 대상 {progress.total_count}건 / 완료 {completed_count}건"
        )
        self.upload_page.phase_total_label.setText(
            "단계별 총 대상: "
            f"생성 {int(progress.phase_totals.get('insert', 0))}건 / "
            f"수정 {int(progress.phase_totals.get('update', 0))}건"
        )
        self.upload_page.phase_counter_label.setText(
            "단계별 결과: "
            f"생성 성공 {int(progress.phase_counts.get('insert_success', 0))} / "
            f"실패 {int(progress.phase_counts.get('insert_failed', 0))} | "
            f"수정 성공 {int(progress.phase_counts.get('update_success', 0))} / "
            f"실패 {int(progress.phase_counts.get('update_failed', 0))}"
        )

    def _update_upload_progress_widgets(self) -> None:
        total = max(int(self.upload_progress.total), 0)
        completed = max(int(self.upload_progress.current), 0)
        clamped_completed = min(completed, total) if total > 0 else 0
        self.upload_page.progress_bar.setMaximum(max(total, 1))
        self.upload_page.progress_bar.setValue(clamped_completed)
        progress_text = _format_upload_progress_text(clamped_completed, total)
        self.upload_page.progress_label.setText(progress_text)
        self.upload_page.progress_bar.setFormat(progress_text.replace("진행률 ", ""))

    def _update_upload_time_label(self) -> None:
        if self.upload_progress.batch_started_at is None:
            self.upload_page.time_label.setText("배치 시간: -")
            self.upload_page.eta_label.setText("예상 종료: -")
            return
        elapsed = time.perf_counter() - self.upload_progress.batch_started_at
        self.upload_page.time_label.setText(
            f"배치 시간: {self._format_duration(elapsed)} 경과 (현재 시각 {self._format_clock()})"
        )
        self.upload_page.eta_label.setText(
            _format_upload_eta_text(
                now_timestamp=time.time(),
                elapsed_seconds=elapsed,
                completed_count=self.upload_progress.current,
                total_count=self.upload_progress.total,
            )
        )

    def _on_upload_event(self, event: dict) -> None:
        event_type = str(event.get("type") or "")
        message = str(event.get("message") or "").strip()
        raw_item_name = str(event.get("upload_name") or "-").strip() or "-"
        file_label = str(event.get("source_file") or "").strip() or "-"
        item_name = self._display_item_name(file_label, raw_item_name)
        row_key = self._upload_event_key(event)

        self._update_upload_time_label()

        if event_type == "log":
            self._append_timestamped_log(message)
            return

        if event_type == "batch_total":
            self.upload_progress.total_count = int(event.get("total") or 0)
            phase_totals = event.get("phase_totals") or {}
            self.upload_progress.phase_totals = {
                "insert": int(phase_totals.get("insert") or 0),
                "update": int(phase_totals.get("update") or 0),
            }
            self.upload_progress.total = self.upload_progress.total_count
            self._update_upload_progress_widgets()
            self._update_upload_counter()
            self._append_timestamped_log(
                f"총 업로드 예정 건수: {self.upload_progress.total_count}"
            )
            return

        if event_type == "phase_started":
            self.upload_progress.current_phase = self._normalize_phase_key(
                event.get("phase")
            )
            phase_name = self._phase_display_name(
                self.upload_progress.current_phase
            )
            total = int(event.get("total") or 0)
            self.upload_page.phase_label.setText(f"현재 단계: {phase_name} ({total}건)")
            self.upload_page.status_label.setText(f"{phase_name} 단계 실행 중")
            self._append_timestamped_log(f"{phase_name} 단계 시작 | 대상 {total}건")
            return

        if event_type == "phase_finished":
            phase_key = self._normalize_phase_key(event.get("phase"))
            phase_name = self._phase_display_name(phase_key)
            success_count = int(event.get("success") or 0)
            failed_count = int(event.get("failed") or 0)
            unresolved_count = int(event.get("unresolved") or 0)
            self._append_timestamped_log(
                f"{phase_name} 단계 완료 | 성공 {success_count} / 실패 {failed_count} / 미해결 {unresolved_count}"
            )
            if self.upload_progress.current_phase == phase_key:
                self.upload_page.phase_label.setText(f"현재 단계: {phase_name} 완료")
            return

        if event_type == "row_started":
            started_at = time.perf_counter()
            self.upload_progress.event_started_at[row_key] = started_at
            phase_name = self._phase_display_name(event.get("phase"))
            self.upload_page.record_activity_started(
                row_key,
                file_label,
                phase_name,
                item_name,
                self._format_clock(),
            )
            self._append_timestamped_log(f"{phase_name} 시작 | {raw_item_name}")
            return

        if event_type not in {"row_success", "row_failed"}:
            return

        started_at = self.upload_progress.event_started_at.get(row_key)
        elapsed = None if started_at is None else (time.perf_counter() - started_at)
        if event_type == "row_success":
            self.upload_progress.success_count += 1
            phase_key = self._normalize_phase_key(event.get("phase"))
            if phase_key == "insert":
                self.upload_progress.phase_counts["insert_success"] += 1
            elif phase_key == "update":
                self.upload_progress.phase_counts["update_success"] += 1
            status_text = "성공"
            if not message:
                message = "업로드 완료"
        else:
            self.upload_progress.failed_count += 1
            phase_key = self._normalize_phase_key(event.get("phase"))
            if phase_key == "insert":
                self.upload_progress.phase_counts["insert_failed"] += 1
            elif phase_key == "update":
                self.upload_progress.phase_counts["update_failed"] += 1
            status_text = "실패"
            if not message:
                message = "업로드 실패"
            response_json = event.get("response_json")
            if response_json not in (None, ""):
                self.upload_page.response_view.setPlainText(str(response_json))
                if hasattr(self.upload_page, "detail_tabs") and hasattr(self.upload_page, "response_tab"):
                    self.upload_page.detail_tabs.setCurrentWidget(self.upload_page.response_tab)
        phase_name = self._phase_display_name(event.get("phase"))

        self.upload_page.record_activity_finished(
            row_key,
            file_label,
            phase_name,
            item_name,
            status=status_text,
            finished_at=self._format_clock(),
            duration_text=self._format_duration(elapsed),
            message=message,
        )
        self._update_upload_counter()
        self._update_upload_time_label()
        self._append_timestamped_log(f"{phase_name} {status_text} | {message}")

    def _on_upload_progress(self, current: int, total: int, upload_name: str) -> None:
        self.upload_progress.current = max(int(current), 0)
        self.upload_progress.total = max(int(total), 0)
        self._update_upload_progress_widgets()
        phase_name = self._phase_display_name(self.upload_progress.current_phase)
        if phase_name != "-":
            self.upload_page.current_label.setText(f"현재 항목: [{phase_name}] {upload_name or '-'}")
        else:
            self.upload_page.current_label.setText(f"현재 항목: {upload_name or '-'}")
        self._update_upload_time_label()

    def _on_upload_finished(self, result: dict) -> None:
        was_retry = bool(getattr(self, "_retry_in_progress", False))
        was_cancelled = bool(result.get("cancelled"))
        self._retry_in_progress = False
        self.session_state.upload_result = result
        self.upload_worker = None
        success_df = result.get("success_df")
        failed_df = result.get("failed_df")
        unresolved_df = result.get("unresolved_df")
        activity_success_df = (
            result.get("retry_success_df") if was_retry else success_df
        )
        activity_failed_df = (
            result.get("retry_failed_df") if was_retry else failed_df
        )
        activity_unresolved_df = (
            result.get("retry_unresolved_df") if was_retry else unresolved_df
        )
        self.upload_progress.success_count = (
            0 if activity_success_df is None else len(activity_success_df)
        )
        self.upload_progress.failed_count = (
            0 if activity_failed_df is None else len(activity_failed_df)
        )
        self.upload_progress.retry_count = (
            int(result.get("retry_attempted_count") or 0) if was_retry else 0
        )
        if was_retry:
            phase_results = {
                phase_name: {
                    "success": self._count_phase_rows(
                        activity_success_df,
                        phase_name,
                    ),
                    "failed": self._count_phase_rows(
                        activity_failed_df,
                        phase_name,
                    ),
                    "unresolved": self._count_phase_rows(
                        activity_unresolved_df,
                        phase_name,
                    ),
                }
                for phase_name in ("insert", "update")
            }
            for phase_counts in phase_results.values():
                phase_counts["total"] = (
                    phase_counts["success"]
                    + phase_counts["failed"]
                    + phase_counts["unresolved"]
                )
        else:
            phase_results = result.get("phase_results") or {}
        self.upload_progress.phase_totals = {
            "insert": int((phase_results.get("insert") or {}).get("total", self.upload_progress.phase_totals.get("insert", 0)) or 0),
            "update": int((phase_results.get("update") or {}).get("total", self.upload_progress.phase_totals.get("update", 0)) or 0),
        }
        self.upload_progress.phase_counts = {
            "insert_success": int((phase_results.get("insert") or {}).get("success", self._count_phase_rows(success_df, "insert")) or 0),
            "insert_failed": int(
                ((phase_results.get("insert") or {}).get("failed", 0) or 0)
                + self._count_phase_rows(activity_unresolved_df, "insert")
            ),
            "update_success": int((phase_results.get("update") or {}).get("success", self._count_phase_rows(success_df, "update")) or 0),
            "update_failed": int(
                ((phase_results.get("update") or {}).get("failed", 0) or 0)
                + self._count_phase_rows(activity_unresolved_df, "update")
            ),
        }
        self.upload_progress.current = (
            self.upload_progress.success_count
            + self.upload_progress.failed_count
            + (0 if activity_unresolved_df is None else len(activity_unresolved_df))
        )
        if was_retry:
            self.upload_progress.total_count = int(
                result.get("retry_attempted_count") or 0
            )
            self.upload_progress.total = self.upload_progress.total_count
        self._update_upload_progress_widgets()
        self._update_upload_counter()
        if activity_failed_df is not None and not getattr(activity_failed_df, "empty", True) and "error_response_json" in activity_failed_df.columns:
            self.upload_page.response_view.setPlainText(str(activity_failed_df.iloc[0].get("error_response_json") or ""))
            if hasattr(self.upload_page, "detail_tabs") and hasattr(self.upload_page, "response_tab"):
                self.upload_page.detail_tabs.setCurrentWidget(self.upload_page.response_tab)
        elif was_retry:
            self.upload_page.response_view.clear()
        self._update_upload_time_label()
        self.upload_page.eta_label.setText(
            f"예상 종료: {'중단됨' if was_cancelled else '완료됨'} ({self._format_clock()})"
        )
        self._append_timestamped_log(
            "업로드가 사용자 요청으로 중단되었습니다. 처리 결과와 재시도 대상을 보존했습니다."
            if was_cancelled
            else (
                "실패 항목 재시도가 완료되었습니다."
                if was_retry
                else "배치 업로드가 완료되었습니다."
            )
        )
        self.upload_page.status_label.setText(
            "재시도 중단됨"
            if was_cancelled and was_retry
            else "업로드 중단됨"
            if was_cancelled
            else "재시도 완료"
            if was_retry
            else "업로드 완료"
        )
        self.upload_page.phase_label.setText(
            "현재 단계: 중단" if was_cancelled else "현재 단계: 완료"
        )
        self.upload_page.start_button.setEnabled(True)
        self.upload_page.pause_button.setEnabled(False)
        self.upload_page.resume_button.setEnabled(False)
        self.upload_page.cancel_button.setEnabled(False)
        self.upload_page.result_button.setEnabled(True)
        if hasattr(self, "result_page"):
            self.result_page.set_results(result)
        activity_unresolved_count = (
            0 if activity_unresolved_df is None else len(activity_unresolved_df)
        )
        remaining_failed_count = 0 if failed_df is None else len(failed_df)
        remaining_unresolved_count = (
            0 if unresolved_df is None else len(unresolved_df)
        )
        result_status = (
            ActivityResult.CANCELLED
            if was_cancelled
            else ActivityResult.PARTIAL
            if self.upload_progress.failed_count or activity_unresolved_count
            else ActivityResult.SUCCESS
        )
        if was_retry:
            execution_label = (
                "실패 항목 Dry Run 재시도"
                if bool(getattr(self, "_activity_dry_run", False))
                else "실패 항목 재시도"
            )
        else:
            execution_label = (
                "배치 Dry Run"
                if bool(getattr(self, "_activity_dry_run", False))
                else "배치 작업"
            )
        self._record_batch_activity(
            result_status,
            summary=(
                f"{execution_label} {'중단' if was_cancelled else '완료'}: "
                f"성공 {self.upload_progress.success_count}건, "
                f"실패 {self.upload_progress.failed_count}건, 미해결 {activity_unresolved_count}건"
            ),
            success_count=self.upload_progress.success_count,
            failed_count=self.upload_progress.failed_count,
            unresolved_count=activity_unresolved_count,
        )
        if not was_cancelled and (remaining_failed_count or remaining_unresolved_count):
            self._show_error_dialog(
                "업로드 결과 확인 필요",
                (
                    f"{'재시도' if was_retry else '배치 업로드'}는 종료되었지만 "
                    f"실패 {remaining_failed_count}건, 미해결 {remaining_unresolved_count}건이 남아 있습니다."
                ),
            )

    def _on_upload_failed(self, message: str) -> None:
        self._retry_in_progress = False
        self.upload_worker = None
        self.upload_page.status_label.setText(message)
        self._update_upload_time_label()
        self.upload_page.eta_label.setText(f"예상 종료: 중단됨 ({self._format_clock()})")
        self._append_timestamped_log(message)
        self.upload_page.start_button.setEnabled(True)
        self.upload_page.pause_button.setEnabled(False)
        self.upload_page.resume_button.setEnabled(False)
        self.upload_page.cancel_button.setEnabled(False)
        self.upload_page.result_button.setEnabled(True)
        cancelled = "사용자 요청으로 중단" in str(message)
        self._record_batch_activity(
            ActivityResult.CANCELLED if cancelled else ActivityResult.FAILED,
            summary=(
                "배치 작업이 사용자 요청으로 중단되었습니다."
                if cancelled
                else "배치 작업에 실패했습니다. 배치 화면의 로그를 확인하세요."
            ),
            success_count=self.upload_progress.success_count,
            failed_count=self.upload_progress.failed_count,
            unresolved_count=0,
        )
        if not cancelled:
            self._show_error_dialog("업로드 오류", message)
