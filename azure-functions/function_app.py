import json

import azure.functions as func

from planner import lookup
from reminders import list_inbox, publish_due_reminders, set_reminder
from saved_exams import handle_saved_exams

app = func.FunctionApp()


@app.route(route="exam-slots", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def exam_slots(req: func.HttpRequest) -> func.HttpResponse:
    status, payload = lookup(req.params)
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status,
        mimetype="application/json",
    )


@app.route(route="saved-exams", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def saved_exams(req: func.HttpRequest) -> func.HttpResponse:
    return handle_saved_exams(req)


@app.route(route="saved-exams/{id}/reminder", methods=["PUT"], auth_level=func.AuthLevel.ANONYMOUS)
def exam_reminder(req: func.HttpRequest) -> func.HttpResponse:
    return set_reminder(req)


@app.timer_trigger(schedule="0 * * * * *", arg_name="timer", use_monitor=True)
def reminder_timer(timer: func.TimerRequest) -> None:
    publish_due_reminders()


@app.route(route="inbox", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def inbox(req: func.HttpRequest) -> func.HttpResponse:
    return list_inbox(req)
