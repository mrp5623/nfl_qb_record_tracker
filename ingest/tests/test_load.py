"""Refresh guard tests.

The guard fails silently in the dangerous direction: if it ever reads a stored
value as "unchanged" when something moved, every scheduled run skips, nothing
errors, and the site quietly stops updating mid-season.
"""

import json

from ingest.load import WATCHED_RELEASES, changed_releases

CURRENT = {
    "stats_player": "2026-09-11 10:03:41 EDT",
    "snap_counts": "2026-09-11 12:10:07 EDT",
    "espn_data": "2026-09-11 09:07:13 EDT",
}


def test_nothing_changed_skips():
    assert changed_releases(json.dumps(CURRENT, sort_keys=True), CURRENT) == []


def test_only_the_release_that_moved_is_reported():
    before = {**CURRENT, "snap_counts": "2026-09-11 06:55:02 EDT"}
    assert changed_releases(json.dumps(before), CURRENT) == ["snap_counts"]


def test_no_previous_run_loads_everything():
    assert changed_releases(None, CURRENT) == list(WATCHED_RELEASES)


def test_legacy_bare_timestamp_loads_everything():
    """Runs before this guard stored one stats_player string, not an object.

    Even when that string equals today's stats_player build, snap counts and QBR
    were never tracked, so treating it as up to date would skip real updates.
    """
    legacy = CURRENT["stats_player"]
    assert changed_releases(legacy, CURRENT) == list(WATCHED_RELEASES)


def test_json_that_is_not_an_object_loads_everything():
    """A stored value that parses but is not a mapping must not read as unchanged."""
    assert changed_releases("5", CURRENT) == list(WATCHED_RELEASES)
    assert changed_releases('["stats_player"]', CURRENT) == list(WATCHED_RELEASES)
