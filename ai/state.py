"""Shared state between the detector and the Telegram bot (armed/schedule/last event).

Stored as ai/state.json. Writes are atomic so both processes can touch it safely.
"""

import datetime
import json
import os
import pathlib

STATE_FILE = pathlib.Path(__file__).with_name("state.json")
DEFAULT = {
    "armed": True,
    "from": "00:00",          # alerts only fire within this window...
    "to": "23:59",            # ...(and only when armed)
    "last_event": "",         # path to last detection photo
    "last_event_ts": "",      # human timestamp of last detection
    "last_person_ts": 0,      # epoch of last confirmed person (for audio+video fusion)
}


def load() -> dict:
    try:
        return {**DEFAULT, **json.loads(STATE_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULT)


def save(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def update(**changes) -> dict:
    state = load()
    state.update(changes)
    save(state)
    return state


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _in_window(now: datetime.datetime, frm: str, to: str) -> bool:
    cur = now.hour * 60 + now.minute
    a, b = _minutes(frm), _minutes(to)
    if a <= b:
        return a <= cur <= b
    return cur >= a or cur <= b  # window crosses midnight (e.g. 20:00–07:00)


def should_alert(now: datetime.datetime | None = None) -> bool:
    """True if alerts are enabled right now (armed and within the time window)."""
    state = load()
    if not state.get("armed", True):
        return False
    now = now or datetime.datetime.now()
    return _in_window(now, state.get("from", "00:00"), state.get("to", "23:59"))
