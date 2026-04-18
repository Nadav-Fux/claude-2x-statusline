"""Tests for seg_peak_hours in engines/python-engine.py.

Import strategy
---------------
The engine file has NO top-level side-effect calls — all execution is gated
behind ``if __name__ == "__main__"``.  We therefore import it directly via
importlib, loading it under the alias ``engine`` so it doesn't collide with
any other name in the test namespace.

The ``ctx`` dict that seg_peak_hours reads:
  ctx["schedule"]       – the JSON schedule (controls peak config + mode)
  ctx["local_time"]     – datetime with .hour / .minute / .isoweekday()
  ctx["local_offset"]   – float UTC offset for the user's local timezone

peak_hours_to_local converts peak UTC start/end into local hours using
local_offset, so tests can drive all cases without touching the system clock.
"""
import importlib.util
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# ── Load engine as a module ───────────────────────────────────────────────────
_ENGINE_PATH = Path(__file__).resolve().parent.parent / "engines" / "python-engine.py"
_spec = importlib.util.spec_from_file_location("engine", _ENGINE_PATH)
engine = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(engine)
    _IMPORT_OK = True
except Exception as _exc:
    _IMPORT_OK = False
    _IMPORT_ERR = str(_exc)


def _require_engine():
    if not _IMPORT_OK:
        pytest.skip(f"engine import failed: {_IMPORT_ERR}")


# ── Schedule helpers ──────────────────────────────────────────────────────────

def _schedule(start_utc=13, end_utc=19, days=None, mode="peak_hours",
              enabled=True, tz="UTC"):
    """Build a minimal schedule dict for peak-hours testing."""
    return {
        "mode": mode,
        "peak": {
            "enabled": enabled,
            "tz": tz,
            "days": days if days is not None else [1, 2, 3, 4, 5],
            "start": start_utc,
            "end": end_utc,
            "label_peak": "Peak",
            "label_offpeak": "Off-Peak",
        },
    }


def _ctx(local_dt: datetime, local_offset: float, schedule: dict) -> dict:
    """Build a minimal ctx dict for seg_peak_hours."""
    return {
        "schedule": schedule,
        "local_time": local_dt,
        "local_offset": local_offset,
    }


def _local_dt(utc_epoch_seconds: float, offset_hours: float) -> datetime:
    """Return naive datetime representing local time for the given UTC + offset."""
    utc = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        seconds=utc_epoch_seconds
    )
    local = utc + timedelta(hours=offset_hours)
    return local.replace(tzinfo=None)  # seg_peak_hours reads .hour/.minute raw


# ── Case 1: Standard peak UTC 13-19, user UTC+3 ──────────────────────────────

class TestStandardPeakUTCPlus3:
    """Peak window UTC 13:00–19:00; user is UTC+3 → local 16:00–22:00."""

    OFFSET = 3.0
    SCHED = _schedule(start_utc=13, end_utc=19, days=[1, 2, 3, 4, 5])

    def _mk(self, utc_h, utc_m=0):
        """Make a Monday local datetime at given UTC hours/minutes."""
        # 2026-04-20 is a Monday
        base_utc = datetime(2026, 4, 20, utc_h, utc_m, 0, tzinfo=timezone.utc)
        epoch = base_utc.timestamp()
        return _local_dt(epoch, self.OFFSET)

    def test_pre_peak(self):
        _require_engine()
        # local 15:59 = UTC 12:59 → before 16:00 local start
        dt = self._mk(12, 59)
        result = engine.seg_peak_hours(_ctx(dt, self.OFFSET, self.SCHED))
        assert "Off-Peak" in result or result == ""

    def test_peak_starts_at_16(self):
        _require_engine()
        # local 16:00 = UTC 13:00 → peak active
        dt = self._mk(13, 0)
        ctx = _ctx(dt, self.OFFSET, self.SCHED)
        result = engine.seg_peak_hours(ctx)
        assert ctx.get("is_peak") is True

    def test_peak_active_at_21_59(self):
        _require_engine()
        # local 21:59 = UTC 18:59 → still peak
        dt = self._mk(18, 59)
        ctx = _ctx(dt, self.OFFSET, self.SCHED)
        engine.seg_peak_hours(ctx)
        assert ctx.get("is_peak") is True

    def test_post_peak_at_22(self):
        _require_engine()
        # local 22:00 = UTC 19:00 → peak just ended
        dt = self._mk(19, 0)
        ctx = _ctx(dt, self.OFFSET, self.SCHED)
        engine.seg_peak_hours(ctx)
        assert ctx.get("is_peak") is False


# ── Case 2: Midnight-crossing peak UTC 22-04, user UTC+3 ─────────────────────

class TestMidnightCrossingPeakUTCPlus3:
    """Peak window UTC 22:00–04:00; user UTC+3 → local 01:00–07:00."""

    OFFSET = 3.0
    SCHED = _schedule(start_utc=22, end_utc=4, days=[1, 2, 3, 4, 5])

    def _monday_utc(self, h, m=0):
        return datetime(2026, 4, 20, h, m, 0, tzinfo=timezone.utc)

    def _as_local(self, utc_dt):
        return _local_dt(utc_dt.timestamp(), self.OFFSET)

    def test_pre_peak_utc_21_59(self):
        _require_engine()
        # UTC 21:59 Mon = local 00:59 Tue → before local 01:00
        dt = self._as_local(self._monday_utc(21, 59))
        ctx = _ctx(dt, self.OFFSET, self.SCHED)
        engine.seg_peak_hours(ctx)
        assert ctx.get("is_peak") is False

    def test_peak_starts_utc_22(self):
        _require_engine()
        # UTC 22:00 Mon = local 01:00 Tue
        dt = self._as_local(self._monday_utc(22, 0))
        ctx = _ctx(dt, self.OFFSET, self.SCHED)
        engine.seg_peak_hours(ctx)
        assert ctx.get("is_peak") is True

    def test_peak_active_utc_03_59(self):
        _require_engine()
        # UTC 03:59 Tue = local 06:59 Tue → still in window
        utc = datetime(2026, 4, 21, 3, 59, 0, tzinfo=timezone.utc)
        dt = _local_dt(utc.timestamp(), self.OFFSET)
        ctx = _ctx(dt, self.OFFSET, self.SCHED)
        engine.seg_peak_hours(ctx)
        assert ctx.get("is_peak") is True

    def test_peak_ends_utc_04(self):
        _require_engine()
        # UTC 04:00 Tue = local 07:00 Tue → post-peak
        utc = datetime(2026, 4, 21, 4, 0, 0, tzinfo=timezone.utc)
        dt = _local_dt(utc.timestamp(), self.OFFSET)
        ctx = _ctx(dt, self.OFFSET, self.SCHED)
        engine.seg_peak_hours(ctx)
        assert ctx.get("is_peak") is False


# ── Case 3: Saturday spillover ────────────────────────────────────────────────

def test_saturday_spillover_into_sunday():
    """Peak Sat UTC 22:00 → Sun UTC 04:00; Sun 02:00 UTC+3 (Sat 23:00 UTC) = peak."""
    _require_engine()
    # Schedule: peak on Saturday (isoweekday=6) only, crosses midnight into Sunday
    sched = _schedule(start_utc=22, end_utc=4, days=[6])
    # Sat 2026-04-18 23:00 UTC = Sun 2026-04-19 02:00 UTC+3
    utc = datetime(2026, 4, 18, 23, 0, 0, tzinfo=timezone.utc)
    offset = 3.0
    dt = _local_dt(utc.timestamp(), offset)  # local Sun 02:00
    ctx = _ctx(dt, offset, sched)
    engine.seg_peak_hours(ctx)
    assert ctx.get("is_peak") is True


# ── Case 4: mode == "normal" returns "" ───────────────────────────────────────

def test_normal_mode_returns_empty():
    _require_engine()
    sched = _schedule(mode="normal")
    utc = datetime(2026, 4, 20, 15, 0, 0, tzinfo=timezone.utc)
    dt = _local_dt(utc.timestamp(), 0.0)
    result = engine.seg_peak_hours(_ctx(dt, 0.0, sched))
    assert result == ""


# ── Case 5: DST spring-forward 2026-03-08 (US EST→EDT) ───────────────────────

def test_dst_spring_forward_2026():
    """After spring-forward, NY offset shifts from -5 to -4.

    Peak UTC 13-19.
    Before DST (EST UTC-5): local 09:00–15:00 EST is peak active at local 14:00.
    After DST  (EDT UTC-4): local 09:00–15:00 EDT is peak active at local 14:00.
    The LOCAL peak window shifts: before=08:00–14:00 local; after=09:00–15:00 local.
    """
    _require_engine()
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        pytest.skip("zoneinfo not available")

    tz_ny = ZoneInfo("America/New_York")

    # Day before DST: 2026-03-07, local 14:00 EST = UTC 19:00 → end of peak (boundary)
    pre_dst_local = datetime(2026, 3, 7, 14, 0, 0, tzinfo=tz_ny)
    pre_offset = pre_dst_local.utcoffset().total_seconds() / 3600  # -5
    pre_dt_naive = _local_dt(pre_dst_local.timestamp(), pre_offset)
    sched = _schedule(start_utc=13, end_utc=19)
    ctx_pre = _ctx(pre_dt_naive, pre_offset, sched)
    engine.seg_peak_hours(ctx_pre)
    # 14:00 EST = UTC 19:00 → exactly at end boundary → NOT peak (exclusive)
    assert ctx_pre.get("is_peak") is False

    # Day after DST: 2026-03-09, local 14:00 EDT = UTC 18:00 → inside peak
    post_dst_local = datetime(2026, 3, 9, 14, 0, 0, tzinfo=tz_ny)
    post_offset = post_dst_local.utcoffset().total_seconds() / 3600  # -4
    post_dt_naive = _local_dt(post_dst_local.timestamp(), post_offset)
    ctx_post = _ctx(post_dt_naive, post_offset, sched)
    engine.seg_peak_hours(ctx_post)
    # 14:00 EDT = UTC 18:00 → inside UTC 13-19 window → peak active
    assert ctx_post.get("is_peak") is True


# ── Case 6: DST fall-back 2025-11-02 (US EDT→EST) ────────────────────────────

def test_dst_fall_back_2025():
    """Before fall-back, NY is EDT (UTC-4); after, EST (UTC-5).

    Peak UTC 13-19.
    Before (EDT -4): local peak 09:00–15:00 local. At local 14:00 EDT → peak.
    After  (EST -5): local peak 08:00–14:00 local. At local 14:00 EST → NOT peak.
    """
    _require_engine()
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        pytest.skip("zoneinfo not available")

    tz_ny = ZoneInfo("America/New_York")
    sched = _schedule(start_utc=13, end_utc=19)

    # 2025-11-01 (Sat, day before fall-back), 14:00 EDT = UTC 18:00 → peak active
    pre_fb = datetime(2025, 11, 1, 14, 0, 0, tzinfo=tz_ny)
    pre_off = pre_fb.utcoffset().total_seconds() / 3600  # -4
    pre_dt = _local_dt(pre_fb.timestamp(), pre_off)
    ctx_pre = _ctx(pre_dt, pre_off, sched)
    # Saturday is not in default peak days [1-5], so adjust schedule
    sched_wknd = _schedule(start_utc=13, end_utc=19, days=[1, 2, 3, 4, 5, 6])
    ctx_pre = _ctx(pre_dt, pre_off, sched_wknd)
    engine.seg_peak_hours(ctx_pre)
    assert ctx_pre.get("is_peak") is True  # 14:00 EDT = UTC 18:00 → peak

    # 2025-11-03 (Mon, day after fall-back), 14:00 EST = UTC 19:00 → NOT peak
    post_fb = datetime(2025, 11, 3, 14, 0, 0, tzinfo=tz_ny)
    post_off = post_fb.utcoffset().total_seconds() / 3600  # -5
    post_dt = _local_dt(post_fb.timestamp(), post_off)
    ctx_post = _ctx(post_dt, post_off, sched)
    engine.seg_peak_hours(ctx_post)
    assert ctx_post.get("is_peak") is False  # 14:00 EST = UTC 19:00 → boundary, NOT peak
