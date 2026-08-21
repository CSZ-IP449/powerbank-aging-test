from __future__ import annotations

import logging
import threading
import time
import random
from typing import Optional

import hdlc
from models import WarehouseState

logger = logging.getLogger(__name__)


MOCK_CABINET_MODEL = 'S06'
MOCK_SLOT_COUNT = 6
MOCK_SLOT_DELAY_OUT_SEC = 1.5
MOCK_SLOT_DELAY_IN_SEC = 1.5
MOCK_FIXTURE_DELAY_SEC = 0.8


def _make_initial_slot(slot_no: int) -> dict:
    return {
        'slot_no': slot_no,
        'warehouse_state': int(WarehouseState.IN_CABINET),
        'id_ok': 1,
        'power_bank_id': [
            0x41, 0x42, 0x43, 0x44,
            (slot_no & 0xFF), 0x04,
            0xAB, 0xCD,
        ],
        'lock_button': 0,
        'tray_button': 0,
        'detect_button': 0,
        'test_result': 0,
        'error_code': 0,
    }


class MockBackend:
    """与 SerialBridge.send_and_wait 接口兼容的内存模拟设备"""

    def __init__(self):
        self.name = 'mock'
        self._port = 'MOCK'
        self._baudrate = 115200
        self._status = 'connected'
        self._slot_count = MOCK_SLOT_COUNT
        self._cabinet_model = MOCK_CABINET_MODEL
        self._slots: dict[int, dict] = {}
        self._protected_fields: dict[int, set] = {}
        self._lock = threading.Lock()
        self._reset_slots()
        self._on_comm_log = None

    def set_comm_log_hook(self, hook):
        self._on_comm_log = hook

    @property
    def is_connected(self) -> bool:
        return True

    @property
    def status(self) -> str:
        return self._status

    @property
    def port(self) -> str:
        return self._port

    @property
    def baudrate(self) -> int:
        return self._baudrate

    def _reset_slots(self):
        with self._lock:
            self._slots = {i: _make_initial_slot(i) for i in range(1, self._slot_count + 1)}

    def reset(self):
        self._reset_slots()
        self._protected_fields.clear()
        logger.info('[mock] slots reset')

    def set_slot_count(self, count: int):
        if not (1 <= count <= 128):
            raise ValueError(f'slot count out of range: {count}')
        self._slot_count = count
        self._protected_fields.clear()
        self._reset_slots()

    def connect(self, port: str = 'MOCK', baudrate: int = 115200) -> bool:
        self._port = port
        self._baudrate = baudrate
        self._status = 'connected'
        return True

    def disconnect(self):
        self._status = 'disconnected'

    def send_and_wait(
        self,
        frame: hdlc.HdlcFrame,
        timeout: float = 5.0,
    ) -> hdlc.HdlcFrame:
        del timeout
        if self._on_comm_log:
            try:
                self._on_comm_log('send', frame.to_bytes().hex(' ').upper(), frame.to_hex(), None)
            except Exception:
                pass

        time.sleep(0.05)

        if frame.address == int(hdlc.Address.CABINET):
            resp = self._handle_cabinet(frame)
        elif frame.address == int(hdlc.Address.FIXTURE):
            resp = self._handle_fixture(frame)
        else:
            raise ValueError(f'unknown address: {frame.address:02X}')

        if self._on_comm_log:
            try:
                self._on_comm_log('recv', resp.to_bytes().hex(' ').upper(), resp.to_hex(), None)
            except Exception:
                pass
        return resp

    def _handle_cabinet(self, frame: hdlc.HdlcFrame) -> hdlc.HdlcFrame:
        cmd = frame.command
        if cmd == int(hdlc.Command.GET_CABINET_INFO):
            payload = self._cabinet_model.encode('ascii')[:3].ljust(3, b' ') + bytes([self._slot_count])
            return hdlc.build_frame(int(hdlc.Address.CABINET), int(hdlc.Command.GET_CABINET_INFO), payload)

        if cmd == int(hdlc.Command.GET_SLOT_DATA):
            if len(frame.payload) != 1:
                raise ValueError('GET_SLOT_DATA payload size != 1')
            slot_no = frame.payload[0]
            return self._build_slot_response(slot_no)

        if cmd == int(hdlc.Command.CABINET_OUT):
            if len(frame.payload) != 1:
                raise ValueError('CABINET_OUT payload size != 1')
            slot_no = frame.payload[0]
            return self._handle_cabinet_out(slot_no)

        raise ValueError(f'unknown cabinet command: {cmd:02X}')

    def _handle_fixture(self, frame: hdlc.HdlcFrame) -> hdlc.HdlcFrame:
        cmd = frame.command
        if cmd == int(hdlc.Command.FIXTURE_IN):
            if len(frame.payload) != 1:
                raise ValueError('FIXTURE_IN payload size != 1')
            slot_no = frame.payload[0]
            return self._handle_fixture_in(slot_no)

        raise ValueError(f'unknown fixture command: {cmd:02X}')

    def _build_slot_response(self, slot_no: int) -> hdlc.HdlcFrame:
        with self._lock:
            slot = self._slots.get(slot_no)
            if slot is None:
                slot = {
                    'slot_no': slot_no,
                    'warehouse_state': int(WarehouseState.UNKNOWN),
                    'id_ok': 0,
                    'power_bank_id': [0] * 8,
                    'lock_button': 1,
                    'tray_button': 1,
                    'detect_button': 1,
                    'test_result': 0,
                    'error_code': 0,
                }
            payload = bytes([
                slot['slot_no'] & 0xFF,
                slot['warehouse_state'] & 0xFF,
                slot['id_ok'] & 0xFF,
            ]) + bytes(slot['power_bank_id']) + bytes([
                slot['lock_button'] & 0xFF,
                slot['tray_button'] & 0xFF,
                slot['detect_button'] & 0xFF,
                slot['test_result'] & 0xFF,
                slot['error_code'] & 0xFF,
            ])
        return hdlc.build_frame(int(hdlc.Address.CABINET), int(hdlc.Command.GET_SLOT_DATA), payload)

    def _handle_cabinet_out(self, slot_no: int) -> hdlc.HdlcFrame:
        with self._lock:
            slot = self._slots.get(slot_no)
            if slot is None:
                payload = bytes([slot_no & 0xFF, 0x04])
                return hdlc.build_frame(int(hdlc.Address.CABINET), int(hdlc.Command.CABINET_OUT), payload)
            protected = self._protected_fields.get(slot_no, set())
            # 出仓命令会修改按键状态，清除这些字段的保护
            protected.discard('lock_button')
            protected.discard('tray_button')
            protected.discard('detect_button')
            slot['warehouse_state'] = int(WarehouseState.WAREHOUSING_OUT)
            slot['lock_button'] = 1
            slot['tray_button'] = 1
            slot['detect_button'] = 1
            slot['test_result'] = 0

        def finalize():
            time.sleep(MOCK_SLOT_DELAY_OUT_SEC)
            with self._lock:
                slot = self._slots.get(slot_no)
                if slot is None:
                    return
                protected = self._protected_fields.get(slot_no, set())
                slot['warehouse_state'] = int(WarehouseState.OUT_CABINET)
                if 'id_ok' not in protected:
                    slot['id_ok'] = 0
                if 'lock_button' not in protected:
                    slot['lock_button'] = 0
                if 'tray_button' not in protected:
                    slot['tray_button'] = 1
                if 'detect_button' not in protected:
                    slot['detect_button'] = 1
                slot['test_result'] = 1

        threading.Thread(target=finalize, daemon=True).start()
        payload = bytes([slot_no & 0xFF, 0x00])
        return hdlc.build_frame(int(hdlc.Address.CABINET), int(hdlc.Command.CABINET_OUT), payload)

    def _handle_fixture_in(self, slot_no: int) -> hdlc.HdlcFrame:
        with self._lock:
            slot = self._slots.get(slot_no)
            if slot is None:
                payload = bytes([slot_no, 0x01])
                return hdlc.build_frame(int(hdlc.Address.FIXTURE), int(hdlc.Command.FIXTURE_IN), payload)
            # 进仓命令会修改按键状态，清除这些字段的保护
            protected = self._protected_fields.get(slot_no, set())
            protected.discard('lock_button')
            protected.discard('tray_button')
            protected.discard('detect_button')

        def finalize():
            time.sleep(MOCK_FIXTURE_DELAY_SEC)
            with self._lock:
                slot = self._slots.get(slot_no)
                if slot is None:
                    return
                protected = self._protected_fields.get(slot_no, set())
                slot['warehouse_state'] = int(WarehouseState.WAREHOUSING_IN)
            time.sleep(MOCK_SLOT_DELAY_IN_SEC - MOCK_FIXTURE_DELAY_SEC)
            with self._lock:
                slot = self._slots.get(slot_no)
                if slot is None:
                    return
                protected = self._protected_fields.get(slot_no, set())
                slot['warehouse_state'] = int(WarehouseState.IN_CABINET)
                if 'id_ok' not in protected:
                    slot['id_ok'] = 1
                slot['lock_button'] = 0
                slot['tray_button'] = 0
                slot['detect_button'] = 0
                slot['test_result'] = 1

        threading.Thread(target=finalize, daemon=True).start()
        payload = bytes([slot_no & 0xFF, 0x00])
        return hdlc.build_frame(int(hdlc.Address.FIXTURE), int(hdlc.Command.FIXTURE_IN), payload)

    def get_slot_snapshot(self, slot_no: int) -> Optional[dict]:
        with self._lock:
            slot = self._slots.get(slot_no)
            return dict(slot) if slot else None

    def set_slot_field(self, slot_no: int, field: str, value):
        """直接修改指定槽位的字段（测试用）。修改后字段不会被命令执行覆盖。"""
        with self._lock:
            slot = self._slots.get(slot_no)
            if slot is not None:
                slot[field] = value
            protected = self._protected_fields.setdefault(slot_no, set())
            protected.add(field)

    def clear_protected_field(self, slot_no: int, field: str):
        """取消指定槽位指定字段的保护，允许后续命令修改该字段。"""
        with self._lock:
            protected = self._protected_fields.get(slot_no)
            if protected and field in protected:
                protected.discard(field)
