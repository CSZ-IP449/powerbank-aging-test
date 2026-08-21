from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import serial
import serial.tools.list_ports

import hdlc

logger = logging.getLogger(__name__)


DEFAULT_BAUDRATE = 115200
READ_TIMEOUT_SEC = 0.2
DEFAULT_RESPONSE_TIMEOUT_SEC = 5.0


def list_available_ports() -> list[str]:
    return [p.device for p in serial.tools.list_ports.comports()]


@dataclass
class PendingRequest:
    expected_address: int
    event: threading.Event
    frame: Optional[hdlc.HdlcFrame] = None
    error: Optional[Exception] = None


class SerialBridge:
    def __init__(
        self,
        name: str,
        expected_address: int,
        on_status_change: Optional[Callable[[str, Optional[str]], None]] = None,
        on_comm_log: Optional[Callable[[str, str, str, Optional[int]], None]] = None,
    ):
        self.name = name
        self.expected_address = expected_address
        self._on_status_change = on_status_change
        self._on_comm_log = on_comm_log
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._read_thread: Optional[threading.Thread] = None
        self._running = False
        self._parser = hdlc.FrameStreamParser()
        self._pending: Optional[PendingRequest] = None
        self._pending_lock = threading.Lock()
        self._port: str = ''
        self._baudrate: int = DEFAULT_BAUDRATE
        self._status: str = 'disconnected'

    @property
    def status(self) -> str:
        return self._status

    @property
    def port(self) -> str:
        return self._port

    @property
    def baudrate(self) -> int:
        return self._baudrate

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, port: str, baudrate: int = DEFAULT_BAUDRATE) -> bool:
        self.disconnect()
        self._port = port
        self._baudrate = baudrate
        self._set_status('connecting', None)
        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=READ_TIMEOUT_SEC,
                write_timeout=1.0,
            )
        except Exception as e:
            logger.exception(f'[{self.name}] connect failed: {port}')
            self._set_status('error', str(e))
            return False

        self._running = True
        self._read_thread = threading.Thread(
            target=self._read_loop,
            name=f'{self.name}-reader',
            daemon=True,
        )
        self._read_thread.start()
        self._set_status('connected', None)
        logger.info(f'[{self.name}] connected: {port} @ {baudrate}')
        return True

    def disconnect(self):
        self._running = False
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=1.0)
        self._read_thread = None
        with self._pending_lock:
            if self._pending:
                self._pending.error = RuntimeError('disconnected')
                self._pending.event.set()
                self._pending = None
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._parser.reset()
        self._set_status('disconnected', None)

    def send_and_wait(
        self,
        frame: hdlc.HdlcFrame,
        timeout: float = DEFAULT_RESPONSE_TIMEOUT_SEC,
    ) -> hdlc.HdlcFrame:
        if not self.is_connected:
            raise RuntimeError(f'[{self.name}] not connected')

        raw = frame.to_bytes()
        if frame.address != self.expected_address:
            raise ValueError(
                f'[{self.name}] frame address {frame.address:02X} != expected {self.expected_address:02X}'
            )

        pending = PendingRequest(expected_address=self.expected_address, event=threading.Event())
        with self._pending_lock:
            if self._pending is not None:
                raise RuntimeError(f'[{self.name}] another request is in flight')
            self._pending = pending

        with self._lock:
            try:
                self._serial.write(raw)
                self._serial.flush()
            except Exception as e:
                with self._pending_lock:
                    self._pending = None
                self._set_status('error', f'write failed: {e}')
                raise

        self._emit_comm_log('send', raw, frame)

        ok = pending.event.wait(timeout=timeout)
        with self._pending_lock:
            self._pending = None

        if pending.error is not None:
            raise pending.error
        if not ok:
            raise TimeoutError(f'[{self.name}] no response within {timeout}s')
        if pending.frame is None:
            raise RuntimeError(f'[{self.name}] response event set but no frame')
        return pending.frame

    def _read_loop(self):
        while self._running and self._serial and self._serial.is_open:
            try:
                chunk = self._serial.read(64)
            except Exception as e:
                logger.warning(f'[{self.name}] read error: {e}')
                self._set_status('error', str(e))
                break
            if not chunk:
                continue
            try:
                for body in self._parser.feed(chunk):
                    self._handle_frame(body)
            except hdlc.ParseError as e:
                logger.warning(f'[{self.name}] parse error: {e}')
            except Exception as e:
                logger.exception(f'[{self.name}] reader unexpected error: {e}')

        if self._running:
            self._set_status('error', 'read loop exited')
        self._running = False

    def _handle_frame(self, body: bytes):
        try:
            unescaped = hdlc.unescape_bytes(body)
            if len(unescaped) < 4:
                logger.warning(f'[{self.name}] frame too short: {len(unescaped)} bytes')
                return
            frame = hdlc.parse_frame_body(unescaped)
        except hdlc.ParseError as e:
            logger.warning(f'[{self.name}] parse error: {e}, raw={body.hex().upper()}')
            return

        if frame.address != self.expected_address:
            logger.warning(
                f'[{self.name}] address mismatch: {frame.address:02X} != {self.expected_address:02X}'
            )
            return

        self._emit_comm_log('recv', frame.to_bytes(), frame)

        with self._pending_lock:
            if self._pending is not None:
                self._pending.frame = frame
                self._pending.event.set()

    def _set_status(self, status: str, error: Optional[str]):
        self._status = status
        if self._on_status_change:
            try:
                self._on_status_change(status, error)
            except Exception:
                logger.exception(f'[{self.name}] status callback error')

    def _emit_comm_log(
        self,
        direction: str,
        raw: bytes,
        frame: hdlc.HdlcFrame,
    ):
        if not self._on_comm_log:
            return
        try:
            self._on_comm_log(direction, raw.hex(' ').upper(), frame.to_hex(), None)
        except Exception:
            logger.exception(f'[{self.name}] comm log callback error')


class DualSerialManager:
    def __init__(
        self,
        on_cabinet_status: Optional[Callable[[str, Optional[str]], None]] = None,
        on_fixture_status: Optional[Callable[[str, Optional[str]], None]] = None,
        on_comm_log: Optional[Callable[[str, str, str, Optional[int]], None]] = None,
    ):
        self._on_comm_log = on_comm_log
        self.cabinet = SerialBridge(
            name='cabinet',
            expected_address=int(hdlc.Address.CABINET),
            on_status_change=on_cabinet_status,
            on_comm_log=self._make_log_hook('cabinet'),
        )
        self.fixture = SerialBridge(
            name='fixture',
            expected_address=int(hdlc.Address.FIXTURE),
            on_status_change=on_fixture_status,
            on_comm_log=self._make_log_hook('fixture'),
        )

    def _make_log_hook(self, device: str):
        def hook(direction: str, raw_hex: str, parsed_hex: str, slot_no):
            if self._on_comm_log:
                self._on_comm_log(device, direction, raw_hex, slot_no)
        return hook

    def connect_cabinet(self, port: str, baudrate: int = DEFAULT_BAUDRATE) -> bool:
        return self.cabinet.connect(port, baudrate)

    def connect_fixture(self, port: str, baudrate: int = DEFAULT_BAUDRATE) -> bool:
        return self.fixture.connect(port, baudrate)

    def disconnect_cabinet(self):
        self.cabinet.disconnect()

    def disconnect_fixture(self):
        self.fixture.disconnect()

    def disconnect_all(self):
        self.cabinet.disconnect()
        self.fixture.disconnect()

    def is_cabinet_connected(self) -> bool:
        return self.cabinet.is_connected

    def is_fixture_connected(self) -> bool:
        return self.fixture.is_connected

    def shutdown(self):
        self.disconnect_all()
