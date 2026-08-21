from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import List, Optional
import json


class WarehouseState(IntEnum):
    UNKNOWN = 0x00
    IN_CABINET = 0x01
    OUT_CABINET = 0x02
    WAREHOUSING_IN = 0x03
    WAREHOUSING_OUT = 0x04
    ABNORMAL = 0x05


class TestDirection(IntEnum):
    NONE = 0
    IN_TEST = 1
    OUT_TEST = 2


class TestState(IntEnum):
    NOT_TESTED = 0x00
    WAITING = 0x01
    RUNNING = 0x02
    SUCCESS = 0x03
    FAILED = 0x04
    TIMEOUT = 0x05
    CANCELLED = 0x06
    UNDETERMINABLE = 0x07


class FlowState:
    IDLE = 'idle'
    INITIALIZING = 'initializing'
    READY = 'ready'
    PRECHECK = 'precheck'
    COMMAND_SENT = 'command_sent'
    WAIT_RESULT = 'wait_result'
    EVALUATING = 'evaluating'
    RECORDING = 'recording'
    NEXT_SLOT = 'next_slot'
    PAUSED = 'paused'
    STOPPING = 'stopping'
    COMPLETED = 'completed'
    FAULT = 'fault'


class DeviceType:
    CABINET = 'cabinet'
    FIXTURE = 'fixture'


class ConnectionStatus:
    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    ERROR = 'error'


@dataclass
class SlotData:
    slot_no: int
    warehouse_state: int = int(WarehouseState.UNKNOWN)
    id_ok: int = 0
    power_bank_id: List[int] = field(default_factory=lambda: [0] * 8)
    lock_button: int = 1
    tray_button: int = 1
    detect_button: int = 1
    test_result: int = 0
    error_code: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SlotStats:
    in_count: int = 0
    out_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    completed_test_count: int = 0
    round_count: int = 0
    out_success_count: int = 0
    out_failure_count: int = 0
    in_success_count: int = 0
    in_failure_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SlotView:
    data: SlotData
    stats: SlotStats
    test_direction: int = int(TestDirection.NONE)
    test_state: int = int(TestState.NOT_TESTED)
    app_result: int = 0
    failure_reason: int = 0
    initial_id: Optional[List[int]] = None
    initial_id_ok: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            **self.data.to_dict(),
            **self.stats.to_dict(),
            'test_direction': self.test_direction,
            'test_state': self.test_state,
            'app_result': self.app_result,
            'failure_reason': self.failure_reason,
            'initial_id': self.initial_id,
            'initial_id_ok': self.initial_id_ok,
        }


@dataclass
class RunnerState:
    target_test_count: int = 100
    current_round: int = 0
    current_phase: str = 'idle'
    current_slot: int = 0
    flow_state: str = FlowState.IDLE
    cabinet_model: str = ''
    slot_count: int = 0
    started_at: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeviceInfo:
    device_type: str
    port: str = ''
    baudrate: int = 115200
    status: str = ConnectionStatus.DISCONNECTED
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def format_power_bank_id(id_bytes: List[int]) -> str:
    if not id_bytes or len(id_bytes) != 8:
        return '--------'
    head = ''.join(
        chr(b) if 0x20 <= b <= 0x7e else '.'
        for b in id_bytes[:4]
    )
    tail = ''.join(f'{b:02X}' for b in id_bytes[4:8])
    return head + tail


def slot_stats_to_json(stats_list: List[SlotStats], cleared_at=None, cleared_by=None) -> str:
    return json.dumps({
        'slots': [s.to_dict() for s in stats_list],
        'last_cleared_at': cleared_at,
        'last_cleared_by': cleared_by,
    }, ensure_ascii=False, indent=2)
