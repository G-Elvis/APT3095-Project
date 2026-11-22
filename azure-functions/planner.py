import json
import re
from pathlib import Path

SLOTS = json.loads(Path(__file__).with_name("slots.json").read_text(encoding="utf-8"))
FILTERS = {"pattern": "pattern", "start": "classStart", "end": "classEnd"}


def lookup(query):
    period = query.get("period")
    if period not in ("mid", "final"):
        return (400, {"error": "period must be mid or final"})

    candidates = [slot for slot in SLOTS if slot["period"] == period]
    if not FILTERS.keys() & query.keys():
        return (200, candidates)

    if not all(query.get(key) for key in FILTERS):
        return (400, {"error": "Provide pattern, start and end together"})
    for key in ("start", "end"):
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", query[key]):
            return (400, {"error": "Use 24-hour HH:MM times"})
    for slot in candidates:
        if all(query[key] == slot[field] for key, field in FILTERS.items()):
            return (200, slot)
    return (404, {"error": "No matching exam slot in the loaded timetable"})
