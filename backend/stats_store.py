from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import List, Optional

from models import SlotStats


def _now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


class StatsStore:
    def __init__(self, data_dir: str, filename: str = 'stats.json'):
        try:
            os.makedirs(data_dir, exist_ok=True)
        except PermissionError:
            pass
        self._path = os.path.join(data_dir, filename)
        self._lock = threading.Lock()
        self._slots: List[SlotStats] = []
        self._last_cleared_at: Optional[str] = None
        self._last_cleared_by: Optional[str] = None
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._slots = [SlotStats(**s) for s in data.get('slots', [])]
            self._last_cleared_at = data.get('last_cleared_at')
            self._last_cleared_by = data.get('last_cleared_by')
        except Exception:
            self._slots = []
            self._last_cleared_at = None
            self._last_cleared_by = None

    def _save(self):
        try:
            tmp = self._path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except (PermissionError, OSError) as e:
            import logging
            logging.getLogger(__name__).warning(f'stats save failed: {e}')

    def to_dict(self) -> dict:
        return {
            'slots': [s.to_dict() for s in self._slots],
            'last_cleared_at': self._last_cleared_at,
            'last_cleared_by': self._last_cleared_by,
        }

    def ensure_slots(self, slot_count: int):
        with self._lock:
            if len(self._slots) < slot_count:
                self._slots.extend(
                    SlotStats() for _ in range(slot_count - len(self._slots))
                )
            elif len(self._slots) > slot_count:
                self._slots = self._slots[:slot_count]
            self._save()

    def get_slot(self, slot_no: int) -> SlotStats:
        # slot_no is 1-based
        with self._lock:
            return self._slots[slot_no - 1]

    def get_all(self) -> List[SlotStats]:
        with self._lock:
            return list(self._slots)

    def increment_in(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].in_count += delta
            self._save()

    def increment_out(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].out_count += delta
            self._save()

    def increment_success(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].success_count += delta
            self._save()

    def increment_failure(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].failure_count += delta
            self._save()

    def increment_out_success(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].out_success_count += delta
            self._save()

    def increment_out_failure(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].out_failure_count += delta
            self._save()

    def increment_in_success(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].in_success_count += delta
            self._save()

    def increment_in_failure(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].in_failure_count += delta
            self._save()

    def increment_completed(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].completed_test_count += delta
            self._save()

    def increment_round(self, slot_no: int, delta: int = 1):
        with self._lock:
            self._slots[slot_no - 1].round_count += delta
            self._save()

    def set_completed(self, slot_no: int, value: int):
        with self._lock:
            self._slots[slot_no - 1].completed_test_count = value
            self._save()

    def clear_all(self, cleared_by: Optional[str] = None):
        with self._lock:
            for s in self._slots:
                s.in_count = 0
                s.out_count = 0
                s.success_count = 0
                s.failure_count = 0
                s.completed_test_count = 0
                s.round_count = 0
                s.out_success_count = 0
                s.out_failure_count = 0
                s.in_success_count = 0
                s.in_failure_count = 0
            self._last_cleared_at = _now_iso()
            self._last_cleared_by = cleared_by
            self._save()

    def clear_slot(self, slot_no: int, cleared_by: Optional[str] = None):
        with self._lock:
            s = self._slots[slot_no - 1]
            s.in_count = 0
            s.out_count = 0
            s.success_count = 0
            s.failure_count = 0
            s.completed_test_count = 0
            s.round_count = 0
            s.out_success_count = 0
            s.out_failure_count = 0
            s.in_success_count = 0
            s.in_failure_count = 0
            self._last_cleared_at = _now_iso()
            self._last_cleared_by = cleared_by
            self._save()
