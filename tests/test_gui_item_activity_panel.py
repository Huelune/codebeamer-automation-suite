from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import Qt


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.activity_history import ActivityOperation
from src.gui.activity_history import ActivityResult
from src.gui.item_activity import ActivityScope
from src.gui.item_activity import BaselineMarker
from src.gui.item_activity import ItemActivityKind
from src.gui.item_activity_export import ItemActivityExportError
from src.gui.item_activity_export import ItemActivityExportSummary
from src.gui.item_activity_panel import ALL_SCOPE_DATA
from src.gui.item_activity_panel import ItemActivityPanel
from src.gui.item_activity_panel import run_activity_export
from src.gui.tracker_baseline_compare import TrackerBaseline
from src.gui.tracker_comment_models import ItemCommentsSnapshot
from src.gui.tracker_content_models import AttachmentSummary
from src.gui.tracker_item_context_models import ItemHistorySnapshot
from tests.gui_widget_cleanup import tearDownModule  # noqa: F401


FIELD = ItemActivityKind.FIELD_CHANGE
COMMENT = ItemActivityKind.COMMENT
ATTACHMENT = ItemActivityKind.ATTACHMENT


def _version(version: int, at: str, *changes: tuple[int, str, str | None, str]) -> dict:
    return {
        "itemRevision": {"version": version},
        "modifiedAt": at,
        "modifiedBy": {"displayName": "Sample User A"},
        "changes": [
            {
                "field": {"id": field_id, "name": name},
                "oldValue": None if old is None else {"fieldId": field_id, "value": old},
                "newValue": {"fieldId": field_id, "value": new},
            }
            for field_id, name, old, new in changes
        ],
    }


HISTORY = ItemHistorySnapshot.from_raw(
    {
        "versions": [
            _version(4, "2026-07-21T09:30:00Z", (101, "Risk Level", "Medium", "High")),
            _version(3, "2026-07-20T09:00:00Z", (101, "Risk Level", None, "Medium")),
            _version(2, "2026-07-19T08:00:00Z", (3, "Summary", "Old", "New")),
            {"itemRevision": {"version": 1}, "modifiedAt": "2026-07-01T00:00:00Z", "changeSummary": "Created"},
        ]
    }
)
COMMENTS = ItemCommentsSnapshot.from_raw(
    [
        {
            "id": 51001,
            "createdBy": {"displayName": "Sample User B"},
            "createdAt": "2026-07-20T09:10:00Z",
            "comment": "Review note",
        }
    ]
)
ATTACHMENTS = (
    AttachmentSummary(53001, "anonymous-spec.txt", size=2048, modified_at="2026-07-18T11:00:00Z"),
    AttachmentSummary(53002, "anonymous-draft.txt", size=512, modified_at="2026-07-10T08:00:00Z"),
)
SOURCES = {FIELD: HISTORY, COMMENT: COMMENTS, ATTACHMENT: ATTACHMENTS}
BASELINES = (
    TrackerBaseline(11, "Sample Baseline", "2026-07-19T08:00:00Z"),
    TrackerBaseline(12, "No Time Baseline", ""),
)


class ItemActivityPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.requests: list[tuple[ItemActivityKind, bool]] = []
        self.panel = ItemActivityPanel(request_kind=lambda kind, force: self.requests.append((kind, force)))
        self.addCleanup(self.panel.deleteLater)

    def _load_all(self, item_id: int = 1) -> None:
        self.panel.set_item(item_id, item_name="Sample requirement", tracker_name="Offline Requirements")
        self.panel.set_active(True)
        for kind, data in SOURCES.items():
            self.panel.set_source(item_id, kind, data)

    def test_requests_checked_kinds_only_while_the_tab_is_visible(self) -> None:
        self.panel.kind_checks[COMMENT].setChecked(False)
        self.panel.set_item(1)

        self.assertEqual(self.requests, [])
        self.assertEqual(self.panel.status_label.text(), "#1 · 탭을 열면 변경 이력을 조회합니다.")

        self.panel.set_active(True)

        self.assertEqual(self.requests, [(FIELD, False), (ATTACHMENT, False)])
        self.assertEqual(self.panel.status_label.text(), "#1 · 전체 · 필드 변경·첨부 조회 중")

        self.panel.kind_checks[COMMENT].setChecked(True)

        self.assertEqual(self.requests[-1], (COMMENT, False))
        self.assertEqual(len(self.requests), 3)

    def test_loaded_sources_fill_status_summary_tree_and_enable_export(self) -> None:
        self._load_all()

        self.assertEqual(
            self.panel.status_label.text(),
            "#1 · 전체 · 버전 4건 · 필드 변경 3건 · 바뀐 필드 2개 · 필드 변경 정보 없는 버전 1건 · 댓글 1건 · 첨부 2건",
        )
        table = self.panel.summary_table
        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(
            [table.item(0, column).text() for column in range(5)],
            ["Risk Level", "-", "High", "2", "2026-07-21 09:30 · Sample User A"],
        )
        self.assertEqual(table.item(0, 0).toolTip(), "<qt>Risk Level</qt>")
        self.assertEqual(self.panel.history_view.topLevelItemCount(), 7)
        self.assertTrue(self.panel.export_button.isEnabled())
        self.assertFalse(self.panel.retry_button.isVisible())

    def test_late_response_for_the_previous_item_is_ignored(self) -> None:
        self.panel.set_item(1)
        self.panel.set_active(True)
        self.panel.set_item(2)

        self.panel.set_source(1, FIELD, HISTORY)

        self.assertEqual(self.panel.history_view.topLevelItemCount(), 0)
        self.assertEqual(self.panel.status_label.text(), "#2 · 전체 · 필드 변경·댓글·첨부 조회 중")
        self.assertEqual(self.requests.count((FIELD, False)), 2)

    def test_baseline_choice_refilters_without_new_requests(self) -> None:
        self.panel.set_baselines(BASELINES)
        self._load_all()
        request_count = len(self.requests)

        self.panel.select_scope(11)

        self.assertEqual(len(self.requests), request_count)
        self.assertEqual(
            self.panel.status_label.text(),
            "#1 · Sample Baseline 이후 · 버전 2건 · 필드 변경 2건 · 바뀐 필드 1개 · 댓글 1건 · 첨부 0건",
        )
        self.assertEqual(self.panel.baseline_combo.currentText(), "Sample Baseline (2026-07-19T08:00:00Z)")

    def test_baseline_without_created_at_cannot_be_chosen(self) -> None:
        self.panel.set_baselines(BASELINES)
        combo = self.panel.baseline_combo
        index = combo.findData(12)
        model_item = combo.model().item(index)

        self.assertFalse(model_item.isEnabled())
        self.assertEqual(model_item.toolTip(), "생성 시각이 없어 기준으로 쓸 수 없습니다")

        self.panel.select_scope(12)

        self.assertEqual(combo.currentData(), ALL_SCOPE_DATA)

    def test_failed_kind_is_reported_and_retry_asks_only_for_it(self) -> None:
        self.panel.set_item(1)
        self.panel.set_active(True)
        self.panel.set_source(1, FIELD, HISTORY)
        self.panel.set_source(1, ATTACHMENT, ATTACHMENTS)

        self.panel.set_source_error(1, COMMENT, "댓글을 볼 권한이 없습니다.")

        self.assertTrue(self.panel.status_label.text().endswith("댓글 조회 실패: 댓글을 볼 권한이 없습니다."))
        self.assertIn("첨부 2건", self.panel.status_label.text())
        self.assertFalse(self.panel.retry_button.isHidden())
        self.assertFalse(self.panel.export_button.isEnabled())

        self.panel.retry_button.click()

        self.assertEqual(self.requests[-1], (COMMENT, True))
        self.assertTrue(self.panel.retry_button.isHidden())

    def test_turning_field_changes_off_empties_the_summary(self) -> None:
        self._load_all()

        self.panel.kind_checks[FIELD].setChecked(False)

        self.assertEqual(self.panel.summary_table.rowCount(), 0)
        self.assertEqual(self.panel.summary_label.text(), "필드 변경 유형을 켜면 필드별 요약을 보입니다.")
        self.assertEqual(self.panel.status_label.text(), "#1 · 전체 · 댓글 1건 · 첨부 2건")

    def test_labels_show_server_values_as_plain_text(self) -> None:
        self.panel.set_item(1)
        self.panel.set_active(True)

        self.panel.set_source_error(1, COMMENT, "<b>권한 없음</b>")

        self.assertEqual(self.panel.status_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(self.panel.summary_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertTrue(self.panel.status_label.text().endswith("댓글 조회 실패: <b>권한 없음</b>"))

    def test_relation_kind_is_shown_but_disabled(self) -> None:
        self.assertFalse(self.panel.relation_check.isEnabled())
        self.assertFalse(self.panel.relation_check.isChecked())
        self.assertEqual(self.panel.relation_check.toolTip(), "서버 응답에 시각 정보가 없어 지원하지 않습니다")

    def test_between_points_panel_reports_missing_versions_and_undetermined_times(self) -> None:
        panel = ItemActivityPanel(request_kind=lambda *_args: None, between_points=True)
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.baseline_combo.itemText(0), "비교 시점 사이")

        panel.set_item(1, between_scope=ActivityScope("비교 시점 사이", versions=(2, 4), time_undetermined=True))
        panel.set_active(True)
        for kind, data in SOURCES.items():
            panel.set_source(1, kind, data)

        self.assertEqual(
            panel.status_label.text(),
            "#1 · 비교 시점 사이 · 버전 2건 · 필드 변경 2건 · 바뀐 필드 1개 · 댓글 0건 · 첨부 0건"
            " · Baseline 생성 시각이 없어 댓글·첨부 구간을 정할 수 없습니다",
        )

        panel.set_item(1, between_scope=None)

        self.assertEqual(panel.status_label.text(), "#1 · 두 시점의 버전 정보가 없어 사이 이력을 고를 수 없습니다.")
        self.assertFalse(panel.export_button.isEnabled())

    def test_export_button_emits_the_visible_range(self) -> None:
        marker = BaselineMarker("Baseline #11", version=2)
        self.panel.set_baselines(BASELINES)
        self.panel.set_item(1, item_name="Sample requirement", tracker_name="Offline Requirements", marker=marker)
        self.panel.set_active(True)
        for kind, data in SOURCES.items():
            self.panel.set_source(1, kind, data)
        self.panel.select_scope(11)
        self.panel.kind_checks[ATTACHMENT].setChecked(False)
        emitted = []
        self.panel.export_requested.connect(emitted.append)

        self.panel.export_button.click()

        (request,) = emitted
        self.assertEqual(
            (request.item_id, request.item_name, request.tracker_name),
            (1, "Sample requirement", "Offline Requirements"),
        )
        self.assertEqual(request.scope_label, "Sample Baseline 이후")
        self.assertEqual(request.kind_labels, ("필드 변경", "댓글"))
        self.assertEqual(
            [(entry.kind, entry.version) for entry in request.entries],
            [(FIELD, 4), (COMMENT, None), (FIELD, 3)],
        )
        self.assertEqual(request.summary.field_change_count, 2)
        self.assertIs(request.baseline, marker)


class RunActivityExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.panel = ItemActivityPanel(request_kind=lambda *_args: None)
        self.addCleanup(lambda: shiboken6.isValid(self.panel) and self.panel.deleteLater())
        self.panel.set_item(1, item_name="Sample requirement")
        self.panel.set_active(True)
        for kind, data in SOURCES.items():
            self.panel.set_source(1, kind, data)
        self.requests = []
        self.panel.export_requested.connect(self.requests.append)
        self.panel.export_button.click()
        self.records = []
        self.errors = []
        self.submitted = []

    def _run(self) -> None:
        def submit(key, operation, completed, failed):
            self.submitted.append(key)
            try:
                result = operation()
            except Exception as exc:
                failed(exc)
            else:
                completed(result)

        run_activity_export(
            self.panel,
            self.panel,
            self.requests[0],
            submit=submit,
            record_activity=self.records.append,
            show_error=lambda exc, prefix="": self.errors.append(prefix),
            source="tracker_workspace",
            project_id=246800,
            project_name="Offline Project",
            tracker_id=24680001,
            tracker_name="Offline Requirements",
        )

    def test_success_records_activity_and_reports_on_the_panel(self) -> None:
        summary = ItemActivityExportSummary(entry_count=7, row_count=8, long_value_count=0)
        with (
            patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("history.xlsx", "")),
            patch("src.gui.item_activity_panel.export_item_activity_xlsx", return_value=summary) as export_mock,
        ):
            self._run()

        export_mock.assert_called_once_with(self.requests[0], "history.xlsx")
        self.assertEqual(self.submitted, ["item_activity_export"])
        (record,) = self.records
        self.assertEqual(record.operation, ActivityOperation.ITEM_HISTORY_EXPORT)
        self.assertEqual(record.result, ActivityResult.SUCCESS)
        self.assertEqual(record.item_id, 1)
        self.assertEqual(record.details["entryCount"], 7)
        self.assertTrue(self.panel.status_label.text().endswith("Excel 내보내기 완료 · 항목 7건 · 행 8개"))
        self.assertTrue(self.panel.export_button.isEnabled())

    def test_failure_shows_error_and_restores_the_button(self) -> None:
        with (
            patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("history.xlsx", "")),
            patch(
                "src.gui.item_activity_panel.export_item_activity_xlsx",
                side_effect=ItemActivityExportError("Excel 파일을 저장하지 못했습니다."),
            ),
        ):
            self._run()

        self.assertEqual(self.errors, ["변경 이력 Excel 내보내기 실패"])
        self.assertEqual(self.records[0].result, ActivityResult.FAILED)
        self.assertTrue(self.panel.status_label.text().endswith("Excel 내보내기 실패"))
        self.assertTrue(self.panel.export_button.isEnabled())

    def _run_with_deferred_callbacks(self) -> tuple:
        captured = []

        def submit(key, operation, completed, failed):
            captured.append((completed, failed))

        run_activity_export(
            self.panel,
            self.panel,
            self.requests[0],
            submit=submit,
            record_activity=self.records.append,
            show_error=lambda exc, prefix="": self.errors.append(prefix),
            source="tracker_workspace",
            project_id=246800,
            project_name="Offline Project",
            tracker_id=24680001,
            tracker_name="Offline Requirements",
        )
        return captured[0]

    def test_success_is_recorded_even_if_the_panel_was_deleted_meanwhile(self) -> None:
        with (
            patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("history.xlsx", "")),
            patch("src.gui.item_activity_panel.export_item_activity_xlsx"),
        ):
            completed, _failed = self._run_with_deferred_callbacks()
        shiboken6.delete(self.panel)

        completed(ItemActivityExportSummary(entry_count=7, row_count=8, long_value_count=0))

        (record,) = self.records
        self.assertEqual(record.result, ActivityResult.SUCCESS)

    def test_failure_is_recorded_and_reported_even_if_the_panel_was_deleted_meanwhile(self) -> None:
        with (
            patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("history.xlsx", "")),
            patch("src.gui.item_activity_panel.export_item_activity_xlsx"),
        ):
            _completed, failed = self._run_with_deferred_callbacks()
        shiboken6.delete(self.panel)

        failed(ItemActivityExportError("Excel 파일을 저장하지 못했습니다."))

        (record,) = self.records
        self.assertEqual(record.result, ActivityResult.FAILED)
        self.assertEqual(self.errors, ["변경 이력 Excel 내보내기 실패"])

    def test_cancelled_file_dialog_does_nothing(self) -> None:
        with patch("src.gui.item_activity_panel.QFileDialog.getSaveFileName", return_value=("", "")):
            self._run()

        self.assertEqual((self.submitted, self.records), ([], []))


if __name__ == "__main__":
    unittest.main()
