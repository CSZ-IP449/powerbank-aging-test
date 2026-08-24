from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import hdlc
from app_logger import AppLogger, CommRecord, RoundRecord, SlotRecord
from mock_backend import MockBackend
from models import (
    FlowState,
    RunnerState,
    SlotData,
    SlotStats,
    SlotView,
    TestDirection,
    TestState,
    WarehouseState,
)
from serial_bridge import DualSerialManager
from stats_store import StatsStore

logger = logging.getLogger(__name__)

APP_VERSION = "v11.5"

PHASE_OUT = 'out_warehouse'
PHASE_IN = 'in_warehouse'
PHASE_IDLE = 'idle'

DEFAULT_SLOT_TIMEOUT_MS = 5000
DEFAULT_PHASE_INTERVAL_MS = 3000
DEFAULT_MAX_RETRY = 0
DEFAULT_POST_CMD_WAIT_MS = 300

# 失败原因
FAILURE_REASON_NONE = 0
FAILURE_REASON_OUT = 1
FAILURE_REASON_IN = 2
FAILURE_REASON_TIMEOUT = 3
FAILURE_REASON_DISCONNECT = 4
FAILURE_REASON_COMM = 5
FAILURE_REASON_PRECHECK = 6


def _is_disconnect_error(e: Exception) -> bool:
    """识别串口断线类异常"""
    msg = str(e).lower()
    if isinstance(e, (ConnectionError,)):
        return True
    return any(k in msg for k in ('not connected', 'disconnected', 'write failed', 'read loop exited'))


@dataclass
class TestConfig:
    target_test_count: int = 100
    max_retry: int = DEFAULT_MAX_RETRY
    slot_timeout_ms: int = DEFAULT_SLOT_TIMEOUT_MS
    phase_interval_ms: int = DEFAULT_PHASE_INTERVAL_MS
    post_cmd_wait_ms: int = DEFAULT_POST_CMD_WAIT_MS


class DeviceAdapter:
    """统一 SerialBridge 和 MockBackend 的接口"""

    def __init__(self, manager: Optional[DualSerialManager] = None, mock: Optional[MockBackend] = None):
        self._manager = manager
        self._mock = mock

    @property
    def is_mock(self) -> bool:
        return self._mock is not None

    @property
    def cabinet(self):
        return self._mock if self._mock is not None else self._manager.cabinet

    @property
    def fixture(self):
        return self._mock if self._mock is not None else self._manager.fixture

    def cabinet_send(self, frame: hdlc.HdlcFrame, timeout: float = 5.0) -> hdlc.HdlcFrame:
        return self.cabinet.send_and_wait(frame, timeout)

    def fixture_send(self, frame: hdlc.HdlcFrame, timeout: float = 5.0) -> hdlc.HdlcFrame:
        return self.fixture.send_and_wait(frame, timeout)

    @property
    def is_fixture_connected(self) -> bool:
        if self._mock is not None:
            return True
        return self._manager.is_fixture_connected()

    @property
    def is_cabinet_connected(self) -> bool:
        if self._mock is not None:
            return True
        return self._manager.is_cabinet_connected()


class TestRunner:
    def __init__(
        self,
        device: DeviceAdapter,
        stats_store: StatsStore,
        app_logger: AppLogger,
        config: TestConfig,
        on_state_change: Optional[Callable[[RunnerState], None]] = None,
        on_slot_change: Optional[Callable[[int, SlotView], None]] = None,
        on_round_complete: Optional[Callable[[RoundRecord], None]] = None,
    ):
        self._device = device
        self._stats = stats_store
        self._logger = app_logger
        self._config = config
        self._on_state_change = on_state_change
        self._on_slot_change = on_slot_change
        self._on_round_complete = on_round_complete

        self._state = RunnerState(
            target_test_count=config.target_test_count,
            current_round=0,
            current_phase=PHASE_IDLE,
            current_slot=0,
            flow_state=FlowState.IDLE,
        )
        self._slot_views: List[SlotView] = []
        self._command_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused
        self._current_round_id: Optional[str] = None
        self._round_out_success: dict[int, bool] = {}
        self._round_in_success: dict[int, bool] = {}
        self._out_failure_reason: dict[int, int] = {}
        self._prev_flow_state: Optional[FlowState] = None

    @property
    def state(self) -> RunnerState:
        return self._state

    @property
    def slot_views(self) -> List[SlotView]:
        return self._slot_views

    def initialize_slots(self, cabinet_model: str, slot_count: int):
        self._state.cabinet_model = cabinet_model
        self._state.slot_count = slot_count
        self._stats.clear_all()
        self._stats.ensure_slots(slot_count)
        self._slot_views = []
        for i in range(1, slot_count + 1):
            self._slot_views.append(SlotView(
                data=SlotData(slot_no=i),
                stats=self._stats.get_slot(i),
            ))
        self._emit_state()

    def start(self):
        if self._state.flow_state not in (FlowState.IDLE, FlowState.COMPLETED, FlowState.FAULT):
            return
        if not self._slot_views:
            return
        self._logger.log_operation('app_version', APP_VERSION)
        if not self._thread or not self._thread.is_alive():
            while not self._command_queue.empty():
                try:
                    self._command_queue.get_nowait()
                except queue.Empty:
                    break
            self.start_thread()
        self._command_queue.put('start')

    def pause(self):
        if self._state.flow_state in (FlowState.PAUSED, FlowState.IDLE):
            return
        self._command_queue.put('pause')

    def resume(self):
        if self._state.flow_state != FlowState.PAUSED:
            return
        self._command_queue.put('resume')

    def stop(self):
        self._command_queue.put('stop')

    def start_thread(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, name='test-runner', daemon=True)
        self._thread.start()

    def join(self, timeout: Optional[float] = None):
        if self._thread:
            self._thread.join(timeout)

    def _has_stop_request(self) -> bool:
        """安全地检查命令队列中是否有 stop 指令（不消费）。"""
        try:
            return self._command_queue.queue[0] == 'stop'
        except (IndexError, AttributeError):
            return False

    def _run_loop(self):
        try:
            while self._running:
                try:
                    cmd = self._command_queue.get_nowait()
                except queue.Empty:
                    cmd = None

                if cmd == 'stop':
                    self._handle_stop()
                    if self._state.flow_state == FlowState.IDLE:
                        break
                    continue
                elif cmd == 'pause':
                    self._prev_flow_state = self._state.flow_state
                    self._state.flow_state = FlowState.PAUSED
                    self._pause_event.clear()
                    self._emit_state()
                    continue
                elif cmd == 'resume':
                    self._pause_event.set()
                    if self._prev_flow_state is not None:
                        self._state.flow_state = self._prev_flow_state
                        self._prev_flow_state = None
                    self._emit_state()
                    continue
                elif cmd == 'start':
                    self._begin_test()

                self._pause_event.wait(timeout=0.1)
                if not self._pause_event.is_set():
                    continue

                self._tick()
                time.sleep(0.02)
        except Exception:
            logger.exception('test runner crashed')
            self._state.flow_state = FlowState.FAULT
            self._emit_state()
        finally:
            self._running = False

    def _begin_test(self):
        self._state.flow_state = FlowState.PRECHECK
        self._state.current_round = 1
        self._state.current_phase = PHASE_OUT
        self._state.current_slot = 1
        self._state.target_test_count = self._config.target_test_count
        self._state.started_at = _now_iso()
        self._current_round_id = f'R{int(time.time())}'
        self._round_out_success = {}
        self._round_in_success = {}
        self._out_failure_reason = {}

        # 初始化时先刷新所有槽位，确保 initial_id 被正确设置
        for i in range(1, self._state.slot_count + 1):
            try:
                self._refresh_slot(i)
            except Exception as e:
                self._logger.log_operation('init_refresh_fail', f'slot={i} err={e}')

        self._logger.log_round(RoundRecord(
            round_id=self._current_round_id,
            started_at=self._state.started_at,
            cabinet_model=self._state.cabinet_model,
            slot_count=self._state.slot_count,
            target_test_count=self._config.target_test_count,
            phase=PHASE_OUT,
        ))
        self._logger.log_operation('start', f'round={self._state.current_round} target={self._config.target_test_count}')
        self._emit_state()

    def _tick(self):
        fs = self._state.flow_state
        if fs == FlowState.IDLE or fs == FlowState.PAUSED or fs == FlowState.COMPLETED or fs == FlowState.FAULT:
            return
        if fs == FlowState.PRECHECK:
            self._do_precheck()
        elif fs == FlowState.COMMAND_SENT:
            # 发送阶段在这里执行
            pass
        elif fs == FlowState.WAIT_RESULT:
            # 等待结果阶段（实际由 send_and_wait 同步完成）
            pass
        elif fs == FlowState.NEXT_SLOT:
            self._do_next_slot()

    def _do_precheck(self):
        slot_no = self._state.current_slot
        slot_count = self._state.slot_count
        if slot_no > slot_count:
            self._handle_phase_end()
            return

        slot_view = self._slot_views[slot_no - 1]
        target = self._config.target_test_count
        if slot_view.stats.round_count >= target:
            self._logger.log_operation('skip_completed', f'slot={slot_no}')
            self._state.current_slot += 1
            self._emit_state()
            return

        try:
            self._refresh_slot(slot_no)
        except Exception as e:
            if _is_disconnect_error(e):
                self._state.flow_state = FlowState.FAULT
                self._state.current_slot = 0
                self._logger.log_operation('flow_fault', f'reason=disconnect slot={slot_no} err={e}')
                self._emit_state()
                return
            # 普通通信异常：跳过该槽位，不用过期数据做判定
            self._logger.log_operation('precheck_refresh_error', f'slot={slot_no} err={e}')
            self._state.current_slot += 1
            self._emit_state()
            return

        slot_view = self._slot_views[slot_no - 1]
        phase = self._state.current_phase
        if phase == PHASE_OUT:
            if slot_view.data.warehouse_state == int(WarehouseState.OUT_CABINET):
                self._logger.log_operation('skip_already_out', f'slot={slot_no}')
                # 槽位已出仓，仍需校验ID与初始一致
                precheck_ok = self._validate_out_precheck(slot_no)
                out_ok = self._evaluate_out(slot_no)
                if out_ok and precheck_ok:
                    self._round_out_success[slot_no] = True
                    self._out_failure_reason[slot_no] = FAILURE_REASON_NONE
                    self._stats.increment_out_success(slot_no)
                    self._stats.increment_success(slot_no)
                else:
                    self._round_out_success[slot_no] = False
                    if not precheck_ok:
                        self._out_failure_reason[slot_no] = FAILURE_REASON_PRECHECK
                    else:
                        self._out_failure_reason[slot_no] = FAILURE_REASON_OUT
                    self._stats.increment_out_failure(slot_no)
                self._stats.increment_out(slot_no)
                self._state.current_slot += 1
                self._emit_state()
                return
            self._execute_out(slot_no)
        elif phase == PHASE_IN:
            self._execute_in(slot_no)

    def _execute_out(self, slot_no: int):
        self._state.flow_state = FlowState.COMMAND_SENT
        self._emit_state()

        slot_view = self._slot_views[slot_no - 1]
        slot_view.test_direction = int(TestDirection.OUT_TEST)

        retry = 0
        success = False
        aborted = False
        command_executed = False
        last_error = ''
        failure_reason = FAILURE_REASON_OUT
        timeout_sec = self._config.slot_timeout_ms / 1000.0
        disconnect_detected = False
        last_precheck_ok = False
        started_monotonic = time.monotonic()

        while retry <= self._config.max_retry:
            if self._has_stop_request() or not self._pause_event.is_set():
                self._logger.log_operation('out_aborted', f'slot={slot_no} retry={retry}')
                aborted = True
                break

            # retry=0 时 _do_slot 已经执行了出仓前查询；重试时必须重新查询仓道状态
            if retry > 0:
                try:
                    self._refresh_slot(slot_no)
                except Exception as e:
                    if _is_disconnect_error(e):
                        failure_reason = FAILURE_REASON_DISCONNECT
                        disconnect_detected = True
                        self._logger.log_operation('out_disconnect', f'slot={slot_no} phase=precheck_retry err={e}')
                    else:
                        failure_reason = FAILURE_REASON_COMM
                        self._logger.log_operation('out_precheck_refresh_error', f'slot={slot_no} retry={retry} err={e}')
                    break

            precheck_ok = self._validate_out_precheck(slot_no)
            last_precheck_ok = precheck_ok
            if not precheck_ok:
                self._logger.log_operation('out_precheck_fail', f'slot={slot_no} retry={retry}')

            slot_view.test_state = int(TestState.RUNNING)
            self._emit_slot(slot_no)

            try:
                resp = self._device.cabinet_send(
                    hdlc.build_cabinet_out_frame(slot_no),
                    timeout=timeout_sec,
                )
                out_resp = hdlc.parse_cabinet_out_response(resp.payload)
                if out_resp.slot_no != slot_no:
                    raise RuntimeError(f'slot mismatch: {out_resp.slot_no} != {slot_no}')
                if not out_resp.accepted:
                    last_error = f'cabinet rejected status={out_resp.status:02X}'
                    retry += 1
                    continue

                command_executed = True
                time.sleep(self._config.post_cmd_wait_ms / 1000.0)
                self._refresh_slot(slot_no)
                final_state = self._slot_views[slot_no - 1]

                eval_ok = self._evaluate_out(slot_no)
                # 预校验失败 或 物理出仓失败 都视为本次尝试失败
                success = eval_ok and precheck_ok
                if success:
                    break  # 成功，停止重试
                # 失败但还有重试次数：进入下一轮完整流程（出仓前查询→下发→出仓后查询）
                if retry < self._config.max_retry:
                    retry += 1
                    continue
                # 重试耗尽，保留最终失败结果跳出
                break
            except TimeoutError as e:
                last_error = str(e)
                failure_reason = FAILURE_REASON_TIMEOUT
                self._logger.log_operation('out_timeout', f'slot={slot_no} retry={retry}')
                break
            except Exception as e:
                last_error = str(e)
                if _is_disconnect_error(e):
                    failure_reason = FAILURE_REASON_DISCONNECT
                    disconnect_detected = True
                    self._logger.log_operation('out_disconnect', f'slot={slot_no} err={e}')
                    break
                failure_reason = FAILURE_REASON_COMM
                self._logger.log_operation('out_error', f'slot={slot_no} retry={retry} err={e}')
                break

        slot_view = self._slot_views[slot_no - 1]
        if aborted:
            slot_view.test_state = int(TestState.CANCELLED)
            slot_view.app_result = 0
            slot_view.failure_reason = FAILURE_REASON_NONE
            self._round_out_success[slot_no] = False
            self._out_failure_reason[slot_no] = FAILURE_REASON_NONE
        elif command_executed:
            self._stats.increment_out(slot_no)
            if success and last_precheck_ok:
                slot_view.test_state = int(TestState.SUCCESS)
                slot_view.app_result = 1
                slot_view.failure_reason = FAILURE_REASON_NONE
                self._out_failure_reason[slot_no] = FAILURE_REASON_NONE
                self._stats.increment_out_success(slot_no)
                self._stats.increment_success(slot_no)
                self._round_out_success[slot_no] = True
            else:
                if not last_precheck_ok:
                    slot_view.test_state = int(TestState.FAILED)
                    slot_view.app_result = 2
                    slot_view.failure_reason = FAILURE_REASON_PRECHECK
                    self._out_failure_reason[slot_no] = FAILURE_REASON_PRECHECK
                else:
                    slot_view.test_state = int(TestState.FAILED)
                    slot_view.app_result = 2
                    slot_view.failure_reason = failure_reason
                    self._out_failure_reason[slot_no] = failure_reason
                self._stats.increment_out_failure(slot_no)
                self._round_out_success[slot_no] = False
        else:
            slot_view.test_state = int(TestState.FAILED)
            slot_view.app_result = 2
            if not last_precheck_ok:
                slot_view.failure_reason = FAILURE_REASON_PRECHECK
                self._out_failure_reason[slot_no] = FAILURE_REASON_PRECHECK
            else:
                slot_view.failure_reason = FAILURE_REASON_COMM
                self._out_failure_reason[slot_no] = FAILURE_REASON_COMM
            self._stats.increment_out_failure(slot_no)
            self._round_out_success[slot_no] = False

        self._logger.log_slot(SlotRecord(
            record_id=f'S{slot_no}R{self._state.current_round}O{int(time.time())}',
            round_id=self._current_round_id,
            slot_no=slot_no,
            direction='out',
            started_at=self._state.started_at or _now_iso(),
            finished_at=_now_iso(),
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            retry_count=retry,
            data_before='',
            data_after='',
            cabinet_result=slot_view.data.test_result,
            app_result=slot_view.app_result,
            failure_reason=slot_view.failure_reason,
        ))

        # 断线直接进入 FAULT，避免后续槽位持续失败
        if disconnect_detected:
            self._state.flow_state = FlowState.FAULT
            self._state.current_slot = 0
            self._logger.log_operation('flow_fault', f'reason=disconnect slot={slot_no}')
            self._emit_slot(slot_no)
            self._emit_state()
            return

        self._state.flow_state = FlowState.NEXT_SLOT
        self._emit_slot(slot_no)
        self._emit_state()

    def _execute_in(self, slot_no: int):
        self._state.flow_state = FlowState.COMMAND_SENT
        self._emit_state()

        slot_view = self._slot_views[slot_no - 1]
        slot_view.test_direction = int(TestDirection.IN_TEST)
        slot_view.test_state = int(TestState.RUNNING)
        self._emit_slot(slot_no)

        retry = 0
        success = False
        aborted = False
        command_executed = False
        last_error = ''
        failure_reason = FAILURE_REASON_IN
        timeout_sec = self._config.slot_timeout_ms / 1000.0
        disconnect_detected = False
        started_monotonic = time.monotonic()

        while retry <= self._config.max_retry:
            if self._has_stop_request() or not self._pause_event.is_set():
                self._logger.log_operation('in_aborted', f'slot={slot_no} retry={retry}')
                aborted = True
                break
            # retry=0 时 _do_slot 已经刷新过仓道；重试时必须重新查询状态
            if retry > 0:
                try:
                    self._refresh_slot(slot_no)
                except Exception as e:
                    if _is_disconnect_error(e):
                        failure_reason = FAILURE_REASON_DISCONNECT
                        disconnect_detected = True
                        self._logger.log_operation('in_disconnect', f'slot={slot_no} phase=precheck_retry err={e}')
                    else:
                        failure_reason = FAILURE_REASON_COMM
                        self._logger.log_operation('in_precheck_refresh_error', f'slot={slot_no} retry={retry} err={e}')
                    break
            try:
                self._logger.log_operation('in_send', f'slot={slot_no} sending fixture_in timeout={timeout_sec}')
                resp = self._device.fixture_send(
                    hdlc.build_fixture_in_frame(slot_no),
                    timeout=timeout_sec,
                )
                self._logger.log_operation('in_recv', f'slot={slot_no} fixture response len={len(resp.payload)}')
                fr = hdlc.parse_fixture_in_response(resp.payload)
                self._logger.log_operation('in_parse', f'slot={slot_no} slot={fr.slot_no} status={fr.status:02X} accepted={fr.accepted}')
                if not fr.accepted:
                    last_error = f'fixture rejected slot={fr.slot_no} status={fr.status:02X}'
                    retry += 1
                    continue

                command_executed = True
                time.sleep(self._config.post_cmd_wait_ms / 1000.0)
                self._refresh_slot(slot_no)
                final_state = self._slot_views[slot_no - 1]

                eval_ok = self._evaluate_in(slot_no)
                if eval_ok:
                    success = True
                    break
                # 物理进仓失败但仍有重试次数：重试完整流程
                if retry < self._config.max_retry:
                    retry += 1
                    continue
                # 重试耗尽，保留最终失败
                success = False
                break
            except TimeoutError as e:
                last_error = str(e)
                failure_reason = FAILURE_REASON_TIMEOUT
                fixture_connected = self._device.is_fixture_connected if hasattr(self._device, 'is_fixture_connected') else 'unknown'
                self._logger.log_operation('in_timeout', f'slot={slot_no} retry={retry} fixture_connected={fixture_connected} err={e}')
                break
            except Exception as e:
                last_error = str(e)
                if _is_disconnect_error(e):
                    failure_reason = FAILURE_REASON_DISCONNECT
                    disconnect_detected = True
                    self._logger.log_operation('in_disconnect', f'slot={slot_no} err={e}')
                    break
                failure_reason = FAILURE_REASON_COMM
                self._logger.log_operation('in_error', f'slot={slot_no} retry={retry} err={e}')
                break

        slot_view = self._slot_views[slot_no - 1]
        if aborted:
            slot_view.test_state = int(TestState.CANCELLED)
            slot_view.app_result = 0
            slot_view.failure_reason = FAILURE_REASON_NONE
            self._round_in_success[slot_no] = False
        elif command_executed:
            self._stats.increment_in(slot_no)
            out_ok = self._round_out_success.get(slot_no, False)
            out_failure_reason = self._out_failure_reason.get(slot_no, FAILURE_REASON_NONE)
            if success:
                self._stats.increment_in_success(slot_no)
                self._round_in_success[slot_no] = True
                if out_ok:
                    slot_view.test_state = int(TestState.SUCCESS)
                    slot_view.app_result = 1
                    slot_view.failure_reason = FAILURE_REASON_NONE
                    self._stats.increment_success(slot_no)
                else:
                    slot_view.test_state = int(TestState.FAILED)
                    slot_view.app_result = 2
                    slot_view.failure_reason = out_failure_reason
                    self._round_in_success[slot_no] = False
            else:
                slot_view.test_state = int(TestState.FAILED)
                slot_view.app_result = 2
                slot_view.failure_reason = failure_reason
                self._stats.increment_in_failure(slot_no)
                self._round_in_success[slot_no] = False
        else:
            slot_view.test_state = int(TestState.FAILED)
            slot_view.app_result = 2
            slot_view.failure_reason = FAILURE_REASON_COMM
            self._stats.increment_in_failure(slot_no)
            self._round_in_success[slot_no] = False

        self._logger.log_slot(SlotRecord(
            record_id=f'S{slot_no}R{self._state.current_round}I{int(time.time())}',
            round_id=self._current_round_id,
            slot_no=slot_no,
            direction='in',
            started_at=self._state.started_at or _now_iso(),
            finished_at=_now_iso(),
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            retry_count=retry,
            data_before='',
            data_after='',
            cabinet_result=slot_view.data.test_result,
            app_result=slot_view.app_result,
            failure_reason=slot_view.failure_reason,
        ))

        if disconnect_detected:
            self._state.flow_state = FlowState.FAULT
            self._state.current_slot = 0
            self._logger.log_operation('flow_fault', f'reason=disconnect slot={slot_no}')
            self._emit_slot(slot_no)
            self._emit_state()
            return

        self._state.flow_state = FlowState.NEXT_SLOT
        self._emit_slot(slot_no)
        self._emit_state()

    def _evaluate_out(self, slot_no: int) -> bool:
        sv = self._slot_views[slot_no - 1]
        d = sv.data
        lock_ok = d.lock_button == 0
        tray_ok = d.tray_button == 1
        detect_ok = d.detect_button == 1
        id_ok_expected = sv.initial_id_ok == 1 and d.id_ok == 0
        result = lock_ok and tray_ok and detect_ok and id_ok_expected
        self._logger.log_operation('evaluate_out', f'slot={slot_no} lock={d.lock_button}(expect0={lock_ok}) tray={d.tray_button}(expect1={tray_ok}) detect={d.detect_button}(expect1={detect_ok}) id_ok={d.id_ok}(expect0={id_ok_expected}) result={result}')
        return result

    def _validate_out_precheck(self, slot_no: int) -> bool:
        """出仓前预校验：id_ok=1, ID与初始一致, 锁扣=0, 托盘=0, 检测=0。"""
        sv = self._slot_views[slot_no - 1]
        d = sv.data
        if d.id_ok != 1:
            self._logger.log_operation('out_precheck_fail', f'slot={slot_no} reason=id_ok_{d.id_ok}')
            return False
        if sv.initial_id is None:
            self._logger.log_operation('out_precheck_fail', f'slot={slot_no} reason=no_initial_id')
            return False
        if list(d.power_bank_id) != list(sv.initial_id):
            self._logger.log_operation('out_precheck_fail', f'slot={slot_no} reason=id_mismatch')
            return False
        if d.lock_button != 0:
            self._logger.log_operation('out_precheck_fail', f'slot={slot_no} reason=lock_{d.lock_button}')
            return False
        if d.tray_button != 0:
            self._logger.log_operation('out_precheck_fail', f'slot={slot_no} reason=tray_{d.tray_button}')
            return False
        if d.detect_button != 0:
            self._logger.log_operation('out_precheck_fail', f'slot={slot_no} reason=detect_{d.detect_button}')
            return False
        return True

    def _evaluate_in(self, slot_no: int) -> bool:
        sv = self._slot_views[slot_no - 1]
        d = sv.data
        lock_ok = d.lock_button == 0
        tray_ok = d.tray_button == 0
        detect_ok = d.detect_button == 0
        id_ok_match = d.id_ok == 1
        id_match = True
        if sv.initial_id is not None:
            id_match = list(d.power_bank_id) == list(sv.initial_id)
        result = lock_ok and tray_ok and detect_ok and id_ok_match and id_match
        self._logger.log_operation('evaluate_in', f'slot={slot_no} lock={d.lock_button}(expect0={lock_ok}) tray={d.tray_button}(expect0={tray_ok}) detect={d.detect_button}(expect0={detect_ok}) id_ok={d.id_ok}(expect1={id_ok_match}) id_match={id_match} result={result}')
        return result

    def _do_next_slot(self):
        next_slot = self._state.current_slot + 1
        if next_slot > self._state.slot_count:
            self._handle_phase_end()
            return
        self._state.current_slot = next_slot
        self._state.flow_state = FlowState.PRECHECK
        self._emit_state()

    def _handle_phase_end(self):
        phase = self._state.current_phase
        if phase == PHASE_OUT:
            self._logger.log_operation('phase_end', f'round={self._state.current_round} phase=out')
            self._state.flow_state = FlowState.WAIT_RESULT
            self._emit_state()
            self._sleep_with_pause(self._config.phase_interval_ms / 1000.0)
            self._state.current_phase = PHASE_IN
            self._state.current_slot = 1
            self._state.flow_state = FlowState.PRECHECK
            self._emit_state()
        elif phase == PHASE_IN:
            self._logger.log_operation('phase_end', f'round={self._state.current_round} phase=in')
            self._finalize_round()
            if self._all_completed():
                self._state.flow_state = FlowState.COMPLETED
                self._state.current_slot = 0
                self._logger.log_operation('completed', f'round={self._state.current_round}')
            else:
                self._state.current_round += 1
                self._state.current_phase = PHASE_OUT
                self._state.current_slot = 1
                self._state.flow_state = FlowState.PRECHECK
                self._round_out_success = {}
                self._round_in_success = {}
                self._out_failure_reason = {}
            self._emit_state()

    def _finalize_round(self):
        success_count = 0
        failure_count = 0
        for i in range(1, self._state.slot_count + 1):
            out_ok = self._round_out_success.get(i, False)
            in_ok = self._round_in_success.get(i, False)
            sv = self._slot_views[i - 1]
            self._stats.increment_round(i)
            self._stats.increment_completed(i)
            self._logger.log_operation('finalize_round', f'slot={i} out_ok={out_ok} in_ok={in_ok} out_reason={self._out_failure_reason.get(i, "N/A")}')
            if out_ok and in_ok:
                success_count += 1
                sv.test_state = int(TestState.SUCCESS)
                sv.failure_reason = FAILURE_REASON_NONE
            else:
                failure_count += 1
                self._stats.increment_failure(i)
                sv.test_state = int(TestState.FAILED)
                if not out_ok:
                    sv.failure_reason = self._out_failure_reason.get(i, FAILURE_REASON_OUT)
                elif not in_ok:
                    sv.failure_reason = FAILURE_REASON_IN
            self._emit_slot(i)
            self._logger.log_operation('slot_completed', f'slot={i} completed={self._stats.get_slot(i).completed_test_count}')

        self._logger.log_round(RoundRecord(
            round_id=self._current_round_id or '',
            started_at=self._state.started_at or _now_iso(),
            finished_at=_now_iso(),
            cabinet_model=self._state.cabinet_model,
            slot_count=self._state.slot_count,
            target_test_count=self._config.target_test_count,
            phase=PHASE_IN,
            success_count=success_count,
            failure_count=failure_count,
        ))

    def _all_completed(self) -> bool:
        target = self._config.target_test_count
        for sv in self._slot_views:
            if sv.stats.round_count < target:
                return False
        return True

    def _handle_stop(self):
        self._logger.log_operation('stop', f'flow={self._state.flow_state}')
        for sv in self._slot_views:
            if sv.test_state in (int(TestState.RUNNING), int(TestState.WAITING), int(TestState.NOT_TESTED)):
                sv.test_state = int(TestState.CANCELLED)
        if 1 <= self._state.current_slot <= self._state.slot_count:
            current_sv = self._slot_views[self._state.current_slot - 1]
            if current_sv.test_state not in (int(TestState.SUCCESS), int(TestState.FAILED), int(TestState.TIMEOUT), int(TestState.CANCELLED)):
                current_sv.test_state = int(TestState.CANCELLED)
        for i in range(1, self._state.slot_count + 1):
            self._emit_slot(i)
        self._state.flow_state = FlowState.IDLE
        self._state.current_phase = PHASE_IDLE
        self._state.current_slot = 0
        self._pause_event.set()
        self._emit_state()

    def _refresh_slot(self, slot_no: int):
        """主动刷新单槽状态。抛出异常让调用方决定如何处理（断线/超时等）。"""
        resp = self._device.cabinet_send(hdlc.build_get_slot_data_frame(slot_no), timeout=2.0)
        slot_raw = hdlc.parse_slot_data(resp.payload)
        if slot_raw.slot_no != slot_no:
            self._logger.log_operation('slot_mismatch', f'req={slot_no} resp={slot_raw.slot_no}')
            return
        sv = self._slot_views[slot_no - 1]
        sv.data = SlotData(
            slot_no=slot_raw.slot_no,
            warehouse_state=slot_raw.warehouse_state,
            id_ok=slot_raw.id_ok,
            power_bank_id=list(slot_raw.power_bank_id),
            lock_button=slot_raw.lock_button,
            tray_button=slot_raw.tray_button,
            detect_button=slot_raw.detect_button,
            test_result=slot_raw.test_result,
            error_code=slot_raw.error_code,
        )
        # 首次刷新到 id_ok=1 的槽位时保存初始 ID（需求：app 初始化时先读取并保存该槽位的宝 ID）
        if sv.initial_id is None and sv.data.id_ok == 1:
            sv.initial_id = list(sv.data.power_bank_id)
            sv.initial_id_ok = sv.data.id_ok
        self._emit_slot(slot_no)

    def _sleep_with_pause(self, seconds: float):
        """暂停期间阻塞等待，恢复后才继续消耗剩余时间。收到 stop 时立即返回。"""
        deadline = time.monotonic() + seconds
        while True:
            if self._has_stop_request():
                return
            now = time.monotonic()
            if now >= deadline:
                return
            if not self._pause_event.is_set():
                pause_start = now
                self._pause_event.wait(timeout=0.5)
                if self._pause_event.is_set():
                    deadline += time.monotonic() - pause_start
            else:
                time.sleep(0.1)

    def _emit_state(self):
        if self._on_state_change:
            try:
                self._on_state_change(self._state)
            except Exception:
                logger.exception('state change callback error')

    def _emit_slot(self, slot_no: int):
        if self._on_slot_change:
            try:
                sv = self._slot_views[slot_no - 1]
                sv.stats = self._stats.get_slot(slot_no)
                self._on_slot_change(slot_no, sv)
            except Exception:
                logger.exception('slot change callback error')


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec='seconds')
