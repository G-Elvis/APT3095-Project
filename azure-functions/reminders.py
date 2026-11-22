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
    minutes = body.get("minutesBefore") if isinstance(body, dict) else None
    if type(minutes) is not int or not 1 <= minutes <= 525600:
        return reply(400, {"error": "minutesBefore must be an integer between 1 and 525600"})

    try:
        with open_table() as table:
            row = table.get_entity(session, saved_id)
            slot = SLOTS_BY_ID.get(row["slotId"])
            if slot is None:
                return reply(404, {"error": "Exam slot not found"})
            start = datetime.fromisoformat(f'{slot["examDate"]}T{slot["examStart"]}')
            start = start.replace(tzinfo=ZoneInfo(slot["timeZone"])).astimezone(timezone.utc)
            due = start - timedelta(minutes=minutes)
            if due <= datetime.now(timezone.utc):
                return reply(400, {"error": "Reminder deadline has already passed"})
            due_at = due.strftime("%Y-%m-%dT%H:%M:%SZ")
            result = {"reminderId": saved_id, "savedExamId": saved_id,
                      "dueAt": due_at, "status": "pending"}
            if row.get("reminderDueAt") == due_at:
                result["status"] = row["reminderStatus"]
                return reply(200, result)
            table.update_entity(
                {"PartitionKey": session, "RowKey": saved_id,
                 "reminderDueAt": due_at, "reminderStatus": "pending",
                 "reminderPublishedAt": ""},
                mode=UpdateMode.MERGE, etag=row.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return reply(200 if row.get("reminderDueAt") else 201, result)
    except ResourceNotFoundError:
        return reply(404, {"error": "Saved exam not found"})
    except ResourceModifiedError:
        return reply(409, {"error": "Reminder changed concurrently. Try again."})
    except (AzureError, KeyError, ValueError) as error:
        logging.error("Reminder storage operation failed: %s", type(error).__name__)
        return reply(503, {"error": "Reminder storage is unavailable"})
