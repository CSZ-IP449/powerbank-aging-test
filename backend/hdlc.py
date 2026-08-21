from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Tuple
import struct


class Address(IntEnum):
    CABINET = 0xA0
    FIXTURE = 0xA1


class Command(IntEnum):
    GET_CABINET_INFO = 0x01
    GET_SLOT_DATA = 0x02
    FIXTURE_IN = 0x03
    CABINET_OUT = 0x04


CONTROL = 0x03
FLAG = 0x7E
ESCAPE = 0x7D

SLOT_DATA_SIZE = 16
CABINET_INFO_SIZE = 4
FIXTURE_RESPONSE_SIZE = 2
CABINET_OUT_RESPONSE_SIZE = 2


class ParseError(Exception):
    pass


class FrameTooShortError(ParseError):
    pass


class CRCMismatchError(ParseError):
    pass


class InvalidEscapeError(ParseError):
    pass


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def escape_bytes(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == FLAG:
            out.append(ESCAPE)
            out.append(0x5E)
        elif b == ESCAPE:
            out.append(ESCAPE)
            out.append(0x5D)
        else:
            out.append(b)
    return bytes(out)


def unescape_bytes(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == ESCAPE:
            if i + 1 >= n:
                raise InvalidEscapeError('dangling escape at end')
            nxt = data[i + 1]
            if nxt == 0x5E:
                out.append(FLAG)
            elif nxt == 0x5D:
                out.append(ESCAPE)
            else:
                raise InvalidEscapeError(f'illegal escape sequence: 7D {nxt:02X}')
            i += 2
        else:
            out.append(b)
            i += 1
    return bytes(out)


@dataclass
class HdlcFrame:
    address: int
    control: int
    command: int
    payload: bytes

    def to_bytes(self) -> bytes:
        body = bytes([self.address, self.control, self.command]) + self.payload
        crc = crc16_ccitt_false(body)
        body_with_crc = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
        escaped = escape_bytes(body_with_crc)
        return bytes([FLAG]) + escaped + bytes([FLAG])

    def to_hex(self) -> str:
        return self.to_bytes().hex(' ').upper()

    @property
    def expected_address(self) -> Address:
        return Address(self.address)


def build_frame(address: int, command: int, payload: bytes = b'') -> HdlcFrame:
    return HdlcFrame(address=address, control=CONTROL, command=command, payload=payload)


def parse_frame_body(body: bytes) -> HdlcFrame:
    if len(body) < 4:
        raise FrameTooShortError(f'frame body too short: {len(body)} bytes')
    addr = body[0]
    ctrl = body[1]
    cmd = body[2]
    payload = body[3:-2]
    crc_recv = body[-2] | (body[-1] << 8)
    crc_calc = crc16_ccitt_false(body[:-2])
    if crc_recv != crc_calc:
        raise CRCMismatchError(f'CRC mismatch: recv={crc_recv:04X} calc={crc_calc:04X}')
    return HdlcFrame(address=addr, control=ctrl, command=cmd, payload=payload)


class FrameStreamParser:
    def __init__(self):
        self._buffer = bytearray()
        self._in_frame = False

    def feed(self, data: bytes):
        for b in data:
            if b == FLAG:
                if self._in_frame and len(self._buffer) > 0:
                    yield bytes(self._buffer)
                self._buffer = bytearray()
                self._in_frame = True
            elif self._in_frame:
                self._buffer.append(b)

    def reset(self):
        self._buffer = bytearray()
        self._in_frame = False


def parse_cabinet_info(payload: bytes) -> Tuple[str, int]:
    if len(payload) != CABINET_INFO_SIZE:
        raise ParseError(f'cabinet info payload size {len(payload)} != {CABINET_INFO_SIZE}')
    model = payload[:3].decode('ascii', errors='replace')
    slot_count = payload[3]
    return model, slot_count


@dataclass
class SlotRaw:
    slot_no: int
    warehouse_state: int
    id_ok: int
    power_bank_id: bytes
    lock_button: int
    tray_button: int
    detect_button: int
    test_result: int
    error_code: int

    def to_dict(self) -> dict:
        return {
            'slot_no': self.slot_no,
            'warehouse_state': self.warehouse_state,
            'id_ok': self.id_ok,
            'power_bank_id': list(self.power_bank_id),
            'lock_button': self.lock_button,
            'tray_button': self.tray_button,
            'detect_button': self.detect_button,
            'test_result': self.test_result,
            'error_code': self.error_code,
        }


def parse_slot_data(payload: bytes) -> SlotRaw:
    if len(payload) != SLOT_DATA_SIZE:
        raise ParseError(f'slot data payload size {len(payload)} != {SLOT_DATA_SIZE}')
    slot_no = payload[0]
    warehouse_state = payload[1]
    id_ok = payload[2]
    power_bank_id = payload[3:11]
    lock_button = payload[11]
    tray_button = payload[12]
    detect_button = payload[13]
    test_result = payload[14]
    error_code = payload[15]
    return SlotRaw(
        slot_no=slot_no,
        warehouse_state=warehouse_state,
        id_ok=id_ok,
        power_bank_id=power_bank_id,
        lock_button=lock_button,
        tray_button=tray_button,
        detect_button=detect_button,
        test_result=test_result,
        error_code=error_code,
    )


@dataclass
class FixtureInResponse:
    slot_no: int
    status: int

    @property
    def accepted(self) -> bool:
        return self.status == 0x00


def parse_fixture_in_response(payload: bytes) -> FixtureInResponse:
    if len(payload) != FIXTURE_RESPONSE_SIZE:
        raise ParseError(f'fixture response payload size {len(payload)} != {FIXTURE_RESPONSE_SIZE}')
    return FixtureInResponse(slot_no=payload[0], status=payload[1])


@dataclass
class CabinetOutResponse:
    slot_no: int
    status: int

    @property
    def accepted(self) -> bool:
        return self.status == 0x00


def parse_cabinet_out_response(payload: bytes) -> CabinetOutResponse:
    if len(payload) != CABINET_OUT_RESPONSE_SIZE:
        raise ParseError(f'cabinet out response payload size {len(payload)} != {CABINET_OUT_RESPONSE_SIZE}')
    return CabinetOutResponse(slot_no=payload[0], status=payload[1])


def build_get_cabinet_info_frame() -> HdlcFrame:
    return build_frame(Address.CABINET, Command.GET_CABINET_INFO, b'')


def build_get_slot_data_frame(slot_no: int) -> HdlcFrame:
    if not (1 <= slot_no <= 128):
        raise ValueError(f'slot_no out of range: {slot_no}')
    return build_frame(Address.CABINET, Command.GET_SLOT_DATA, bytes([slot_no]))


def build_fixture_in_frame(slot_no: int) -> HdlcFrame:
    if not (1 <= slot_no <= 128):
        raise ValueError(f'slot_no out of range: {slot_no}')
    return build_frame(Address.FIXTURE, Command.FIXTURE_IN, bytes([slot_no]))


def build_cabinet_out_frame(slot_no: int) -> HdlcFrame:
    if not (1 <= slot_no <= 128):
        raise ValueError(f'slot_no out of range: {slot_no}')
    return build_frame(Address.CABINET, Command.CABINET_OUT, bytes([slot_no]))
