# Exam Planner lookup for Azure Functions

The Python v2 HTTP function serves GET /exam-slots using three sample timetable rows. The sample data is for the first milestone. The full dataset, database, reminder timer and student UI are pending.

## Run locally

Use Python 3.12 and Azure Functions Core Tools. Create and activate a virtual environment, run `python -m pip install -r requirements.txt`, copy `local.settings.example.json` to `local.settings.json`, and run `func start`.

Request `http://localhost:7071/exam-slots?period=final&pattern=MW&start=09:00&end=10:40`. Expect HTTP 200 and examDate 2026-12-09. Request only period to list the loaded slots.

## Deploy

Check whether the student subscription allows a Linux Python 3.12 Function App on Flex Consumption and its required storage account. Once created, publish with Azure Functions Core Tools using `func azure functionapp publish YOUR_APP_NAME`. Configure the function app's storage in Azure before adding a timer trigger.

See https://learn.microsoft.com/azure/azure-functions/functions-run-local for Core Tools and https://learn.microsoft.com/azure/azure-functions/flex-consumption-plan for the hosting plan.

## Collaborate on GitHub

Use a single team repository. Members can contribute via branches and pull requests. Keep diagrams, API specifications and evaluation scripts alongside the code. Commit only anonymised evidence that the group can share. The ignored local settings file is for local configuration.
