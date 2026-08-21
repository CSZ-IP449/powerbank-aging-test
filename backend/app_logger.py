from __future__ import annotations

import csv
import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _today() -> str:
    return datetime.now().strftime('%Y-%m-%d')


@dataclass
class RoundRecord:
    round_id: str
    started_at: str
    finished_at: Optional[str] = None
    cabinet_model: str = ''
    slot_count: int = 0
    target_test_count: int = 0
    phase: str = ''
    success_count: int = 0
    failure_count: int = 0
    timeout_count: int = 0
    skipped_count: int = 0
    final_result: str = ''


@dataclass
class SlotRecord:
    record_id: str
    round_id: Optional[str] = None
    slot_no: int = 0
    direction: str = ''
    started_at: str = ''
    finished_at: Optional[str] = None
    duration_ms: int = 0
    retry_count: int = 0
    data_before: str = ''
    data_after: str = ''
    cabinet_result: int = 0
    app_result: int = 0
    failure_reason: int = 0


@dataclass
class CommRecord:
    timestamp: str
    device: str
    direction: str
    raw_hex: str
    parsed: str
    slot_no: Optional[int] = None
    note: str = ''


@dataclass
class OperationRecord:
    timestamp: str
    action: str
    detail: str = ''


class _DailyCsvJsonWriter:
    def __init__(self, log_dir: str, prefix: str, fieldnames: list[str]):
        self._log_dir = log_dir
        self._prefix = prefix
        self._fieldnames = fieldnames
        self._lock = threading.Lock()
        self._current_date: Optional[str] = None
        self._csv_path: Optional[str] = None
        self._json_path: Optional[str] = None
        self._csv_initialized = False

    def _ensure_paths(self, date_str: str):
        if self._current_date == date_str and self._csv_path and self._json_path:
            return
        self._current_date = date_str
        self._csv_path = os.path.join(self._log_dir, f'{self._prefix}_{date_str}.csv')
        self._json_path = os.path.join(self._log_dir, f'{self._prefix}_{date_str}.json')
        self._csv_initialized = os.path.exists(self._csv_path)

    def write(self, record_dict: dict[str, Any]):
        date_str = _today()
        with self._lock:
            self._ensure_paths(date_str)
            write_header = not self._csv_initialized
            try:
                with open(self._csv_path, 'a', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=self._fieldnames, extrasaction='ignore')
                    if write_header:
                        writer.writeheader()
                        self._csv_initialized = True
                    writer.writerow({k: record_dict.get(k, '') for k in self._fieldnames})
                with open(self._json_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record_dict, ensure_ascii=False, default=str) + '\n')
            except (PermissionError, OSError) as e:
                logger.warning(f'log write failed: {e}')


class _DailyLineWriter:
    def __init__(self, log_dir: str, prefix: str):
        self._log_dir = log_dir
        self._prefix = prefix
        self._lock = threading.Lock()

    def write(self, line: str):
        date_str = _today()
        path = os.path.join(self._log_dir, f'{self._prefix}_{date_str}.log')
        with self._lock:
            try:
                with open(path, 'a', encoding='utf-8') as f:
                    f.write(f'[{_now_iso()}] {line}\n')
            except (PermissionError, OSError) as e:
                logger.warning(f'log line write failed: {e}')


class AppLogger:
    def __init__(self, log_dir: str):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except PermissionError:
            pass
        self._log_dir = log_dir
        self._rounds = _DailyCsvJsonWriter(
            log_dir, 'rounds',
            ['round_id', 'started_at', 'finished_at', 'cabinet_model', 'slot_count',
             'target_test_count', 'phase', 'success_count', 'failure_count',
             'timeout_count', 'skipped_count', 'final_result'],
        )
        self._slots = _DailyCsvJsonWriter(
            log_dir, 'slots',
            ['record_id', 'round_id', 'slot_no', 'direction', 'started_at', 'finished_at',
             'duration_ms', 'retry_count', 'data_before', 'data_after',
             'cabinet_result', 'app_result', 'failure_reason'],
        )
        self._comm = _DailyLineWriter(log_dir, 'comm')
        self._operations = _DailyLineWriter(log_dir, 'operations')

    def log_round(self, record: RoundRecord):
        self._rounds.write(asdict(record))

    def log_slot(self, record: SlotRecord):
        self._slots.write(asdict(record))

    def log_comm(self, record: CommRecord):
        line = f'{record.device:8s} {record.direction:4s} slot={record.slot_no} raw={record.raw_hex} parsed={record.parsed}'
        if record.note:
            line += f' note={record.note}'
        self._comm.write(line)

    def log_operation(self, action: str, detail: str = ''):
        self._operations.write(f'{action}: {detail}' if detail else action)

    def log_connection(self, device: str, status: str, detail: str = ''):
        self.log_operation(f'connection:{device}', f'{status} {detail}'.strip())
