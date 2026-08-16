from __future__ import annotations

import sys
import json
import os
import platform
from collections import deque
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from time import monotonic
from uuid import uuid4

from .calibration import render_channel_results, select_best_channel
from .cli import build_record, create_session_paths, utc_now, write_json_line
from .collection import (
    COLLECTION_LABELS,
    FALL_LABELS,
    TRANSITION_LABELS,
    UNLABELED,
    finalize_collection_label,
    render_korean_summary,
    summarize_collection,
)
from .features import (
    build_current_calibration_presence_rows,
    build_profile_feature_rows,
    extract_session_features,
)
from .fall_alert import (
    FallAlertError,
    build_collection_fall_event,
    build_detected_fall_event,
    send_fall_event,
)
from .live_detection import (
    DetectionEvent,
    EventJournal,
    FALL_HISTORY_EVENT_TYPES,
    LiveActionDetector,
    format_fall_history_record,
)
from .datasets import (
    DatasetError,
    attach_dataset_to_profile,
    detach_dataset_from_profile,
    export_profile_dataset,
    import_dataset_bundle,
    list_datasets,
)
from .presence import (
    PresenceDecision,
    PresenceDetector,
    PresenceState,
    build_static_presence_baseline,
)
from .profiles import (
    append_profile_session,
    archive_profile,
    create_profile,
    list_profiles,
    load_profile,
    load_or_create_profile,
    update_profile_calibration,
    update_profile_channel,
    update_profile_details,
    update_profile_rx_mac,
)
from .radar import (
    CalibrationSample,
    ChannelSample,
    DeviceMacSample,
    LinkSample,
    RadarSample,
    parse_channel_line,
    parse_calibration_line,
    parse_device_mac_line,
    parse_link_line,
    parse_radar_line,
)
from .prototype import predict_action
from .activity import ActivityFrame, AsyncFrameWindowEngine
from .activity_events import ActivityEventAggregator
from .csi import RAW_CSI_ENABLE_COMMAND, parse_csi_line

def run_monitor(
    port: str,
    baud: int,
    project_root: str = ".",
    *,
    activity_model: str | None = None,
    activity_hz: float = 5.0,
    activity_window_frames: int | None = None,
    activity_tail_seconds: float = 3.0,
    activity_fall_threshold: float = 0.80,
) -> int:
    import pyqtgraph as pg
    from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QGroupBox,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QInputDialog,
        QPushButton,
        QPlainTextEdit,
        QHBoxLayout,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )
    from serial import Serial

    class SerialReader(QThread):
        sample_received = pyqtSignal(object)
        link_received = pyqtSignal(object)
        channel_received = pyqtSignal(object)
        calibration_received = pyqtSignal(object)
        device_mac_received = pyqtSignal(object)
        raw_line_received = pyqtSignal(bytes)
        read_error = pyqtSignal(str)

        def __init__(self, *, enable_raw_csi: bool = False) -> None:
            super().__init__()
            self.commands: Queue[str] = Queue()
            self.enable_raw_csi = enable_raw_csi

        def send_command(self, command: str) -> None:
            self.commands.put(command)

        def run(self) -> None:
            try:
                with Serial(port, baud, timeout=0.2) as serial_port:
                    serial_port.write(b"rf_channel\r\n")
                    if self.enable_raw_csi:
                        serial_port.write(
                            f"{RAW_CSI_ENABLE_COMMAND}\r\n".encode("utf-8")
                        )
                    while not self.isInterruptionRequested():
                        try:
                            command = self.commands.get_nowait()
                        except Empty:
                            pass
                        else:
                            serial_port.write(f"{command}\r\n".encode("utf-8"))
                        line = serial_port.readline()
                        if line:
                            self.raw_line_received.emit(line)
                        sample = parse_radar_line(line)
                        if sample is not None:
                            self.sample_received.emit(sample)
                        link_sample = parse_link_line(line)
                        if link_sample is not None:
                            self.link_received.emit(link_sample)
                        channel_sample = parse_channel_line(line)
                        if channel_sample is not None:
                            self.channel_received.emit(channel_sample)
                        calibration_sample = parse_calibration_line(line)
                        if calibration_sample is not None:
                            self.calibration_received.emit(calibration_sample)
                        device_mac_sample = parse_device_mac_line(line)
                        if device_mac_sample is not None:
                            self.device_mac_received.emit(device_mac_sample)
            except Exception as exc:
                self.read_error.emit(str(exc))

    class FallAlertWorker(QThread):
        delivered = pyqtSignal(str)
        failed = pyqtSignal(str, str)

        def __init__(self, endpoint: str, event: dict[str, object]) -> None:
            super().__init__()
            self.endpoint = endpoint
            self.event = event

        def run(self) -> None:
            try:
                send_fall_event(self.endpoint, self.event)
            except (FallAlertError, ValueError) as exc:
                self.failed.emit(str(self.event["window_id"]), str(exc))
            else:
                self.delivered.emit(str(self.event["window_id"]))

    class RadarWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"ESP32 CSI Movement Monitor - {port}")
            self.resize(1050, 780)
            self.project_root = Path(project_root).resolve()
            self.active_profile = load_or_create_profile(self.project_root)
            self.presence_detector = PresenceDetector()
            self.refresh_presence_baseline()
            self.event_journal = EventJournal(self.project_root)
            self.live_detector = self.build_live_detector()

            self.jitter_values: deque[float] = deque(maxlen=100)
            self.threshold_values: deque[float] = deque(maxlen=100)
            self.sample_count = 0
            self.started_at = monotonic()
            self.last_sample_at = 0.0
            self.last_link_at = 0.0
            self.last_link_sample: LinkSample | None = None
            self.current_moving = False
            self.activity_engine = None
            self.activity_aggregator = None
            self.activity_model_error: str | None = None
            self.activity_window_frames = activity_window_frames or 950
            self.activity_model_device = ""
            self.csi_frame_count = 0
            self.last_csi_at = 0.0
            if activity_model:
                try:
                    if str(self.project_root) not in sys.path:
                        sys.path.insert(0, str(self.project_root))
                    from ml.runtime import TorchCnnActivityModel

                    backend = TorchCnnActivityModel(activity_model)
                    if (
                        activity_window_frames is not None
                        and activity_window_frames != backend.window_frames
                    ):
                        raise ValueError(
                            "실행 window와 checkpoint 입력 크기가 다릅니다: "
                            f"실행={activity_window_frames}, 모델={backend.window_frames}"
                        )
                    self.activity_window_frames = backend.window_frames
                    self.activity_model_device = str(backend.device)
                    self.activity_engine = AsyncFrameWindowEngine(
                        backend,
                        window_frames=backend.window_frames,
                        inference_hz=activity_hz,
                        tail_seconds=activity_tail_seconds,
                    )
                    self.activity_aggregator = ActivityEventAggregator(
                        fall_score_threshold=activity_fall_threshold,
                    )
                except Exception as exc:
                    self.activity_model_error = str(exc)
            self.calibrating = False
            self.calibration_stage = ""
            self.calibration_remaining = 0
            self.calibration_channel: int | None = None
            self.integrated_calibration = False
            self.integrated_channel_summary: list[str] = []
            self.current_channel: int | None = None
            self.scanning_channels = False
            self.scan_channels = [1, 6, 11]
            self.scan_index = 0
            self.scan_phase = ""
            self.scan_deadline = 0.0
            self.scan_link_samples: list[LinkSample] = []
            self.scan_radar_times: list[float] = []
            self.scan_results: dict[int, dict[str, float]] = {}
            self.scan_measure_started = 0.0
            self.collecting = False
            self.collection_phase = ""
            self.collection_remaining = 0
            self.collection_elapsed = 0
            self.collection_event_at: str | None = None
            self.collection_session_id = ""
            self.collection_label = ""
            self.collection_planned_label: str | None = None
            self.collection_output = None
            self.collection_manifest: dict[str, object] = {}
            self.collection_manifest_path: Path | None = None
            self.collection_raw_path: Path | None = None
            self.collection_sample_id = 0
            self.collection_radar_samples: list[RadarSample] = []
            self.collection_link_samples: list[LinkSample] = []
            self.collection_safety_confirmed: bool | None = None
            self.fall_alert_workers: list[FallAlertWorker] = []
            self.pending_fall_alerts: dict[str, dict[str, object]] = {}

            self.status = QLabel("WAITING FOR RADAR DATA")
            self.status.setAlignment(Qt.AlignCenter)
            self.status.setFont(QFont("Arial", 28, QFont.Bold))
            self.status.setStyleSheet(
                "background:#343a40;color:white;padding:18px;border-radius:8px;"
            )

            self.presence_status = QLabel("재실 상태: 판단 대기")
            self.presence_status.setAlignment(Qt.AlignCenter)
            self.presence_status.setFont(QFont("Arial", 15, QFont.Bold))
            self.presence_status.setStyleSheet(
                "background:#b54708;color:white;padding:12px;border-radius:6px;"
            )

            self.action_status = QLabel("자동 행동 감지: 보정 후 자동 시작")
            self.action_status.setAlignment(Qt.AlignCenter)
            self.action_status.setFont(QFont("Arial", 13, QFont.Bold))
            self.action_status.setStyleSheet(
                "background:#495057;color:white;padding:10px;border-radius:6px;"
            )

            self.fall_history = QPlainTextEdit()
            self.fall_history.setReadOnly(True)
            self.fall_history.setMaximumBlockCount(100)
            self.fall_history.setMaximumHeight(145)
            self.fall_history.setPlaceholderText("아직 기록된 낙상 후보가 없습니다.")
            fall_history_layout = QVBoxLayout()
            fall_history_layout.addWidget(self.fall_history)
            fall_history_group = QGroupBox("최근 낙상 후보·감지 기록 (최신순)")
            fall_history_group.setLayout(fall_history_layout)
            self.refresh_fall_history()

            if self.activity_model_error:
                activity_text = f"행동 분류: 모델 사용 불가 · {self.activity_model_error}"
            elif self.activity_engine is None:
                activity_text = "행동 분류: 모델 미설정 · Radar 감지만 사용"
            else:
                activity_text = (
                    "행동 분류: 원시 CSI 대기 · LLTF 자동 활성화 · "
                    f"{self.activity_model_device}"
                )
            self.activity_status = QLabel(activity_text)
            self.activity_status.setAlignment(Qt.AlignCenter)
            self.activity_status.setFont(QFont("Arial", 13, QFont.Bold))
            self.activity_status.setStyleSheet(
                "background:#495057;color:white;padding:10px;border-radius:6px;"
            )

            self.details = QLabel(f"Port: {port}  |  Baud: {baud:,}")
            self.details.setFont(QFont("Arial", 12))

            self.link_status = QLabel("Wi-Fi CSI link: waiting for telemetry")
            self.link_status.setFont(QFont("Arial", 12, QFont.Bold))
            self.link_status.setStyleSheet(
                "background:#495057;color:white;padding:10px;border-radius:6px;"
            )

            self.channel_status = QLabel("Wi-Fi channel: checking...")
            self.channel_status.setFont(QFont("Arial", 12, QFont.Bold))

            self.channel_scan_button = QPushButton(
                "채널 + 공간 통합 보정 (약 100초)"
            )
            self.channel_scan_button.setFont(QFont("Arial", 12, QFont.Bold))
            self.channel_scan_button.clicked.connect(self.start_channel_scan)

            self.profile_status = QLabel()
            self.profile_status.setFont(QFont("Arial", 11, QFont.Bold))
            self.profile_combo = QComboBox()
            self.refresh_profile_list(self.active_profile["profileId"])
            self.profile_combo.currentIndexChanged.connect(self.select_space_profile)
            self.profile_add_button = QPushButton("새 프로필 추가")
            self.profile_add_button.clicked.connect(self.add_space_profile)
            self.profile_edit_button = QPushButton("선택 프로필 수정")
            self.profile_edit_button.clicked.connect(self.edit_space_profile)
            self.profile_delete_button = QPushButton("선택 프로필 삭제")
            self.profile_delete_button.clicked.connect(self.delete_space_profile)
            self.profile_apply_button = QPushButton("공간 프로필 적용")
            self.profile_apply_button.setFont(QFont("Arial", 11, QFont.Bold))
            self.profile_apply_button.clicked.connect(self.apply_space_profile)

            profile_controls = QHBoxLayout()
            profile_controls.addWidget(self.profile_combo, 1)
            profile_controls.addWidget(self.profile_add_button)
            profile_controls.addWidget(self.profile_edit_button)
            profile_controls.addWidget(self.profile_delete_button)
            profile_controls.addWidget(self.profile_apply_button)
            profile_layout = QVBoxLayout()
            profile_layout.addLayout(profile_controls)
            profile_layout.addWidget(self.profile_status)
            profile_group = QGroupBox("공간 프로필")
            profile_group.setLayout(profile_layout)

            self.dataset_combo = QComboBox()
            self.dataset_combo.currentIndexChanged.connect(
                self.select_reference_dataset
            )
            self.dataset_export_button = QPushButton("현재 프로필 데이터 내보내기")
            self.dataset_export_button.clicked.connect(
                self.export_active_profile_dataset
            )
            self.dataset_import_button = QPushButton("데이터셋 번들 가져오기")
            self.dataset_import_button.clicked.connect(self.import_dataset_dialog)
            self.dataset_attach_button = QPushButton("선택 데이터 연결")
            self.dataset_attach_button.clicked.connect(
                self.toggle_reference_dataset
            )
            self.dataset_status = QLabel()
            self.dataset_status.setFont(QFont("Arial", 10))
            dataset_controls = QHBoxLayout()
            dataset_controls.addWidget(self.dataset_combo, 1)
            dataset_controls.addWidget(self.dataset_export_button)
            dataset_controls.addWidget(self.dataset_import_button)
            dataset_controls.addWidget(self.dataset_attach_button)
            dataset_layout = QVBoxLayout()
            dataset_layout.addLayout(dataset_controls)
            dataset_layout.addWidget(self.dataset_status)
            dataset_group = QGroupBox("참조 데이터셋")
            dataset_group.setLayout(dataset_layout)
            self.refresh_dataset_list()

            self.collection_label_combo = QComboBox()
            self.collection_label_combo.addItem("수집 후 실제 행동 선택", None)
            for collection_label in COLLECTION_LABELS:
                self.collection_label_combo.addItem(collection_label, collection_label)
            self.collection_label_combo.currentTextChanged.connect(
                self.update_collection_cue_default
            )

            self.collection_prep_spin = QSpinBox()
            self.collection_prep_spin.setRange(3, 60)
            self.collection_prep_spin.setValue(10)
            self.collection_prep_spin.setSuffix("초 준비")

            self.collection_duration_spin = QSpinBox()
            self.collection_duration_spin.setRange(10, 600)
            self.collection_duration_spin.setValue(60)
            self.collection_duration_spin.setSuffix("초 수집")
            self.collection_duration_spin.valueChanged.connect(
                self.update_collection_cue_limit
            )

            self.collection_cue_spin = QSpinBox()
            self.collection_cue_spin.setRange(1, 599)
            self.collection_cue_spin.setValue(30)
            self.collection_cue_spin.setSuffix("초에 신호")
            self.collection_cue_spin.setEnabled(False)
            self.collection_cue_checkbox = QCheckBox("중간 행동 신호")
            self.collection_cue_checkbox.toggled.connect(
                self.collection_cue_spin.setEnabled
            )
            self.collection_fall_safety_checkbox = QCheckBox("모의 낙상 안전 수집")

            self.fall_alert_endpoint = QLineEdit()
            self.fall_alert_endpoint.setText(
                os.environ.get("CARNATION_EVENT_API_URL", "")
            )
            self.fall_alert_endpoint.setPlaceholderText(
                "앱 서버 주소 (예: http://192.168.0.5:8080)"
            )
            self.fall_alert_test_button = QPushButton("앱 알림 테스트")
            self.fall_alert_test_button.setFont(QFont("Arial", 10, QFont.Bold))
            self.fall_alert_test_button.clicked.connect(self.send_manual_fall_alert_test)

            self.collection_start_button = QPushButton("행동 수집 시작")
            self.collection_start_button.setFont(QFont("Arial", 11, QFont.Bold))
            self.collection_start_button.clicked.connect(self.start_collection)
            self.collection_status = QLabel("수집 대기")

            collection_controls = QHBoxLayout()
            collection_controls.addWidget(self.collection_label_combo)
            collection_controls.addWidget(self.collection_prep_spin)
            collection_controls.addWidget(self.collection_duration_spin)
            collection_controls.addWidget(self.collection_cue_checkbox)
            collection_controls.addWidget(self.collection_cue_spin)
            collection_controls.addWidget(self.collection_fall_safety_checkbox)
            collection_controls.addWidget(self.collection_start_button)
            collection_layout = QVBoxLayout()
            collection_layout.addLayout(collection_controls)
            fall_alert_layout = QHBoxLayout()
            fall_alert_layout.addWidget(QLabel("낙상 알림 서버"))
            fall_alert_layout.addWidget(self.fall_alert_endpoint, 1)
            fall_alert_layout.addWidget(self.fall_alert_test_button)
            collection_layout.addLayout(fall_alert_layout)
            collection_layout.addWidget(self.collection_status)
            collection_group = QGroupBox("행동 데이터 수집")
            collection_group.setLayout(collection_layout)

            self.plot = pg.PlotWidget(title="Movement signal (jitter)")
            self.plot.setBackground("#101214")
            self.plot.showGrid(x=True, y=True, alpha=0.3)
            self.plot.addLegend()
            self.plot.setXRange(0, 100, padding=0)
            self.plot.setLimits(xMin=0, xMax=100)
            self.plot.setMouseEnabled(x=False, y=True)
            self.jitter_curve = self.plot.plot(
                pen=pg.mkPen("#20e070", width=2), name="jitter"
            )
            self.threshold_curve = self.plot.plot(
                pen=pg.mkPen("#ff40e0", width=2), name="move threshold"
            )

            layout = QVBoxLayout()
            layout.addWidget(self.status)
            layout.addWidget(self.presence_status)
            layout.addWidget(self.action_status)
            layout.addWidget(self.activity_status)
            layout.addWidget(fall_history_group)
            layout.addWidget(self.link_status)
            layout.addWidget(self.channel_status)
            layout.addWidget(self.details)
            button_layout = QHBoxLayout()
            button_layout.addWidget(self.channel_scan_button)
            layout.addLayout(button_layout)
            layout.addWidget(profile_group)
            layout.addWidget(dataset_group)
            layout.addWidget(collection_group)
            layout.addWidget(self.plot, 1)
            container = QWidget()
            container.setLayout(layout)
            self.setCentralWidget(container)

            self.reader = SerialReader(enable_raw_csi=self.activity_engine is not None)
            self.reader.sample_received.connect(self.update_sample)
            self.reader.link_received.connect(self.update_link)
            self.reader.channel_received.connect(self.update_channel)
            self.reader.calibration_received.connect(self.update_calibration_result)
            self.reader.device_mac_received.connect(self.update_device_mac)
            self.reader.raw_line_received.connect(self.record_raw_line)
            self.reader.raw_line_received.connect(self.process_activity_frame)
            self.reader.read_error.connect(self.show_error)
            self.reader.start()

            self.health_timer = QTimer(self)
            self.health_timer.timeout.connect(self.update_health)
            self.health_timer.start(500)

            self.activity_timer = QTimer(self)
            self.activity_timer.timeout.connect(self.poll_activity_prediction)
            self.activity_timer.start(20)

            self.calibration_timer = QTimer(self)
            self.calibration_timer.timeout.connect(self.calibration_tick)
            self.calibration_timer.setInterval(1000)

            self.channel_scan_timer = QTimer(self)
            self.channel_scan_timer.timeout.connect(self.channel_scan_tick)
            self.channel_scan_timer.setInterval(250)

            self.collection_timer = QTimer(self)
            self.collection_timer.timeout.connect(self.collection_tick)
            self.collection_timer.setInterval(1000)

        def refresh_profile_status(self) -> None:
            channel = self.active_profile["radio"]["channel"]
            if self.active_profile.get("needsCalibration", True):
                calibration = "보정값 없음"
            else:
                calibration = "보정값 저장됨"
            static_presence = (
                "정지 재실 기준 준비됨"
                if self.presence_detector.static_baseline is not None
                else "정지 재실 기준 미구성"
            )
            self.profile_status.setText(
                f"저장 채널 {channel}  |  {calibration}  |  "
                f"연결 데이터 {len(self.active_profile.get('sessionIds', []))}개  |  "
                f"참조 데이터셋 {len(self.active_profile.get('referenceDatasets', []))}개  |  "
                f"{static_presence}"
            )

        def refresh_presence_baseline(self) -> None:
            rows = build_current_calibration_presence_rows(
                self.project_root, self.active_profile["profileId"]
            )
            self.presence_detector.set_static_baseline(
                build_static_presence_baseline(rows)
            )
            if hasattr(self, "live_detector"):
                self.live_detector = self.build_live_detector()

        def build_live_detector(self) -> LiveActionDetector:
            # Radar 규칙은 ML과 독립적으로 계속 동작한다. model.pt가 활성화된
            # 경우 monitor가 Radar 낙상 후보를 ML 행동 사건과 결합한다.
            return LiveActionDetector()

        def refresh_profile_list(self, selected_profile_id: str) -> None:
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            selected_index = 0
            for index, profile in enumerate(list_profiles(self.project_root)):
                self.profile_combo.addItem(profile["displayName"], profile["profileId"])
                if profile["profileId"] == selected_profile_id:
                    selected_index = index
            self.profile_combo.setCurrentIndex(selected_index)
            self.profile_combo.blockSignals(False)
            self.refresh_profile_status()
            if hasattr(self, "dataset_combo"):
                self.refresh_dataset_status()

        def select_space_profile(self, index: int) -> None:
            if index < 0:
                return
            profile_id = self.profile_combo.itemData(index)
            if not profile_id:
                return
            self.active_profile = load_profile(self.project_root, profile_id)
            self.refresh_presence_baseline()
            self.show_presence(self.presence_detector.reset("profile_changed"))
            self.refresh_profile_status()
            if hasattr(self, "dataset_combo"):
                self.refresh_dataset_status()

        def refresh_dataset_list(self, selected_dataset_id: str | None = None) -> None:
            datasets = list_datasets(self.project_root)
            self.dataset_combo.blockSignals(True)
            self.dataset_combo.clear()
            selected_index = 0
            if not datasets:
                self.dataset_combo.addItem("가져온 데이터셋 없음", None)
            else:
                for index, dataset in enumerate(datasets):
                    dataset_id = str(dataset["datasetId"])
                    self.dataset_combo.addItem(str(dataset["displayName"]), dataset_id)
                    if dataset_id == selected_dataset_id:
                        selected_index = index
                self.dataset_combo.setCurrentIndex(selected_index)
            self.dataset_combo.blockSignals(False)
            self.refresh_dataset_status()

        def selected_dataset_id(self) -> str | None:
            value = self.dataset_combo.currentData()
            return str(value) if value else None

        def select_reference_dataset(self, index: int) -> None:
            if index >= 0:
                self.refresh_dataset_status()

        def refresh_dataset_status(self) -> None:
            dataset_id = self.selected_dataset_id()
            if dataset_id is None:
                self.dataset_status.setText(
                    "팀 ESP-Radar 데이터셋 번들을 가져오면 공간 프로필에 참조로 연결할 수 있습니다."
                )
                self.dataset_attach_button.setText("선택 데이터 연결")
                self.dataset_attach_button.setEnabled(False)
                return
            dataset = next(
                item
                for item in list_datasets(self.project_root)
                if item["datasetId"] == dataset_id
            )
            attached = any(
                item.get("datasetId") == dataset_id
                for item in self.active_profile.get("referenceDatasets", [])
            )
            labels = ", ".join(str(label) for label in dataset.get("labels", []))
            self.dataset_status.setText(
                f"세션 {len(dataset.get('sessions', []))}개  |  "
                f"라벨 {labels or '없음'}  |  "
                f"현재 프로필 {'연결됨' if attached else '연결 안 됨'}"
            )
            self.dataset_attach_button.setText(
                "선택 데이터 연결 해제" if attached else "선택 데이터 연결"
            )
            self.dataset_attach_button.setEnabled(
                not (self.calibrating or self.scanning_channels or self.collecting)
            )

        def export_active_profile_dataset(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            default_path = (
                self.project_root
                / "data"
                / "exports"
                / f"{self.active_profile['profileId']}.csi-dataset.zip"
            )
            selected_path, _ = QFileDialog.getSaveFileName(
                self,
                "현재 프로필 데이터셋 내보내기",
                str(default_path),
                "CSI 데이터셋 (*.csi-dataset.zip *.zip)",
            )
            if not selected_path:
                return
            output_path = Path(selected_path)
            if output_path.suffix.lower() != ".zip":
                output_path = output_path.with_name(
                    output_path.name + ".csi-dataset.zip"
                )
            try:
                export_profile_dataset(
                    self.project_root,
                    self.active_profile["profileId"],
                    output_path,
                )
            except (DatasetError, OSError) as exc:
                QMessageBox.warning(self, "데이터셋 내보내기 실패", str(exc))
                return
            QMessageBox.information(
                self,
                "데이터셋 내보내기 완료",
                f"유효한 행동 세션을 공유 번들로 저장했습니다.\n{output_path}",
            )

        def import_dataset_dialog(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            selected_path, _ = QFileDialog.getOpenFileName(
                self,
                "CSI 데이터셋 번들 가져오기",
                str(self.project_root),
                "CSI 데이터셋 (*.csi-dataset.zip *.zip)",
            )
            if not selected_path:
                return
            try:
                dataset = import_dataset_bundle(
                    self.project_root, Path(selected_path)
                )
            except (DatasetError, OSError) as exc:
                QMessageBox.warning(self, "데이터셋 가져오기 실패", str(exc))
                return
            dataset_id = str(dataset["datasetId"])
            self.refresh_dataset_list(dataset_id)
            QMessageBox.information(
                self,
                "데이터셋 가져오기 완료",
                f"{dataset['displayName']}\n"
                f"세션 {len(dataset.get('sessions', []))}개를 확인했습니다.\n"
                "필요하면 '선택 데이터 연결'을 눌러 현재 공간의 참고 데이터로 사용하세요.",
            )

        def toggle_reference_dataset(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            dataset_id = self.selected_dataset_id()
            if dataset_id is None:
                return
            attached = any(
                item.get("datasetId") == dataset_id
                for item in self.active_profile.get("referenceDatasets", [])
            )
            if attached:
                detach_dataset_from_profile(
                    self.project_root, self.active_profile, dataset_id
                )
            else:
                attach_dataset_to_profile(
                    self.project_root, self.active_profile, dataset_id
                )
            self.refresh_profile_status()
            self.refresh_dataset_status()

        def add_space_profile(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            display_name, accepted = QInputDialog.getText(
                self,
                "새 공간 프로필",
                "공간 이름을 입력하세요. 예: 부모님 집 거실",
            )
            display_name = display_name.strip()
            if not accepted or not display_name:
                return
            description, accepted = QInputDialog.getText(
                self,
                "배치 설명",
                "TX와 RX의 배치를 입력하세요. 예: 방 양쪽 끝 대각선",
            )
            description = description.strip()
            if not accepted or not description:
                return
            distance, accepted = QInputDialog.getDouble(
                self,
                "TX-RX 거리",
                "두 보드의 직선거리(m)를 입력하세요.",
                1.0,
                0.1,
                100.0,
                1,
            )
            if not accepted:
                return
            channel = self.current_channel or int(
                self.active_profile["radio"]["channel"]
            )
            self.active_profile = create_profile(
                self.project_root,
                display_name=display_name,
                placement_description=description,
                distance_meters=distance,
                channel=channel,
            )
            self.refresh_presence_baseline()
            self.show_presence(self.presence_detector.reset("calibration_required"))
            self.refresh_profile_list(self.active_profile["profileId"])
            QMessageBox.information(
                self,
                "프로필 추가 완료",
                f"{display_name} 프로필을 만들었습니다.\n"
                "보드를 최종 위치에 놓고 빈 공간 보정을 실행해 주세요.",
            )

        def delete_space_profile(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            profiles = list_profiles(self.project_root)
            if len(profiles) <= 1:
                QMessageBox.warning(
                    self,
                    "프로필 삭제 불가",
                    "마지막 남은 공간 프로필은 삭제할 수 없습니다.",
                )
                return

            name = self.active_profile["displayName"]
            session_count = len(self.active_profile.get("sessionIds", []))
            reply = QMessageBox.question(
                self,
                "공간 프로필 삭제",
                f"{name} 프로필을 목록에서 삭제할까요?\n"
                f"연결 데이터: {session_count}개\n\n"
                "원본 행동 데이터는 삭제하지 않으며 프로필 파일은 복구용 폴더에 보관됩니다.",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if reply != QMessageBox.Yes:
                return

            archived_path = archive_profile(
                self.project_root, self.active_profile["profileId"]
            )
            remaining_profiles = list_profiles(self.project_root)
            self.active_profile = remaining_profiles[0]
            self.refresh_presence_baseline()
            self.show_presence(self.presence_detector.reset("profile_changed"))
            self.refresh_profile_list(self.active_profile["profileId"])
            QMessageBox.information(
                self,
                "프로필 삭제 완료",
                f"{name} 프로필을 목록에서 제거했습니다.\n"
                f"원본 데이터는 유지되며 프로필은 다음 위치에 보관했습니다.\n{archived_path}",
            )

        def edit_space_profile(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return

            placement = self.active_profile["placement"]
            display_name, accepted = QInputDialog.getText(
                self,
                "공간 프로필 수정",
                "공간 이름",
                QLineEdit.Normal,
                str(self.active_profile["displayName"]),
            )
            display_name = display_name.strip()
            if not accepted or not display_name:
                return
            description, accepted = QInputDialog.getText(
                self,
                "공간 프로필 수정",
                "배치 설명",
                QLineEdit.Normal,
                str(placement.get("description", "")),
            )
            description = description.strip()
            if not accepted or not description:
                return
            current_distance = placement.get("txRxDistanceMeters")
            distance, accepted = QInputDialog.getDouble(
                self,
                "공간 프로필 수정",
                "TX-RX 직선거리(m)",
                float(current_distance) if current_distance is not None else 1.0,
                0.1,
                100.0,
                1,
            )
            if not accepted:
                return
            tx_position, accepted = QInputDialog.getText(
                self,
                "공간 프로필 수정",
                "TX 위치와 높이",
                QLineEdit.Normal,
                str(placement.get("txPosition", "")),
            )
            tx_position = tx_position.strip()
            if not accepted or not tx_position:
                return
            rx_position, accepted = QInputDialog.getText(
                self,
                "공간 프로필 수정",
                "RX 위치와 높이",
                QLineEdit.Normal,
                str(placement.get("rxPosition", "")),
            )
            rx_position = rx_position.strip()
            if not accepted or not rx_position:
                return

            placement_changed = any(
                (
                    placement.get("description", "") != description,
                    placement.get("txRxDistanceMeters") != distance,
                    placement.get("txPosition", "") != tx_position,
                    placement.get("rxPosition", "") != rx_position,
                )
            )
            if placement_changed and not self.active_profile.get(
                "needsCalibration", True
            ):
                reply = QMessageBox.question(
                    self,
                    "배치 변경 확인",
                    "거리나 위치를 바꾸면 기존 빈 공간 보정값을 사용할 수 없습니다.\n"
                    "수정 내용을 저장하고 보정 필요 상태로 바꿀까요?",
                    QMessageBox.Yes | QMessageBox.Cancel,
                    QMessageBox.Cancel,
                )
                if reply != QMessageBox.Yes:
                    return

            update_profile_details(
                self.project_root,
                self.active_profile,
                display_name=display_name,
                placement_description=description,
                distance_meters=distance,
                tx_position=tx_position,
                rx_position=rx_position,
            )
            self.refresh_presence_baseline()
            if placement_changed:
                self.show_presence(
                    self.presence_detector.reset("calibration_required")
                )
            self.refresh_profile_list(self.active_profile["profileId"])
            message = "프로필 정보를 저장했습니다."
            if placement_changed:
                message += "\n최종 배치에서 빈 공간 보정을 다시 실행해 주세요."
            QMessageBox.information(self, "프로필 수정 완료", message)

        def apply_space_profile(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            placement = self.active_profile["placement"]
            reply = QMessageBox.question(
                self,
                "공간 프로필 적용",
                f"프로필: {self.active_profile['displayName']}\n"
                f"배치: {placement['description']}\n"
                f"거리: 약 {placement['txRxDistanceMeters']}m\n"
                f"TX: {placement.get('txPosition', '')}\n"
                f"RX: {placement.get('rxPosition', '')}\n\n"
                "TX와 RX를 기록 당시 위치·높이·방향으로 놓았습니까?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

            channel = int(self.active_profile["radio"]["channel"])
            self.show_presence(self.presence_detector.reset("profile_applied"))
            self.reader.send_command(f"rf_channel --set {channel}")
            calibration = self.active_profile.get("calibration")
            if calibration is None:
                QMessageBox.information(
                    self,
                    "채널 적용 완료",
                    f"채널 {channel}을 적용했습니다.\n"
                    "저장된 보정값이 없으므로 빈 공간 보정을 한 번 실행해 주세요.",
                )
                return

            command = (
                "radar "
                f"--predict_someone_threshold {calibration['someoneThreshold']} "
                f"--predict_move_threshold {calibration['moveThreshold']} "
                f"--predict_someone_sensitivity {calibration['someoneSensitivity']} "
                f"--predict_move_sensitivity {calibration['moveSensitivity']} "
                f"--predict_buff_size {calibration['bufferSize']} "
                f"--predict_outliers_number {calibration['outliersNumber']}"
            )
            QTimer.singleShot(1500, lambda: self.reader.send_command(command))
            QMessageBox.information(
                self,
                "공간 프로필 적용",
                f"채널 {channel}과 저장된 빈 공간 보정값을 적용했습니다.\n"
                "30초 정지 후 STATIC, 움직인 뒤 MOVEMENT DETECTED인지 확인해 주세요.",
            )

        def update_collection_cue_default(self, label: str) -> None:
            self.collection_cue_checkbox.setChecked(label in TRANSITION_LABELS)
            self.collection_fall_safety_checkbox.setChecked(label in FALL_LABELS)

        def update_collection_cue_limit(self, duration: int) -> None:
            self.collection_cue_spin.setMaximum(max(1, duration - 1))
            if self.collection_cue_spin.value() >= duration:
                self.collection_cue_spin.setValue(max(1, duration // 2))

        def set_collection_controls_enabled(self, enabled: bool) -> None:
            self.collection_label_combo.setEnabled(enabled)
            self.collection_prep_spin.setEnabled(enabled)
            self.collection_duration_spin.setEnabled(enabled)
            self.collection_cue_checkbox.setEnabled(enabled)
            self.collection_fall_safety_checkbox.setEnabled(enabled)
            self.collection_cue_spin.setEnabled(
                enabled and self.collection_cue_checkbox.isChecked()
            )
            self.collection_start_button.setEnabled(enabled)
            self.fall_alert_endpoint.setEnabled(enabled)
            self.fall_alert_test_button.setEnabled(enabled)
            self.channel_scan_button.setEnabled(enabled)
            self.profile_combo.setEnabled(enabled)
            self.profile_add_button.setEnabled(enabled)
            self.profile_edit_button.setEnabled(enabled)
            self.profile_delete_button.setEnabled(enabled)
            self.profile_apply_button.setEnabled(enabled)
            self.dataset_combo.setEnabled(enabled)
            self.dataset_export_button.setEnabled(enabled)
            self.dataset_import_button.setEnabled(enabled)
            self.dataset_attach_button.setEnabled(
                enabled and self.selected_dataset_id() is not None
            )

        def start_collection(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return

            planned_label = self.collection_label_combo.currentData()
            display_label = planned_label or "수집 후 실제 행동 선택"
            duration = self.collection_duration_spin.value()
            cue_enabled = self.collection_cue_checkbox.isChecked()
            cue_offset = self.collection_cue_spin.value()
            self.collection_safety_confirmed = None
            if self.collection_fall_safety_checkbox.isChecked():
                safety_reply = QMessageBox.question(
                    self,
                    "모의 낙상 안전 확인",
                    "실제 바닥으로 넘어지면 안 됩니다.\n\n"
                    "충격을 충분히 흡수하는 매트리스와 옆에서 도와줄 성인이 "
                    "준비되어 있고, 통제된 천천히 넘어지는 동작만 수행합니까?",
                    QMessageBox.Yes | QMessageBox.Cancel,
                    QMessageBox.Cancel,
                )
                if safety_reply != QMessageBox.Yes:
                    return
                self.collection_safety_confirmed = True
            if cue_enabled and cue_offset >= duration:
                QMessageBox.warning(
                    self,
                    "수집 설정 오류",
                    "행동 신호 시점은 전체 수집 시간보다 짧아야 합니다.",
                )
                return

            reply = QMessageBox.question(
                self,
                "행동 데이터 수집",
                f"예정 행동: {display_label}\n준비: {self.collection_prep_spin.value()}초\n"
                f"수집: {duration}초\n\n수집을 시작할까요?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

            self.collecting = True
            self.collection_phase = "preparing"
            self.collection_remaining = self.collection_prep_spin.value()
            self.collection_duration = duration
            self.collection_cue_enabled = cue_enabled
            self.collection_cue_offset = cue_offset
            self.collection_event_at = None
            self.collection_planned_label = planned_label
            self.collection_label = UNLABELED
            self.collection_session_id = (
                datetime.now().strftime("%Y%m%d-%H%M%S") + "-collection"
            )
            self.collection_status.setText(
                f"준비 중: {self.collection_remaining}초 남음"
            )
            self.status.setText(f"COLLECTION PREP - {self.collection_remaining}s")
            self.status.setStyleSheet(
                "background:#b54708;color:white;padding:18px;border-radius:8px;"
            )
            self.set_collection_controls_enabled(False)
            self.collection_timer.start()

        def begin_collection(self) -> None:
            raw_path, manifest_path = create_session_paths(
                self.project_root, self.collection_session_id
            )
            self.collection_raw_path = raw_path
            self.collection_manifest_path = manifest_path
            self.collection_output = raw_path.open("w", encoding="utf-8", newline="\n")
            self.collection_sample_id = 0
            self.collection_elapsed = 0
            self.collection_remaining = self.collection_duration
            self.collection_radar_samples.clear()
            self.collection_link_samples.clear()
            started_at = utc_now()
            self.collection_manifest = {
                "schemaVersion": "1.0.0",
                "sessionId": self.collection_session_id,
                "startedAtUtc": started_at,
                "finishedAtUtc": None,
                "deviceId": "rx-s3-001",
                "profileId": self.active_profile["profileId"],
                "roomId": self.active_profile["roomId"],
                "plannedLabel": self.collection_planned_label,
                "label": UNLABELED,
                "labelConfirmedAtEnd": False,
                "labelCorrected": False,
                "serialPort": port,
                "baudRate": baud,
                "platform": platform.platform(),
                "pythonVersion": platform.python_version(),
                "sampleCount": 0,
                "durationSeconds": self.collection_duration,
                "prepSeconds": self.collection_prep_spin.value(),
                "actionCueEnabled": self.collection_cue_enabled,
                "actionCueOffsetSeconds": (
                    self.collection_cue_offset if self.collection_cue_enabled else None
                ),
                "eventAtUtc": None,
                "safetyProtocolConfirmed": self.collection_safety_confirmed,
                "channel": self.current_channel,
                "valid": None,
                "rawFile": raw_path.relative_to(self.project_root).as_posix(),
            }
            manifest_path.write_text(
                json.dumps(self.collection_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.collection_phase = "recording"
            QApplication.beep()
            self.collection_status.setText(
                f"수집 중: 실제 행동은 종료 후 선택 | {self.collection_remaining}초 남음"
            )
            self.status.setText("COLLECTING - LABEL AFTER FINISH")
            self.status.setStyleSheet(
                "background:#175cd3;color:white;padding:18px;border-radius:8px;"
            )

        def collection_tick(self) -> None:
            if self.collection_phase == "preparing":
                self.collection_remaining -= 1
                if self.collection_remaining <= 0:
                    self.begin_collection()
                else:
                    self.collection_status.setText(
                        f"준비 중: {self.collection_remaining}초 남음"
                    )
                return

            if self.collection_phase != "recording":
                return

            self.collection_elapsed += 1
            self.collection_remaining -= 1
            if (
                self.collection_cue_enabled
                and self.collection_event_at is None
                and self.collection_elapsed >= self.collection_cue_offset
            ):
                self.mark_action_cue()
            else:
                self.collection_status.setText(
                    "수집 중: 실제 행동은 종료 후 선택 | "
                    f"{max(0, self.collection_remaining)}초 남음"
                )

            if self.collection_remaining <= 0:
                self.finish_collection()

        def mark_action_cue(self) -> None:
            self.collection_event_at = utc_now()
            self.collection_manifest["eventAtUtc"] = self.collection_event_at
            QApplication.beep()
            QTimer.singleShot(200, lambda: QApplication.beep())
            self.collection_status.setText(
                "행동 시작 신호 | 실제 행동은 종료 후 선택 | "
                f"{self.collection_remaining}초 남음"
            )
            self.status.setText("ACTION CUE - MOVE NOW")
            self.status.setStyleSheet(
                "background:#087f3d;color:white;padding:18px;border-radius:8px;"
            )

        def record_raw_line(self, raw_line: bytes) -> None:
            if self.collection_phase != "recording" or self.collection_output is None:
                return
            self.collection_sample_id += 1
            write_json_line(
                self.collection_output,
                build_record(
                    session_id=self.collection_session_id,
                    sample_id=self.collection_sample_id,
                    device_id="rx-s3-001",
                    raw_line=raw_line,
                    label=self.collection_label,
                ),
            )

        def process_activity_frame(self, raw_line: bytes) -> None:
            if self.activity_engine is None:
                return
            sample = parse_csi_line(raw_line)
            if sample is None:
                return
            self.csi_frame_count += 1
            self.last_csi_at = monotonic()
            suspended = self.scanning_channels or self.calibrating or self.collecting
            if suspended:
                self.activity_engine.deactivate(clear_frames=True)
                if self.activity_aggregator is not None:
                    self.activity_aggregator.reset()
                return
            self.activity_engine.submit(
                ActivityFrame(sample.sequence, sample.timestamp, sample.amplitude),
                moving=self.current_moving and not suspended,
            )

        def poll_activity_prediction(self) -> None:
            if self.activity_engine is None:
                return
            if self.scanning_channels or self.calibrating or self.collecting:
                try:
                    self.activity_engine.poll()
                except Exception:
                    pass
                return
            now = monotonic()
            try:
                prediction = self.activity_engine.poll()
            except Exception as exc:
                self.activity_status.setText(f"행동 분류 오류: {exc}")
                self.activity_status.setStyleSheet(
                    "background:#b42318;color:white;padding:10px;border-radius:6px;"
                )
                return
            if prediction is None:
                if self.activity_aggregator is not None:
                    for event in self.activity_aggregator.expire(now):
                        self.handle_live_detection(event)
                if self.csi_frame_count == 0:
                    self.activity_status.setText(
                        "행동 분류: 원시 CSI 대기 · LLTF 자동 활성화 명령 전송됨"
                    )
                    self.activity_status.setStyleSheet(
                        "background:#495057;color:white;padding:10px;border-radius:6px;"
                    )
                elif now - self.last_csi_at > 2.0:
                    self.activity_status.setText(
                        "행동 분류: 원시 CSI 수신 중단 · RX 연결과 펌웨어 확인 필요"
                    )
                    self.activity_status.setStyleSheet(
                        "background:#b42318;color:white;padding:10px;border-radius:6px;"
                    )
                elif not self.activity_engine.window.ready:
                    remaining = self.activity_engine.window.window_frames - self.activity_engine.window.buffered_frames
                    self.activity_status.setText(f"행동 분류: 최근 프레임 준비 중 · {remaining}개 남음")
                    self.activity_status.setStyleSheet(
                        "background:#495057;color:white;padding:10px;border-radius:6px;"
                    )
                else:
                    self.activity_status.setText(
                        "행동 분류: 모델 준비됨 · Radar 움직임 대기"
                    )
                    self.activity_status.setStyleSheet(
                        "background:#087f3d;color:white;padding:10px;border-radius:6px;"
                    )
                return
            scores = " · ".join(f"{name} {value * 100:.0f}%" for name,value in prediction.scores.items())
            self.activity_status.setText(f"행동 분류: {prediction.label} · {scores}")
            color = "#b42318" if prediction.label == "fall_suspected" else "#175cd3"
            self.activity_status.setStyleSheet(f"background:{color};color:white;padding:10px;border-radius:6px;")
            if self.activity_aggregator is not None:
                for event in self.activity_aggregator.observe(
                    prediction,
                    observed_at=now,
                    detected_at=utc_now(),
                ):
                    self.handle_live_detection(event)

        def finish_collection(
            self,
            *,
            valid: bool | None = None,
            invalid_reason: str | None = None,
            show_dialog: bool = True,
        ) -> None:
            self.collection_timer.stop()
            self.collection_phase = "finishing"
            if self.collection_output is not None:
                self.collection_output.close()
                self.collection_output = None

            if valid is None:
                QApplication.beep()
                QTimer.singleShot(180, lambda: QApplication.beep())
                QTimer.singleShot(360, lambda: QApplication.beep())
                default_index = 0
                if self.collection_planned_label in COLLECTION_LABELS:
                    default_index = COLLECTION_LABELS.index(
                        self.collection_planned_label
                    )
                actual_label, label_confirmed = QInputDialog.getItem(
                    self,
                    "실제 행동 확인",
                    "방금 실제로 수행한 행동을 선택하세요.",
                    COLLECTION_LABELS,
                    default_index,
                    False,
                )
                decision = finalize_collection_label(
                    planned_label=self.collection_planned_label,
                    actual_label=actual_label if label_confirmed else None,
                    safety_confirmed=self.collection_safety_confirmed is True,
                )
                self.collection_label = decision.label
                self.collection_manifest.update(
                    {
                        "label": decision.label,
                        "labelConfirmedAtEnd": decision.confirmed,
                        "labelCorrected": decision.corrected,
                    }
                )
                if decision.invalid_reason is not None:
                    valid = False
                    invalid_reason = decision.invalid_reason
                    if show_dialog:
                        QMessageBox.warning(
                            self,
                            "수집 데이터 제외",
                            f"{decision.invalid_reason}\n\n"
                            "원본은 보존하지만 학습·내보내기에서는 제외합니다.",
                        )
                else:
                    reply = QMessageBox.question(
                        self,
                        "수집 유효성 확인",
                        "이번 회차를 유효한 데이터로 저장할까요?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    valid = reply == QMessageBox.Yes
                    if not valid:
                        invalid_reason = "사용자가 수집 후 무효로 표시"

            summary = summarize_collection(
                self.collection_radar_samples, self.collection_link_samples
            )
            self.collection_manifest.update(
                {
                    "finishedAtUtc": utc_now(),
                    "sampleCount": self.collection_sample_id,
                    "eventAtUtc": self.collection_event_at,
                    "valid": valid,
                    "invalidReason": invalid_reason,
                    "summary": {
                        "radarSamples": summary.radar_count,
                        "movingSamples": summary.moving_count,
                        "movingRatio": summary.moving_ratio,
                        "averageJitter": summary.average_jitter,
                        "maximumJitter": summary.maximum_jitter,
                        "averageRssi": summary.average_rssi,
                        "averagePacketHz": summary.average_hz,
                        "minimumPacketHz": summary.minimum_hz,
                    },
                }
            )
            assert self.collection_manifest_path is not None
            assert self.collection_raw_path is not None
            self.collection_manifest_path.write_text(
                json.dumps(self.collection_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            prediction_message = "참고 행동 예측을 수행하지 않았습니다."
            if valid:
                reference_rows = [
                    row
                    for row in build_profile_feature_rows(
                        self.project_root, self.active_profile["profileId"]
                    )
                    if not (
                        row.get("dataset_id") == "native"
                        and row["session_id"] == self.collection_session_id
                    )
                ]
                known_labels = {str(row["label"]) for row in reference_rows}
                if self.collection_label not in known_labels:
                    prediction_message = (
                        f"{self.collection_label} 기준 데이터가 없어 아직 예측할 수 없습니다."
                    )
                else:
                    current_features = extract_session_features(self.collection_raw_path)
                    prediction = predict_action(current_features, reference_rows)
                    if prediction is not None:
                        self.collection_manifest["prototypePrediction"] = {
                            "label": prediction.label,
                            "separationPercent": prediction.separation_percent,
                            "distance": prediction.distance,
                            "comparedLabels": prediction.compared_labels,
                            "experimental": True,
                        }
                        prediction_message = (
                            f"참고 예측: {prediction.label}\n"
                            f"가까운 두 행동 간 분리도: {prediction.separation_percent:.1f}%"
                        )
                        self.collection_manifest_path.write_text(
                            json.dumps(
                                self.collection_manifest, ensure_ascii=False, indent=2
                            ),
                            encoding="utf-8",
                        )
            processed_dir = self.project_root / "data" / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            summary_path = processed_dir / f"{self.collection_session_id}.md"
            summary_text = render_korean_summary(
                session_id=self.collection_session_id,
                label=self.collection_label,
                duration_seconds=self.collection_duration,
                valid=valid,
                event_at_utc=self.collection_event_at,
                channel=self.current_channel,
                summary=summary,
                raw_file=self.collection_raw_path.relative_to(
                    self.project_root
                ).as_posix(),
                manifest_file=self.collection_manifest_path.relative_to(
                    self.project_root
                ).as_posix(),
            )
            summary_text += (
                "\n## 실험용 행동 예측\n\n"
                f"{prediction_message}\n\n"
                "이 값은 행동당 기준 세션이 1개인 유사도 시험이며 모델 정확도가 아니다.\n"
            )
            summary_path.write_text(summary_text, encoding="utf-8")
            append_profile_session(
                self.project_root, self.active_profile, self.collection_session_id
            )
            self.refresh_presence_baseline()
            self.show_presence(self.presence_detector.reset("warming_up"))
            self.refresh_profile_status()

            self.collecting = False
            self.collection_phase = ""
            self.set_collection_controls_enabled(True)
            self.collection_status.setText(
                f"수집 완료: {self.collection_label} | "
                f"Radar {summary.radar_count}개 | 움직임 {summary.moving_count}개"
            )
            self.status.setText("COLLECTION COMPLETE")
            self.status.setStyleSheet(
                "background:#087f3d;color:white;padding:18px;border-radius:8px;"
            )
            if show_dialog:
                QMessageBox.information(
                    self,
                    "수집 완료",
                    f"원본과 한글 요약을 저장했습니다.\n\n"
                    f"{prediction_message}\n\n{summary_path}",
                )
            if valid and self.collection_label in FALL_LABELS:
                self.dispatch_collection_fall_alert()

        def dispatch_collection_fall_alert(self) -> None:
            endpoint = self.fall_alert_endpoint.text().strip()
            if not endpoint:
                self.collection_status.setText(
                    "모의 낙상 수집 완료 | 앱 서버 주소가 없어 알림 미전송"
                )
                QMessageBox.warning(
                    self,
                    "낙상 의심 알림 미전송",
                    "유효한 모의 낙상 수집을 확인했지만 앱 서버 주소가 비어 있습니다.\n"
                    "'낙상 알림 서버'에 문서에서 받은 주소를 입력한 뒤 다시 수집하세요.",
                )
                return

            detected_at = (
                self.collection_event_at
                or str(self.collection_manifest["finishedAtUtc"])
            )
            event = build_collection_fall_event(
                session_id=self.collection_session_id,
                detected_at=detected_at,
                room_id=str(self.active_profile["roomId"]),
            )
            self.start_fall_alert_delivery(endpoint, event, "모의 낙상 수집 완료")

        def handle_live_detection(self, event: DetectionEvent) -> None:
            record = {
                "schema_version": "1.0",
                **event.to_record(),
                "profile_id": self.active_profile["profileId"],
                "room_id": self.active_profile["roomId"],
                "device_id": "rx-s3-001",
                "channel": self.current_channel,
            }
            event_path = self.event_journal.append(record)
            if event.event_type in FALL_HISTORY_EVENT_TYPES:
                self.refresh_fall_history()
            labels = {
                "moving": "움직임",
                "static": "정지",
                "fall_like": "낙상 의심",
            }
            label = labels.get(event.label, event.label)
            self.action_status.setText(
                f"자동 행동 감지: {label} | 신뢰 지표 {event.confidence * 100:.0f}% | "
                f"기록 {event_path.name}"
            )
            if event.event_type != "fall_suspected":
                self.action_status.setStyleSheet(
                    "background:#175cd3;color:white;padding:10px;border-radius:6px;"
                )
                return

            self.action_status.setStyleSheet(
                "background:#b42318;color:white;padding:10px;border-radius:6px;"
            )
            evidence = event.evidence
            app_event = build_detected_fall_event(
                window_id=event.event_id,
                detected_at=event.detected_at,
                room_id=str(self.active_profile["roomId"]),
                risk_score=event.confidence,
                motion_confidence=event.confidence,
                presence_state=str(evidence["presence_state"]),
                presence_probability=float(evidence["presence_probability"]),
                no_recovery_sec=float(evidence["no_recovery_sec"]),
            )
            endpoint = self.fall_alert_endpoint.text().strip()
            if not endpoint:
                self.record_alert_delivery(
                    app_event,
                    status="skipped",
                    message="앱 서버 주소 미설정",
                )
                self.action_status.setText(
                    "자동 행동 감지: 낙상 의심 기록 완료 | 앱 서버 주소가 없어 알림 미전송"
                )
                return
            self.start_fall_alert_delivery(endpoint, app_event, "자동 낙상 의심 감지")

        def send_manual_fall_alert_test(self) -> None:
            endpoint = self.fall_alert_endpoint.text().strip()
            if not endpoint:
                QMessageBox.warning(
                    self,
                    "앱 서버 주소 필요",
                    "'낙상 알림 서버'에 http://<서버-IP>:8080 형식으로 입력하세요.",
                )
                return

            window_id = f"manual-test-{uuid4().hex}"
            event = build_collection_fall_event(
                session_id=window_id,
                detected_at=utc_now(),
                room_id=str(self.active_profile["roomId"]),
            )
            self.start_fall_alert_delivery(endpoint, event, "앱 알림 테스트")

        def start_fall_alert_delivery(
            self,
            endpoint: str,
            event: dict[str, object],
            status_prefix: str,
        ) -> None:
            worker = FallAlertWorker(endpoint, event)
            self.fall_alert_workers.append(worker)
            self.pending_fall_alerts[str(event["window_id"])] = event
            self.record_alert_delivery(event, status="sending")
            worker.delivered.connect(self.fall_alert_delivered)
            worker.failed.connect(self.fall_alert_failed)
            worker.finished.connect(lambda: self.release_fall_alert_worker(worker))
            self.collection_status.setText(
                f"{status_prefix} | 앱 알림 전송 중: {event['window_id']}"
            )
            self.action_status.setText(
                f"{status_prefix} | 앱 알림 전송 중: {event['window_id']}"
            )
            worker.start()

        def record_alert_delivery(
            self,
            event: dict[str, object],
            *,
            status: str,
            message: str | None = None,
        ) -> None:
            self.event_journal.append(
                {
                    "schema_version": "1.0",
                    "event_type": "fall_alert_delivery",
                    "window_id": event["window_id"],
                    "detected_at": event["detected_at"],
                    "recorded_at": utc_now(),
                    "room_id": event["room_id"],
                    "status": status,
                    "message": message,
                }
            )
            self.refresh_fall_history()

        def refresh_fall_history(self) -> None:
            records = self.event_journal.recent_fall_records(limit=20)
            self.fall_history.setPlainText(
                "\n".join(format_fall_history_record(record) for record in records)
            )

        def release_fall_alert_worker(self, worker: FallAlertWorker) -> None:
            if worker in self.fall_alert_workers:
                self.fall_alert_workers.remove(worker)
            worker.deleteLater()

        def fall_alert_delivered(self, window_id: str) -> None:
            event = self.pending_fall_alerts.pop(window_id, None)
            if event is not None:
                self.record_alert_delivery(event, status="delivered")
            self.collection_status.setText(
                f"낙상 의심 알림 전송 완료 | window_id: {window_id}"
            )
            self.action_status.setText(
                f"낙상 의심 알림 전송 완료 | window_id: {window_id}"
            )
            QMessageBox.information(
                self,
                "낙상 의심 알림 전송 완료",
                f"앱 서버가 이벤트를 접수했습니다.\nwindow_id: {window_id}",
            )

        def fall_alert_failed(self, window_id: str, message: str) -> None:
            failed_event = self.pending_fall_alerts.pop(window_id, None)
            if failed_event is not None:
                self.record_alert_delivery(
                    failed_event,
                    status="failed",
                    message=message,
                )
            self.collection_status.setText("낙상 의심 알림 전송 실패")
            self.action_status.setText("낙상 의심 알림 전송 실패 | 기록 저장됨")
            QMessageBox.warning(self, "낙상 의심 알림 전송 실패", message)

        def start_channel_scan(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            reply = QMessageBox.question(
                self,
                "채널 + 공간 통합 보정",
                "약 100초 동안 채널 1·6·11을 비교한 뒤 선택 채널에서 "
                "빈 공간 보정까지 자동으로 진행합니다.\n\n"
                "10초 안에 방을 나간 뒤 완료 안내가 나올 때까지 방을 비우고, "
                "보드·문·가구를 움직이지 않겠습니까?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

            self.integrated_calibration = True
            self.integrated_channel_summary.clear()
            self.scanning_channels = True
            self.show_presence(self.presence_detector.reset("measurement_in_progress"))
            self.scan_index = 0
            self.scan_phase = "leaving"
            self.scan_deadline = monotonic() + 10
            self.scan_results.clear()
            self.set_collection_controls_enabled(False)
            self.status.setText("통합 보정 준비 - 10초 안에 방을 비워 주세요")
            self.status.setStyleSheet(
                "background:#b54708;color:white;padding:18px;border-radius:8px;"
            )
            self.channel_scan_timer.start()

        def begin_channel_measurement(self) -> None:
            channel = self.scan_channels[self.scan_index]
            self.reader.send_command(f"rf_channel --set {channel}")
            self.scan_phase = "settling"
            self.scan_deadline = monotonic() + 4
            self.scan_link_samples.clear()
            self.scan_radar_times.clear()
            self.status.setText(f"CHANNEL {channel} - LINK SETTLING")

        def channel_scan_tick(self) -> None:
            now = monotonic()
            if now < self.scan_deadline:
                return

            if self.scan_phase == "leaving":
                self.begin_channel_measurement()
                return

            if self.scan_phase == "settling":
                channel = self.scan_channels[self.scan_index]
                self.scan_phase = "measuring"
                self.scan_deadline = now + 15
                self.scan_measure_started = now
                self.scan_link_samples.clear()
                self.scan_radar_times.clear()
                self.status.setText(f"MEASURING CHANNEL {channel} - 15 seconds")
                return

            if self.scan_phase == "measuring":
                channel = self.scan_channels[self.scan_index]
                frequencies = [sample.frequency_hz for sample in self.scan_link_samples]
                rssis = [sample.rssi for sample in self.scan_link_samples]
                if self.scan_radar_times:
                    gaps = [self.scan_radar_times[0] - self.scan_measure_started]
                    gaps.extend(
                        later - earlier
                        for earlier, later in zip(
                            self.scan_radar_times, self.scan_radar_times[1:]
                        )
                    )
                    gaps.append(now - self.scan_radar_times[-1])
                else:
                    gaps = [15.0]
                self.scan_results[channel] = {
                    "samples": float(len(frequencies)),
                    "min_hz": float(min(frequencies)) if frequencies else 0.0,
                    "avg_hz": sum(frequencies) / len(frequencies) if frequencies else 0.0,
                    "avg_rssi": sum(rssis) / len(rssis) if rssis else -999.0,
                    "max_gap": max(gaps) if gaps else 15.0,
                }
                self.scan_index += 1
                if self.scan_index < len(self.scan_channels):
                    self.begin_channel_measurement()
                    return
                self.finish_channel_scan()
                return

            if self.scan_phase == "finalizing":
                self.complete_channel_scan()

        def finish_channel_scan(self) -> None:
            selected = select_best_channel(self.scan_results)
            if selected is None:
                self.abort_channel_scan(
                    "No channel produced enough link data. Press RST on both boards; "
                    "they will return to channel 6."
                )
                return
            self.selected_scan_channel = selected
            self.reader.send_command(f"rf_channel --set {selected}")
            self.scan_phase = "finalizing"
            self.scan_deadline = monotonic() + 2
            self.status.setText(f"SELECTING CHANNEL {selected}")

        def complete_channel_scan(self) -> None:
            self.channel_scan_timer.stop()
            self.scanning_channels = False
            self.scan_phase = ""
            selected = self.selected_scan_channel
            self.integrated_channel_summary = render_channel_results(
                self.scan_channels, self.scan_results
            )
            self.status.setText(
                f"채널 {selected} 선택 완료 - 빈 공간 보정을 시작합니다"
            )
            self.begin_empty_room_calibration(
                delay_seconds=0,
                channel=selected,
                integrated=True,
            )

        def abort_channel_scan(self, message: str) -> None:
            self.channel_scan_timer.stop()
            self.scanning_channels = False
            self.scan_phase = ""
            self.integrated_calibration = False
            self.integrated_channel_summary.clear()
            self.show_presence(self.presence_detector.reset("measurement_failed"))
            self.set_collection_controls_enabled(True)
            self.status.setText("CHANNEL COMPARISON FAILED")
            self.status.setStyleSheet(
                "background:#b42318;color:white;padding:18px;border-radius:8px;"
            )
            QMessageBox.warning(self, "Channel comparison failed", message)

        def start_calibration(self) -> None:
            """개발용 단독 빈 공간 보정 진입점.

            기본 GUI는 통합 보정을 사용하지만 저장 채널에서 보정만 다시 시험할 때
            재사용할 수 있도록 내부 진입점은 유지한다.
            """
            reply = QMessageBox.question(
                self,
                "Empty-room calibration",
                "The room must remain empty during calibration. "
                "You will have 10 seconds to leave, followed by 30 seconds of calibration.",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

            self.integrated_calibration = False
            self.integrated_channel_summary.clear()
            self.begin_empty_room_calibration(delay_seconds=10, integrated=False)

        def begin_empty_room_calibration(
            self,
            *,
            delay_seconds: int,
            channel: int | None = None,
            integrated: bool,
        ) -> None:
            selected_channel = channel or self.current_channel or int(
                self.active_profile["radio"]["channel"]
            )
            update_profile_channel(
                self.project_root, self.active_profile, selected_channel
            )
            self.refresh_presence_baseline()
            self.refresh_profile_status()
            self.integrated_calibration = integrated
            self.calibration_channel = selected_channel
            self.calibrating = True
            self.show_presence(self.presence_detector.reset("calibrating"))
            self.set_collection_controls_enabled(False)
            self.jitter_values.clear()
            self.threshold_values.clear()
            self.jitter_curve.clear()
            self.threshold_curve.clear()

            if delay_seconds > 0:
                self.calibration_stage = "delay"
                self.calibration_remaining = delay_seconds
                self.status.setText(
                    f"LEAVE THE AREA - {self.calibration_remaining} seconds"
                )
            else:
                self.reader.send_command("radar --train_start")
                self.calibration_stage = "training"
                self.calibration_remaining = 30
                self.status.setText(
                    f"채널 {selected_channel} 빈 공간 보정 중 - 30초"
                )
            self.status.setStyleSheet(
                "background:#b54708;color:white;padding:18px;border-radius:8px;"
            )
            self.calibration_timer.start()

        def calibration_tick(self) -> None:
            self.calibration_remaining -= 1
            if self.calibration_stage == "delay":
                if self.calibration_remaining <= 0:
                    self.reader.send_command("radar --train_start")
                    self.calibration_stage = "training"
                    self.calibration_remaining = 30
                    self.status.setText("CALIBRATING EMPTY ROOM - 30 seconds")
                else:
                    self.status.setText(
                        f"LEAVE THE AREA - {self.calibration_remaining} seconds"
                    )
                return

            if self.calibration_stage == "waiting_result":
                if self.calibration_remaining > 0:
                    self.status.setText("보정 결과를 기다리는 중입니다")
                    return
                was_integrated = self.integrated_calibration
                self.calibration_timer.stop()
                self.calibrating = False
                self.calibration_stage = ""
                self.calibration_channel = None
                self.integrated_calibration = False
                self.integrated_channel_summary.clear()
                self.set_collection_controls_enabled(True)
                self.status.setText("보정 결과 저장 실패 - 다시 보정해 주세요")
                self.status.setStyleSheet(
                    "background:#b42318;color:white;padding:18px;border-radius:8px;"
                )
                if was_integrated:
                    QMessageBox.warning(
                        self,
                        "통합 보정 실패",
                        "채널은 선택해 저장했지만 빈 공간 보정 결과를 받지 못했습니다.\n"
                        "보드 연결을 확인한 뒤 통합 보정을 다시 실행해 주세요.",
                    )
                return

            if self.calibration_remaining > 0:
                self.status.setText(
                    f"CALIBRATING EMPTY ROOM - {self.calibration_remaining} seconds"
                )
                return

            self.reader.send_command("radar --train_stop")
            self.calibration_stage = "waiting_result"
            self.calibration_remaining = 5
            self.status.setText("보정 결과를 기다리는 중입니다")

        def update_calibration_result(self, sample: CalibrationSample) -> None:
            if not self.calibrating or self.calibration_stage != "waiting_result":
                return
            was_integrated = self.integrated_calibration
            channel_summary = list(self.integrated_channel_summary)
            self.calibration_timer.stop()
            self.calibrating = False
            self.calibration_stage = ""
            self.integrated_calibration = False
            self.integrated_channel_summary.clear()
            if self.calibration_channel is not None:
                self.active_profile["radio"]["channel"] = self.calibration_channel
            self.calibration_channel = None
            update_profile_calibration(
                self.project_root,
                self.active_profile,
                someone_threshold=sample.someone_threshold,
                move_threshold=sample.move_threshold,
            )
            self.refresh_presence_baseline()
            self.show_presence(self.presence_detector.reset("warming_up"))
            self.set_collection_controls_enabled(True)
            self.refresh_profile_status()
            self.status.setText(
                "통합 보정 완료 - 프로필 저장됨"
                if was_integrated
                else "CALIBRATION COMPLETE - PROFILE SAVED"
            )
            self.status.setStyleSheet(
                "background:#175cd3;color:white;padding:18px;border-radius:8px;"
            )
            QMessageBox.information(
                self,
                "채널 + 공간 통합 보정 완료"
                if was_integrated
                else "보정 및 프로필 저장 완료",
                (
                    ("\n".join(channel_summary) + "\n\n")
                    if channel_summary
                    else ""
                )
                + f"선택 채널: {self.active_profile['radio']['channel']}\n"
                + f"{self.active_profile['displayName']} 프로필에 채널과 빈 공간 "
                "보정값을 함께 저장했습니다.",
            )

        def update_device_mac(self, sample: DeviceMacSample) -> None:
            """RX 부팅 로그에서 관측한 MAC을 현재 프로필에 기록한다.

            이미 기록된 값이 있으면 아무것도 하지 않는다. 보드가 이미 실행
            중일 때 모니터를 붙이면 부팅 로그가 없어 관측되지 않는다.
            """
            if update_profile_rx_mac(self.project_root, self.active_profile, sample.mac):
                self.refresh_profile_status()

        def update_sample(self, sample: RadarSample) -> None:
            self.sample_count += 1
            now = monotonic()
            self.last_sample_at = now
            self.last_link_at = self.last_sample_at
            self.current_moving = sample.moving
            self.jitter_values.append(sample.jitter)
            self.threshold_values.append(sample.move_threshold)
            if self.scanning_channels and self.scan_phase == "measuring":
                self.scan_radar_times.append(self.last_sample_at)
            if self.collection_phase == "recording":
                self.collection_radar_samples.append(sample)

            if self.last_link_sample is None:
                self.link_status.setText("Wi-Fi CSI link: ACTIVE  |  Radar data received")
                self.link_status.setStyleSheet(
                    "background:#087f3d;color:white;padding:10px;border-radius:6px;"
                )
            else:
                self.show_link(self.last_link_sample)

            x_values = list(range(len(self.jitter_values)))
            self.jitter_curve.setData(x_values, list(self.jitter_values))
            self.threshold_curve.setData(x_values, list(self.threshold_values))
            self.plot.enableAutoRange(axis="y")

            if self.scanning_channels or self.calibrating:
                presence = self.presence_detector.reset("measurement_in_progress")
            else:
                presence = self.presence_detector.update(
                    sample,
                    calibrated=self.is_presence_calibrated(),
                    observed_at=now,
                )
            self.show_presence(presence)

            if self.scanning_channels or self.calibrating or self.collecting:
                self.live_detector.reset()
                self.action_status.setText("자동 행동 감지: 측정·수집 중 일시 정지")
            elif not self.is_presence_calibrated():
                self.live_detector.reset()
                self.action_status.setText("자동 행동 감지: 빈 공간 보정 필요")
            else:
                presence_state = (
                    "present"
                    if presence.state
                    in {PresenceState.PRESENT_ACTIVE, PresenceState.PRESENT_STATIC}
                    else "absent"
                    if presence.state == PresenceState.ABSENT
                    else "unknown"
                )
                for detected_event in self.live_detector.update(
                    sample,
                    observed_at=now,
                    detected_at=utc_now(),
                    presence_state=presence_state,
                    presence_probability=presence.presence_ratio,
                ):
                    if (
                        detected_event.event_type == "fall_suspected"
                        and self.activity_aggregator is not None
                    ):
                        fused = self.activity_aggregator.fuse_radar_fall(
                            detected_event,
                            observed_at=now,
                        )
                        self.handle_live_detection(
                            fused
                            if fused is not None
                            else self.activity_aggregator.radar_candidate(
                                detected_event
                            )
                        )
                    else:
                        self.handle_live_detection(detected_event)

            if self.scanning_channels or self.collecting:
                pass
            elif sample.moving:
                self.status.setText("MOVEMENT DETECTED")
                self.status.setStyleSheet(
                    "background:#087f3d;color:white;padding:18px;border-radius:8px;"
                )
            else:
                self.status.setText("STATIC")
                self.status.setStyleSheet(
                    "background:#343a40;color:white;padding:18px;border-radius:8px;"
                )

            elapsed = max(monotonic() - self.started_at, 0.001)
            self.details.setText(
                f"Port: {port}  |  Samples: {self.sample_count}  |  "
                f"Rate: {self.sample_count / elapsed:.1f}/s  |  "
                f"Jitter: {sample.jitter:.6f}  |  "
                f"Threshold: {sample.move_threshold:.6f}"
            )

        def update_link(self, sample: LinkSample) -> None:
            self.last_link_at = monotonic()
            self.last_link_sample = sample
            if self.scanning_channels and self.scan_phase == "measuring":
                self.scan_link_samples.append(sample)
            if self.collection_phase == "recording":
                self.collection_link_samples.append(sample)
            self.show_link(sample)

        def update_channel(self, sample: ChannelSample) -> None:
            self.current_channel = sample.channel
            self.channel_status.setText(
                f"Current Wi-Fi channel: {sample.channel}  |  Bandwidth: HT20"
            )

        def show_link(self, sample: LinkSample) -> None:
            if sample.rssi >= -65:
                quality, color = "GOOD", "#087f3d"
            elif sample.rssi >= -75:
                quality, color = "FAIR", "#b54708"
            else:
                quality, color = "WEAK", "#b42318"
            self.link_status.setText(
                f"Wi-Fi CSI link: {quality}  |  RSSI: {sample.rssi} dBm  |  "
                f"Packets: {sample.frequency_hz} Hz"
            )
            self.link_status.setStyleSheet(
                f"background:{color};color:white;padding:10px;border-radius:6px;"
            )

        def update_health(self) -> None:
            if self.calibrating or self.scanning_channels or self.collecting:
                return
            now = monotonic()
            self.show_presence(
                self.presence_detector.health(
                    calibrated=self.is_presence_calibrated(),
                    observed_at=now,
                )
            )
            if self.last_sample_at and now - self.last_sample_at > 10:
                self.status.setText("WAITING FOR NEXT RADAR RESULT")
                self.status.setStyleSheet(
                    "background:#b54708;color:white;padding:18px;border-radius:8px;"
                )
            if self.last_link_at and now - self.last_link_at > 10:
                self.link_status.setText("Wi-Fi CSI link data paused")
                self.link_status.setStyleSheet(
                    "background:#b42318;color:white;padding:10px;border-radius:6px;"
                )

        def show_error(self, message: str) -> None:
            self.live_detector.reset()
            self.action_status.setText("자동 행동 감지: 직렬 통신 오류로 중지")
            self.show_presence(self.presence_detector.reset("serial_error"))
            self.status.setText("SERIAL ERROR")
            self.status.setStyleSheet(
                "background:#b42318;color:white;padding:18px;border-radius:8px;"
            )
            self.details.setText(message)

        def is_presence_calibrated(self) -> bool:
            return (
                not bool(self.active_profile.get("needsCalibration", True))
                and self.active_profile.get("calibration") is not None
            )

        def show_presence(self, decision: PresenceDecision) -> None:
            if decision.state == PresenceState.PRESENT_ACTIVE:
                label, detail, color = "재실", "움직임 있음", "#087f3d"
            elif decision.state == PresenceState.PRESENT_STATIC:
                label, detail, color = "재실", "정지 상태", "#087f3d"
            elif decision.state == PresenceState.ABSENT:
                label, detail, color = "부재", "빈 상태 지속 확인", "#175cd3"
            else:
                reasons = {
                    "calibration_required": "빈 공간 보정 필요",
                    "calibrating": "빈 공간 보정 중",
                    "measurement_in_progress": "채널 비교 또는 보정 중",
                    "measurement_failed": "채널 비교 실패",
                    "radar_timeout": "Radar 데이터 중단",
                    "serial_error": "직렬 통신 오류",
                    "waiting_for_samples": "Radar 데이터 대기",
                    "warming_up": "판정 데이터 수집 중",
                    "confirming_presence": "재실 여부 확인 중",
                    "confirming_absence": "부재 지속 시간 확인 중",
                    "ambiguous_signal": "경계 신호 확인 중",
                    "profile_changed": "공간 프로필 변경됨",
                    "profile_applied": "프로필 적용 후 재확인 중",
                }
                label = "판단 불가"
                detail = reasons.get(decision.reason, "Radar 데이터 대기")
                color = "#b54708"

            ratio = decision.presence_ratio * 100
            self.presence_status.setText(
                f"재실 상태: {label} · {detail} · 재실 신호 {ratio:.0f}%"
            )
            self.presence_status.setStyleSheet(
                f"background:{color};color:white;padding:12px;border-radius:6px;"
            )

        def closeEvent(self, event) -> None:
            if self.calibrating and self.calibration_stage == "training":
                self.reader.send_command("radar --train_stop")
                QThread.msleep(250)
            if self.collecting:
                if self.collection_phase == "recording":
                    self.finish_collection(
                        valid=False,
                        invalid_reason="GUI 종료로 수집 중단",
                        show_dialog=False,
                    )
                else:
                    self.collection_timer.stop()
                    self.collecting = False
            self.reader.requestInterruption()
            self.reader.wait(1000)
            if self.activity_engine is not None:
                self.activity_engine.close()
            event.accept()

    app = QApplication(sys.argv)
    window = RadarWindow()
    window.show()
    return app.exec()
