import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from azure.core import MatchConditions
from azure.core.exceptions import AzureError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import TableClient, UpdateMode

from saved_exams import SLOTS_BY_ID, reply, session_from


def open_table():
    return TableClient.from_connection_string(
        os.environ["AzureWebJobsStorage"], table_name="SavedExams"
    )


MAX_REMINDERS = 20


def utc_text(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_reminders(row):
    if "remindersJson" in row:
        return json.loads(row["remindersJson"])
    if row.get("reminderDueAt"):
        return [{
            "reminderId": row["RowKey"],
            "dueAt": row["reminderDueAt"],
            "status": row["reminderStatus"],
            "publishedAt": row.get("reminderPublishedAt", ""),
        }]
    return []


def write_reminders(table, row, reminders):
    next_due = min((r["dueAt"] for r in reminders if r["status"] == "pending"), default="")
    table.update_entity(
        {"PartitionKey": row["PartitionKey"], "RowKey": row["RowKey"],
         "remindersJson": json.dumps(reminders), "nextReminderDueAt": next_due,
         "reminderStatus": ""},
        mode=UpdateMode.MERGE, etag=row.metadata["etag"],
        match_condition=MatchConditions.IfNotModified,
    )


def set_reminder(req):
    session, is_new = session_from(req)
    saved_id = req.route_params["id"]
    if is_new or not re.fullmatch(r"[0-9a-f]{32}", saved_id):
        return reply(404, {"error": "Saved exam not found"})
    if req.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        return reply(415, {"error": "Use application/json"})
    try:
        body = req.get_json()
    except ValueError:
        return reply(400, {"error": "Invalid JSON"})
    if not isinstance(body, dict):
        return reply(400, {"error": "Expected a JSON object"})
    try:
        with open_table() as table:
            row = table.get_entity(session, saved_id)
            reminders = read_reminders(row)
            if body == {"list": True}:
                return reply(200, reminders)
            if "remove" in body:
                remaining = [r for r in reminders if not (
                    r["reminderId"] == body["remove"] and r["status"] == "pending"
                )]
                if remaining != reminders:
                    write_reminders(table, row, remaining)
                return reply(200, remaining)
            offsets = body.get("minutesBefore")
            single = not isinstance(offsets, list)
            if single:
                offsets = [offsets]
            if not offsets or len(offsets) > MAX_REMINDERS or any(
                type(value) is not int or not 1 <= value <= 525600 for value in offsets
            ):
                return reply(400, {"error": "Choose 1–20 intervals between 1 and 525600 minutes."})
            slot = SLOTS_BY_ID.get(row["slotId"])
            if slot is None:
                return reply(404, {"error": "Exam slot not found"})
            start = datetime.fromisoformat(f'{slot["examDate"]}T{slot["examStart"]}')
            start = start.replace(tzinfo=ZoneInfo(slot["timeZone"])).astimezone(timezone.utc)
            now = datetime.now(timezone.utc)
            by_due = {r["dueAt"]: r for r in reminders}
            requested = []
            for minutes in dict.fromkeys(offsets):
                due = start - timedelta(minutes=minutes)
                due_at = utc_text(due)
                if due_at not in by_due:
                    if due <= now:
                        return reply(400, {"error": "One or more reminder times have already passed."})
                    by_due[due_at] = {"reminderId": f"{saved_id}-{minutes}", "dueAt": due_at,
                                      "status": "pending", "minutesBefore": minutes}
                requested.append(by_due[due_at])
            if len(by_due) > MAX_REMINDERS:
                return reply(400, {"error": "Each exam can have up to 20 reminders."})
            changed = len(by_due) != len(reminders)
            if changed:
                write_reminders(table, row, list(by_due.values()))
            payload = dict(requested[0], savedExamId=saved_id) if single else list(by_due.values())
            return reply(201 if changed else 200, payload)
    except ResourceNotFoundError:
        return reply(404, {"error": "Saved exam not found"})
    except ResourceModifiedError:
        return reply(409, {"error": "Reminder changed concurrently. Try again."})
    except (AzureError, KeyError, ValueError) as error:
        logging.error("Reminder storage operation failed: %s", type(error).__name__)
        return reply(503, {"error": "Reminder storage is unavailable"})


def publish_due_reminders():
    now = utc_text(datetime.now(timezone.utc))
    published = 0
    with open_table() as table:
        # Read due times in Python for both legacy and multi-reminder rows.
        for row in table.list_entities():
            reminders = read_reminders(row)
            due = [r for r in reminders if r["status"] == "pending" and r["dueAt"] <= now]
            if not due:
                continue
            for reminder in due:
                reminder.update(status="published", publishedAt=now)
            try:
                write_reminders(table, row, reminders)
                published += len(due)
            except (ResourceModifiedError, ResourceNotFoundError):
                continue
    logging.info("Published %d due exam reminders", published)


def list_inbox(req):
    session, is_new = session_from(req)
    if is_new:
        return reply(200, [], session)
    try:
        with open_table() as table:
            rows = table.query_entities("PartitionKey eq @session", parameters={"session": session})
            notices = [
                dict(reminder, savedExamId=row["RowKey"], courseLabel=row["courseLabel"])
                for row in rows
                for reminder in read_reminders(row)
                if reminder["status"] == "published"
            ]
        return reply(200, sorted(notices, key=lambda item: item["publishedAt"], reverse=True))
    except (AzureError, KeyError, ValueError) as error:
        logging.error("Inbox storage operation failed: %s", type(error).__name__)
        return reply(503, {"error": "Reminder storage is unavailable"})
