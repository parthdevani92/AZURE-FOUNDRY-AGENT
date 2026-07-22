"""
Azure Function App exposing the calculator and user-lookup tools as plain
HTTP endpoints. Once deployed, the Microsoft Foundry portal agent calls
these URLs directly via an "OpenAPI tool" - Foundry hosts the agent loop,
we only host these two small functions.

Endpoints:
  POST /api/calculate    body: {"expression": "12 * (3 + 4)"}
  POST /api/queryUsers   body: {"min_age": 18, ...}  (all fields optional)
"""

import ast
import json
import operator
import os
from datetime import date

import azure.functions as func

# This app runs as a plain Container App, not a classic Function App resource,
# so Azure's built-in function-key management (which needs that classic
# resource type) isn't available here. Instead we check our own shared
# secret, set as the TOOL_API_KEY environment variable on the Container App,
# against an "x-api-key" header the caller must send.
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _check_api_key(req: func.HttpRequest) -> bool:
    expected = os.environ.get("TOOL_API_KEY")
    return bool(expected) and req.headers.get("x-api-key") == expected


# ---------------------------------------------------------------------------
# Tool #1 - Calculator
# ---------------------------------------------------------------------------
# Same safe approach as the FastAPI version: parse with `ast` and only allow
# a fixed set of math operators, instead of using eval() (which would let
# anyone run arbitrary Python through this endpoint).

_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    raise ValueError("Only numbers and + - * / % ** operators are allowed.")


@app.route(route="calculate", methods=["POST"])
def calculate(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_api_key(req):
        return func.HttpResponse(json.dumps({"error": "Unauthorized"}), status_code=401, mimetype="application/json")

    body = req.get_json()
    expression = body.get("expression", "")
    try:
        parsed = ast.parse(expression, mode="eval")
        result = _safe_eval(parsed.body)
        return func.HttpResponse(json.dumps({"result": str(result)}), mimetype="application/json")
    except Exception:
        return func.HttpResponse(
            json.dumps({"error": f"Could not calculate '{expression}'."}),
            status_code=400,
            mimetype="application/json",
        )


# ---------------------------------------------------------------------------
# Tool #2 - Static user datasource
# ---------------------------------------------------------------------------
# Same dummy data as the FastAPI version - a hardcoded list standing in for
# a real database.

DUMMY_USERS = [
    {"name": "Amit ol", "phone": "9998887771", "dob": "1998-04-12", "height_cm": 175, "weight_kg": 70},
    {"name": "Priya Mehta", "phone": "9998887772", "dob": "2010-06-20", "height_cm": 150, "weight_kg": 40},
    {"name": "Ravi Patel", "phone": "9998887773", "dob": "1985-11-02", "height_cm": 168, "weight_kg": 82},
    {"name": "Sneha Joshi", "phone": "9998887774", "dob": "2015-01-30", "height_cm": 110, "weight_kg": 22},
    {"name": "Karan Desai", "phone": "9998887775", "dob": "2005-09-15", "height_cm": 172, "weight_kg": 60},
    {"name": "Neha Trivedi", "phone": "9998887776", "dob": "2019-03-08", "height_cm": 95, "weight_kg": 15},
    {"name": "Vikram Rao", "phone": "9998887777", "dob": "1975-07-22", "height_cm": 165, "weight_kg": 90},
    {"name": "Anjali Nair", "phone": "9998887778", "dob": "2002-12-01", "height_cm": 160, "weight_kg": 55},
]


def _age_from_dob(dob_str: str) -> int:
    dob = date.fromisoformat(dob_str)
    today = date.today()
    had_birthday_this_year = (today.month, today.day) >= (dob.month, dob.day)
    return today.year - dob.year - (0 if had_birthday_this_year else 1)


@app.route(route="queryUsers", methods=["POST"])
def query_users(req: func.HttpRequest) -> func.HttpResponse:
    if not _check_api_key(req):
        return func.HttpResponse(json.dumps({"error": "Unauthorized"}), status_code=401, mimetype="application/json")

    try:
        body = req.get_json()
    except ValueError:
        body = {}

    matches = []
    for user in DUMMY_USERS:
        age = _age_from_dob(user["dob"])

        if body.get("min_age") is not None and age < body["min_age"]:
            continue
        if body.get("max_age") is not None and age > body["max_age"]:
            continue
        if body.get("min_weight_kg") is not None and user["weight_kg"] < body["min_weight_kg"]:
            continue
        if body.get("max_weight_kg") is not None and user["weight_kg"] > body["max_weight_kg"]:
            continue
        if body.get("min_height_cm") is not None and user["height_cm"] < body["min_height_cm"]:
            continue
        if body.get("max_height_cm") is not None and user["height_cm"] > body["max_height_cm"]:
            continue
        if body.get("phone") is not None and user["phone"] != body["phone"]:
            continue

        matches.append({**user, "age": age})

    return func.HttpResponse(json.dumps({"users": matches}), mimetype="application/json")
