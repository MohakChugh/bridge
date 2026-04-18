"""Tests for cron scheduler — matching, parsing, formatting."""

import os
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scheduler import cron_matches, _field_matches, next_cron_fire, format_schedule_list


class TestFieldMatches:
    def test_star(self):
        assert _field_matches("*", 5) is True

    def test_exact(self):
        assert _field_matches("5", 5) is True
        assert _field_matches("5", 6) is False

    def test_range(self):
        assert _field_matches("1-5", 3) is True
        assert _field_matches("1-5", 6) is False
        assert _field_matches("1-5", 1) is True
        assert _field_matches("1-5", 5) is True

    def test_list(self):
        assert _field_matches("1,3,5", 3) is True
        assert _field_matches("1,3,5", 4) is False

    def test_step(self):
        assert _field_matches("*/15", 0) is True
        assert _field_matches("*/15", 15) is True
        assert _field_matches("*/15", 30) is True
        assert _field_matches("*/15", 7) is False

    def test_range_step(self):
        assert _field_matches("1-10/2", 1) is True
        assert _field_matches("1-10/2", 3) is True
        assert _field_matches("1-10/2", 2) is False


class TestCronMatches:
    def test_every_minute(self):
        dt = datetime(2026, 4, 18, 9, 30)
        assert cron_matches("* * * * *", dt) is True

    def test_specific_time(self):
        dt = datetime(2026, 4, 18, 9, 0)
        assert cron_matches("0 9 * * *", dt) is True
        assert cron_matches("0 10 * * *", dt) is False

    def test_weekday(self):
        # April 18 2026 is Saturday (cron: 6)
        dt = datetime(2026, 4, 18, 9, 0)
        assert cron_matches("0 9 * * 6", dt) is True  # Saturday
        assert cron_matches("0 9 * * 1", dt) is False  # Monday

    def test_weekdays_mon_fri(self):
        # Monday April 20 2026
        dt = datetime(2026, 4, 20, 17, 0)
        assert cron_matches("0 17 * * 1-5", dt) is True

    def test_monthly(self):
        dt = datetime(2026, 4, 1, 0, 0)
        assert cron_matches("0 0 1 * *", dt) is True
        dt2 = datetime(2026, 4, 15, 0, 0)
        assert cron_matches("0 0 1 * *", dt2) is False

    def test_invalid_cron(self):
        assert cron_matches("bad cron", datetime.now()) is False
        assert cron_matches("* *", datetime.now()) is False

    def test_every_2_hours(self):
        dt = datetime(2026, 4, 18, 10, 0)
        assert cron_matches("0 */2 * * *", dt) is True
        dt2 = datetime(2026, 4, 18, 11, 0)
        assert cron_matches("0 */2 * * *", dt2) is False


class TestNextCronFire:
    def test_next_fire_daily_9am(self):
        after = datetime(2026, 4, 18, 8, 30)
        ts = next_cron_fire("0 9 * * *", after)
        dt = datetime.fromtimestamp(ts)
        assert dt.hour == 9
        assert dt.minute == 0

    def test_next_fire_past_today(self):
        after = datetime(2026, 4, 18, 10, 0)  # Already past 9am
        ts = next_cron_fire("0 9 * * *", after)
        dt = datetime.fromtimestamp(ts)
        assert dt.day == 19  # Tomorrow
        assert dt.hour == 9

    def test_next_fire_every_hour(self):
        after = datetime(2026, 4, 18, 10, 30)
        ts = next_cron_fire("0 * * * *", after)
        dt = datetime.fromtimestamp(ts)
        assert dt.hour == 11
        assert dt.minute == 0


class TestFormatScheduleList:
    def test_empty(self):
        assert "No active" in format_schedule_list([])

    def test_single_task(self):
        tasks = [{"human": "daily 9am", "prompt": "check pipeline", "next_fire": 1776600000, "status": "active"}]
        result = format_schedule_list(tasks)
        assert "1." in result
        assert "daily 9am" in result
        assert "check pipeline" in result

    def test_paused_task(self):
        tasks = [{"human": "every 2h", "prompt": "build", "next_fire": 0, "status": "paused"}]
        result = format_schedule_list(tasks)
        assert "[paused]" in result

    def test_multiple_tasks(self):
        tasks = [
            {"human": "daily 9am", "prompt": "check", "next_fire": 1776600000, "status": "active"},
            {"human": "weekly", "prompt": "report", "next_fire": 1776700000, "status": "active"},
        ]
        result = format_schedule_list(tasks)
        assert "1." in result
        assert "2." in result
