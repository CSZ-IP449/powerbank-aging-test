from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Optional

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

import hdlc
from app_logger import AppLogger, CommRecord, OperationRecord
from mock_backend import MockBackend
from models import (
    ConnectionStatus,
    DeviceInfo,
    DeviceType,
    FlowState,
    RunnerState,
    SlotData,
    SlotStats,
    SlotView,
    TestDirection,
    TestState,
    WarehouseState,
    format_power_bank_id,
)
from serial_bridge import DualSerialManager, list_available_ports
from stats_store import StatsStore
from test_runner import DeviceAdapter, TestConfig, TestRunner

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def _get_base_dir():
    """可写目录：exe 同级（打包后）或 backend 源码目录（开发时）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _get_bundle_dir():
    """资源目录：PyInstaller onefile 解包后的 _MEIPASS；开发时与 BASE_DIR 一致"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _get_base_dir()
BUNDLE_DIR = _get_bundle_dir()
DATA_DIR = os.path.join(BASE_DIR, 'data')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
DIST_DIR = os.path.join(BUNDLE_DIR, 'dist')
for d in (DATA_DIR, LOG_DIR):
    try:
        os.makedirs(d, exist_ok=True)
    except PermissionError:
        pass  # 权限不足时降级，日志/统计写入会跳过


COMM_LOG_CAPACITY = 500


class AppState:
    def __init__(self):
        self.manager = DualSerialManager(
            on_cabinet_status=lambda s, e: self._on_connection('cabinet', s, e),
            on_fixture_status=lambda s, e: self._on_connection('fixture', s, e),
            on_comm_log=lambda dev, direction, raw_hex, slot_no: self._on_comm(dev, direction, raw_hex, slot_no),
        )
        self.mock = None
        self.device: Optional[DeviceAdapter] = None
        self.app_logger = AppLogger(LOG_DIR)
        self.stats_store = StatsStore(DATA_DIR)
        self.config = TestConfig()
        self.runner: Optional[TestRunner] = None
        self.cabinet_info = DeviceInfo(device_type=DeviceType.CABINET)
        self.fixture_info = DeviceInfo(device_type=DeviceType.FIXTURE)
        self._sse_clients: list[queue.Queue] = []
        self._sse_lock = threading.Lock()
        self._comm_log_deque = deque(maxlen=COMM_LOG_CAPACITY)
        self._comm_log_id = 0
        self._comm_log_lock = threading.Lock()

    def emit(self, event: str, data: Any):
        payload = json.dumps({'event': event, 'data': data}, ensure_ascii=False, default=str)
        with self._sse_lock:
            dead = []
            for q in self._sse_clients:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._sse_clients.remove(q)

    def register_sse(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._sse_lock:
            self._sse_clients.append(q)
        return q

    def unregister_sse(self, q: queue.Queue):
        with self._sse_lock:
            if q in self._sse_clients:
                self._sse_clients.remove(q)

    def _on_connection(self, device: str, status: str, error: Optional[str]):
        if device == 'cabinet':
            self.cabinet_info.status = status
            self.cabinet_info.error_message = error
        else:
            self.fixture_info.status = status
            self.fixture_info.error_message = error
        self.app_logger.log_connection(device, status, error or '')
        self.emit('connection', {
            'device': device,
            'status': status,
            'error': error,
        })

    def _on_comm(self, device: str, direction: str, raw_hex: str, slot_no: Optional[int]):
        with self._comm_log_lock:
            self._comm_log_id += 1
            entry = {
                'id': self._comm_log_id,
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'device': device,
                'direction': direction,
                'raw_hex': raw_hex,
                'slot_no': slot_no,
            }
            self._comm_log_deque.append(entry)
        self.app_logger.log_comm(CommRecord(
            timestamp=entry['timestamp'],
            device=device,
            direction=direction,
            raw_hex=raw_hex,
            parsed='',
            slot_no=slot_no,
        ))
        self.emit('comm', entry)

    def init_mock(self):
        if self.mock is None:
            self.mock = MockBackend()
            self.mock.set_comm_log_hook(
                lambda direction, raw_hex, parsed_hex, slot_no: self._on_comm('mock', direction, raw_hex, slot_no)
            )
        self.device = DeviceAdapter(mock=self.mock)
        self.cabinet_info.status = ConnectionStatus.CONNECTED
        self.cabinet_info.port = 'MOCK'
        self.fixture_info.status = ConnectionStatus.CONNECTED
        self.fixture_info.port = 'MOCK'
        self._init_runner()
        self.app_logger.log_operation('mock_enabled', '')

    def init_real(self):
        self.device = DeviceAdapter(manager=self.manager)
        self._init_runner()

    def _init_runner(self):
        if self.runner is None and self.device is not None:
            self.runner = TestRunner(
                device=self.device,
                stats_store=self.stats_store,
                app_logger=self.app_logger,
                config=self.config,
                on_state_change=lambda s: self.emit('state', s.to_dict()),
                on_slot_change=lambda slot_no, sv: self.emit('slot', {'slot_no': slot_no, **sv.to_dict()}),
            )
            self.runner.start_thread()
        elif self.runner is not None and self.device is not None:
            # 切换 mock/real 时同步更新 runner 持有的 device，避免 runner 还用旧的
            self.runner._device = self.device

    def refresh_all_slots(self):
        if not self.runner:
            return
        for i in range(1, self.runner.state.slot_count + 1):
            try:
                self.runner._refresh_slot(i)
            except Exception as e:
                logger.warning(f'refresh slot {i} failed: {e}')

    def get_full_status(self) -> dict:
        runner_state = self.runner.state.to_dict() if self.runner else RunnerState().to_dict()
        slots = []
        if self.runner:
            for sv in self.runner.slot_views:
                slot_dict = sv.to_dict()
                slot_dict['id_display'] = format_power_bank_id(sv.data.power_bank_id)
                slot_dict['initial_id_display'] = (
                    format_power_bank_id(sv.initial_id) if sv.initial_id else None
                )
                slots.append(slot_dict)
        return {
            'cabinet': self.cabinet_info.to_dict(),
            'fixture': self.fixture_info.to_dict(),
            'runner': runner_state,
            'slots': slots,
            'config': {
                'target_test_count': self.config.target_test_count,
                'max_retry': self.config.max_retry,
                'slot_timeout_ms': self.config.slot_timeout_ms,
                'phase_interval_ms': self.config.phase_interval_ms,
            },
        }


state = AppState()


def _parse_debug_response(command: int, payload: bytes) -> dict:
    """解析调试发送的响应，返回可读字典。"""
    try:
        if command == 0x01:
            model, slot_count = hdlc.parse_cabinet_info(payload)
            return {'model': model, 'slot_count': slot_count}
        elif command == 0x02:
            s = hdlc.parse_slot_data(payload)
            return {
                'slot_no': s.slot_no,
                'warehouse_state': s.warehouse_state,
                'id_ok': s.id_ok,
                'power_bank_id': s.power_bank_id.hex(' ').upper() if isinstance(s.power_bank_id, (bytes, bytearray)) else str(s.power_bank_id),
                'lock_button': s.lock_button,
                'tray_button': s.tray_button,
                'detect_button': s.detect_button,
            }
        elif command == 0x03:
            r = hdlc.parse_fixture_in_response(payload)
            return {'slot_no': r.slot_no, 'accepted': r.accepted, 'status': f'0x{r.status:02X}'}
        elif command == 0x04:
            r = hdlc.parse_cabinet_out_response(payload)
            return {'slot_no': r.slot_no, 'accepted': r.accepted, 'status': f'0x{r.status:02X}'}
    except Exception as e:
        return {'parse_error': str(e)}
    return {}


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)

    @app.get('/api/health')
    def health():
        return jsonify({'ok': True})

    @app.get('/api/version')
    def version():
        return jsonify({'name': 'aging-test-app', 'version': '11.5.0'})

    @app.get('/api/ports')
    def ports():
        return jsonify({'ports': list_available_ports()})

    @app.get('/api/status')
    def status():
        return jsonify(state.get_full_status())

    @app.post('/api/connect/cabinet')
    def connect_cabinet():
        data = request.get_json(force=True) or {}
        port = data.get('port')
        baudrate = int(data.get('baudrate', 115200))
        if not port:
            return jsonify({'ok': False, 'error': 'port required'}), 400
        ok = state.manager.connect_cabinet(port, baudrate)
        if ok:
            state.init_real()
            state.app_logger.log_operation('connect_cabinet', f'port={port} baud={baudrate}')
        return jsonify({'ok': ok, 'status': state.cabinet_info.status})

    @app.post('/api/connect/fixture')
    def connect_fixture():
        data = request.get_json(force=True) or {}
        port = data.get('port')
        baudrate = int(data.get('baudrate', 115200))
        if not port:
            return jsonify({'ok': False, 'error': 'port required'}), 400
        ok = state.manager.connect_fixture(port, baudrate)
        if ok:
            if state.device is None or state.device.is_mock:
                state.init_real()
            state.app_logger.log_operation('connect_fixture', f'port={port} baud={baudrate}')
        return jsonify({'ok': ok, 'status': state.fixture_info.status})

    @app.post('/api/disconnect/cabinet')
    def disconnect_cabinet():
        state.manager.disconnect_cabinet()
        return jsonify({'ok': True})

    @app.post('/api/disconnect/fixture')
    def disconnect_fixture():
        state.manager.disconnect_fixture()
        return jsonify({'ok': True})

    @app.post('/api/mock/enable')
    def enable_mock():
        state.init_mock()
        return jsonify({'ok': True})

    @app.post('/api/mock/disable')
    def disable_mock():
        state.mock = None
        state.device = None
        state.runner = None
        state.cabinet_info.status = ConnectionStatus.DISCONNECTED
        state.cabinet_info.port = ''
        state.cabinet_info.baudrate = 0
        state.fixture_info.status = ConnectionStatus.DISCONNECTED
        state.fixture_info.port = ''
        state.fixture_info.baudrate = 0
        state.emit('state', RunnerState().to_dict())
        # 通知前端清空槽位显示
        state.emit('slots_cleared', {'slot_count': 0})
        return jsonify({'ok': True})

    @app.post('/api/init')
    def init_devices():
        if not state.device:
            return jsonify({'ok': False, 'error': 'device not connected'}), 400
        try:
            resp = state.device.cabinet_send(hdlc.build_get_cabinet_info_frame(), timeout=5.0)
            model, slot_count = hdlc.parse_cabinet_info(resp.payload)
            if not (1 <= slot_count <= 128):
                return jsonify({'ok': False, 'error': f'invalid slot_count: {slot_count}'}), 400
            state.runner.initialize_slots(model, slot_count)
            state.refresh_all_slots()
            state.app_logger.log_operation('init', f'model={model} slots={slot_count}')
            return jsonify({'ok': True, 'model': model, 'slot_count': slot_count})
        except Exception as e:
            logger.exception('init failed')
            return jsonify({'ok': False, 'error': str(e)}), 500

    @app.post('/api/config')
    def set_config():
        data = request.get_json(force=True) or {}
        try:
            if 'target_test_count' in data:
                v = int(data['target_test_count'])
                if v < 1 or v > 100000:
                    return jsonify({'ok': False, 'error': 'target_test_count 取值范围 1-100000'}), 400
                state.config.target_test_count = v
            if 'max_retry' in data:
                v = int(data['max_retry'])
                if v < 0 or v > 10:
                    return jsonify({'ok': False, 'error': 'max_retry 取值范围 0-10'}), 400
                state.config.max_retry = v
            if 'slot_timeout_ms' in data:
                v = int(data['slot_timeout_ms'])
                if v < 1000 or v > 60000:
                    return jsonify({'ok': False, 'error': 'slot_timeout_ms 取值范围 1000-60000'}), 400
                state.config.slot_timeout_ms = v
            if 'phase_interval_ms' in data:
                v = int(data['phase_interval_ms'])
                if v < 0 or v > 60000:
                    return jsonify({'ok': False, 'error': 'phase_interval_ms 取值范围 0-60000'}), 400
                state.config.phase_interval_ms = v
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': '参数类型错误，必须为整数'}), 400
        if state.runner:
            state.runner._config = state.config
            state.runner._state.target_test_count = state.config.target_test_count
        state.app_logger.log_operation('config', json.dumps(data, ensure_ascii=False))
        state.emit('state', state.runner.state.to_dict() if state.runner else RunnerState().to_dict())
        return jsonify({'ok': True})

    @app.post('/api/start')
    def start_test():
        if not state.runner:
            return jsonify({'ok': False, 'error': 'not initialized'}), 400
        state.runner.start()
        return jsonify({'ok': True})

    @app.post('/api/pause')
    def pause_test():
        if state.runner:
            state.runner.pause()
        return jsonify({'ok': True})

    @app.post('/api/resume')
    def resume_test():
        if state.runner:
            state.runner.resume()
        return jsonify({'ok': True})

    @app.post('/api/stop')
    def stop_test():
        if state.runner:
            state.runner.stop()
        return jsonify({'ok': True})

    @app.post('/api/refresh')
    def refresh_slots():
        state.refresh_all_slots()
        return jsonify({'ok': True})

    @app.post('/api/clear-stats')
    def clear_stats():
        data = request.get_json(silent=True) or {}
        scope = data.get('scope', 'all')
        slot_no = data.get('slot_no')
        if scope == 'slot' and slot_no:
            state.stats_store.clear_slot(int(slot_no))
        else:
            state.stats_store.clear_all()
        state.app_logger.log_operation('clear_stats', f'scope={scope} slot={slot_no}')
        if state.runner:
            for i in range(1, state.runner.state.slot_count + 1):
                sv = state.runner._slot_views[i - 1]
                sv.stats = state.stats_store.get_slot(i)
                # 清零时同步重置槽位的测试状态，使顶部统计条（成功/失败/超时/等待）一并归零
                sv.test_state = int(TestState.NOT_TESTED)
                sv.test_direction = int(TestDirection.NONE)
                sv.app_result = 0
                sv.failure_reason = 0
                state.emit('slot', {'slot_no': i, **sv.to_dict()})
        return jsonify({'ok': True})

    @app.get('/api/comm-logs')
    def comm_logs():
        limit = int(request.args.get('limit', 100))
        with state._comm_log_lock:
            items = list(state._comm_log_deque)[-limit:]
        return jsonify({'logs': items})

    @app.post('/api/debug/send')
    def debug_send():
        data = request.get_json(force=True) or {}
        address = int(data.get('address', 0))
        command = int(data.get('command', 0))
        slot_no = data.get('slot_no')
        try:
            if slot_no is not None:
                slot_no = int(slot_no)
                if slot_no < 1 or slot_no > 128:
                    return jsonify({'ok': False, 'error': 'slot_no 取值范围 1-128'}), 400
        except (ValueError, TypeError):
            return jsonify({'ok': False, 'error': 'slot_no 必须为整数'}), 400

        if state.device is None:
            return jsonify({'ok': False, 'error': 'device not connected'}), 400

        try:
            if command == 0x01:
                frame = hdlc.build_get_cabinet_info_frame()
            elif command == 0x02:
                sn = slot_no if slot_no else 1
                frame = hdlc.build_get_slot_data_frame(sn)
            elif command == 0x03:
                if not slot_no:
                    return jsonify({'ok': False, 'error': '0x03 需要 slot_no'}), 400
                frame = hdlc.build_fixture_in_frame(slot_no)
            elif command == 0x04:
                if not slot_no:
                    return jsonify({'ok': False, 'error': '0x04 需要 slot_no'}), 400
                frame = hdlc.build_cabinet_out_frame(slot_no)
            else:
                return jsonify({'ok': False, 'error': f'不支持的命令: 0x{command:02X}'}), 400
        except Exception as e:
            return jsonify({'ok': False, 'error': f'帧构建失败: {e}'}), 400

        req_hex = frame.to_bytes().hex(' ').upper()
        try:
            if address == 0xA0:
                resp = state.device.cabinet_send(frame, timeout=5.0)
            elif address == 0xA1:
                resp = state.device.fixture_send(frame, timeout=5.0)
            else:
                return jsonify({'ok': False, 'error': f'不支持的地址: 0x{address:02X}'}), 400
        except Exception as e:
            state.app_logger.log_operation('debug_send_error', f'addr=0x{address:02X} cmd=0x{command:02X} slot={slot_no} err={e}')
            return jsonify({'ok': False, 'error': f'通信失败: {e}', 'request_hex': req_hex}), 500

        resp_hex = resp.to_bytes().hex(' ').upper()
        parsed = _parse_debug_response(command, resp.payload)
        state.app_logger.log_operation('debug_send', f'addr=0x{address:02X} cmd=0x{command:02X} slot={slot_no}')
        return jsonify({
            'ok': True,
            'request_hex': req_hex,
            'response_hex': resp_hex,
            'parsed': parsed,
        })

    @app.get('/events')
    def sse():
        def stream():
            q = state.register_sse()
            try:
                yield f'data: {json.dumps({"event": "hello", "data": {}})}\n\n'
                while True:
                    try:
                        payload = q.get(timeout=15)
                        yield f'data: {payload}\n\n'
                    except queue.Empty:
                        yield ': keepalive\n\n'
            finally:
                state.unregister_sse(q)
        return Response(stream(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        })

    @app.get('/')
    @app.get('/<path:path>')
    def serve_frontend(path: str = ''):
        if os.path.exists(DIST_DIR):
            full = os.path.join(DIST_DIR, path)
            if path and os.path.exists(full) and os.path.isfile(full):
                return send_from_directory(DIST_DIR, path)
            index = os.path.join(DIST_DIR, 'index.html')
            if os.path.exists(index):
                return send_from_directory(DIST_DIR, 'index.html')
        return jsonify({'ok': False, 'error': 'frontend not built'}), 404

    return app


if __name__ == '__main__':
    app = create_app()
    print(f'Backend on http://127.0.0.1:5001  (logs: {LOG_DIR})')
    app.run(host='127.0.0.1', port=5001, debug=False, threaded=True)
