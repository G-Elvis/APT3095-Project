import json
import logging
import os
import re
import secrets
from datetime import datetime, timezone
from http.cookies import CookieError, SimpleCookie
from uuid import uuid4

import azure.functions as func
from azure.core.exceptions import AzureError
from azure.data.tables import TableClient

from planner import SLOTS

COOKIE_NAME = "__Host-exam_planner"
SLOTS_BY_ID = {slot["slotId"]: slot for slot in SLOTS}


def session_from(req):
    cookies = SimpleCookie()
    try:
        cookies.load(req.headers.get("Cookie", ""))
    except CookieError:
        cookies.clear()
    value = cookies.get(COOKIE_NAME)
    if value and re.fullmatch(r"[A-Za-z0-9_-]{43}", value.value):
        return value.value, False
    return secrets.token_urlsafe(32), True


def reply(status, payload, new_session=None):
    headers = {"Cache-Control": "no-store"}
    if new_session:
        headers["Set-Cookie"] = (
            f"{COOKIE_NAME}={new_session}; Path=/; Secure; HttpOnly; SameSite=Lax"
        )
    return func.HttpResponse(
        json.dumps(payload), status_code=status, headers=headers, mimetype="application/json"
    )


def handle_saved_exams(req):
    session, is_new = session_from(req)
    cookie = session if is_new else None
    if req.method == "POST":
        if req.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return reply(415, {"error": "Use application/json"})
        try:
            data = req.get_json()
        except ValueError:
            return reply(400, {"error": "Invalid JSON"})
        if not isinstance(data, dict):
            return reply(400, {"error": "Expected a JSON object"})
        slot_id = data.get("slotId")
        label = data.get("courseLabel")
        if not isinstance(slot_id, str) or not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
            return reply(400, {"error": "Provide slotId and a courseLabel of 1–80 characters"})
        if slot_id not in SLOTS_BY_ID:
            return reply(404, {"error": "Unknown exam slot"})

    connection = os.environ.get("AzureWebJobsStorage")
    if not connection:
        logging.error("SavedExams requires an AzureWebJobsStorage connection string")
        return reply(503, {"error": "Saved exams storage is unavailable"})

    try:
        with TableClient.from_connection_string(connection, table_name="SavedExams") as table:
            if req.method == "POST":
                saved_id = uuid4().hex
                course_label = label.strip()
                table.create_entity({
                    "PartitionKey": session,
                    "RowKey": saved_id,
                    "slotId": slot_id,
                    "courseLabel": course_label,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                })
                return reply(201, {
                    "savedExamId": saved_id, "slotId": slot_id, "courseLabel": course_label
                }, cookie)

            rows = table.query_entities("PartitionKey eq @session", parameters={"session": session})
            exams = []
            for row in rows:
                slot = SLOTS_BY_ID.get(row["slotId"])
                if slot:
                    exams.append({
                        "savedExamId": row["RowKey"],
                        "courseLabel": row["courseLabel"],
                        "examDate": slot["examDate"],
                        "examStart": slot["examStart"],
                    })
            exams.sort(key=lambda exam: (exam["examDate"], exam["examStart"], exam["savedExamId"]))
            return reply(200, exams, cookie)
    except (AzureError, ValueError) as error:
        logging.error("SavedExams storage operation failed: %s", type(error).__name__)
        return reply(503, {"error": "Saved exams storage is unavailable"})
