"""
Hosted Agent — FastAPI service that talks to the Kimi-K2.6 model deployed in
Azure AI Foundry, and can call two custom "tools" (plain Python functions)
when the model decides it needs them:

  1. calculate    -> does math (e.g. "what is 12 * 7?")
  2. query_users  -> searches a small hardcoded list of dummy users
                     (e.g. "list users older than 18", "who weighs under 25kg")

How "tool calling" works here (no Azure Agents/Assistants API involved):
  1. We send the user's message to the model along with a TOOLS list that
     describes what each function does and what arguments it takes.
  2. If the model decides a tool is needed, it replies with a "tool_calls"
     entry instead of a normal answer, naming the function + arguments.
  3. We run that Python function ourselves, locally, and send the result
     back to the model as a "tool" message.
  4. The model reads the tool result and writes the final human-readable
     answer, which we return to the caller.

This is the standard OpenAI-style "function calling" pattern - it works
directly against the chat completions endpoint, so it's simple and doesn't
depend on any Azure-specific "agent" service.
"""

import json
import os
from datetime import date

from fastapi import FastAPI
from pydantic import BaseModel

from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# ---------------------------------------------------------------------------
# 1. Connect to the Azure AI Foundry model
# ---------------------------------------------------------------------------

# PROJECT_ENDPOINT looks like:
#   https://<resource>.services.ai.azure.com/api/projects/<project-name>
# but chat completions need the account-level endpoint instead:
#   https://<resource>.services.ai.azure.com/openai/v1
# so we derive it by cutting off the "/api/projects/..." part.
PROJECT_ENDPOINT = os.environ["PROJECT_ENDPOINT"]
DEPLOYMENT_NAME = os.environ.get("DEPLOYMENT_NAME", "Kimi-K2.6")
ACCOUNT_ENDPOINT = PROJECT_ENDPOINT.split("/api/projects/")[0] + "/openai/v1"

# get_bearer_token_provider() returns a function that fetches a fresh Azure AD
# token whenever the OpenAI client needs one - no API keys stored anywhere.
# Locally this uses your `az login` session; once deployed to Azure, it will
# automatically use the Container App's managed identity instead.
token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
client = OpenAI(base_url=ACCOUNT_ENDPOINT, api_key=token_provider)


# ---------------------------------------------------------------------------
# 2. Tool #1 - Calculator
# ---------------------------------------------------------------------------
# We do NOT use Python's built-in eval() here - eval() would run any Python
# code the model (or a malicious prompt) sends us, which is a big security
# risk. Instead we parse the expression into a syntax tree with `ast` and
# only allow a safe, fixed set of math operators.

import ast
import operator

_ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,  # unary minus, e.g. -5
    ast.UAdd: operator.pos,  # unary plus, e.g. +5
}


def _safe_eval(node):
    """Recursively evaluate a parsed math expression, one node at a time."""
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _ALLOWED_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    raise ValueError("Only numbers and + - * / % ** operators are allowed.")


def calculate(expression: str) -> str:
    """Safely evaluate a basic arithmetic expression and return the result as text."""
    try:
        parsed = ast.parse(expression, mode="eval")
        result = _safe_eval(parsed.body)
        return str(result)
    except Exception:
        return f"Could not calculate '{expression}'. Please use only numbers and + - * / % **."


# ---------------------------------------------------------------------------
# 3. Tool #2 - Static user datasource
# ---------------------------------------------------------------------------
# A small hardcoded/dummy "database" of users. In a real app this would come
# from a real database - here it's just a Python list so the example stays
# simple and needs no extra setup.

DUMMY_USERS = [
    {"name": "Amit Shah", "phone": "9998887771", "dob": "1998-04-12", "height_cm": 175, "weight_kg": 70},
    {"name": "Priya Mehta", "phone": "9998887772", "dob": "2010-06-20", "height_cm": 150, "weight_kg": 40},
    {"name": "Ravi Patel", "phone": "9998887773", "dob": "1985-11-02", "height_cm": 168, "weight_kg": 82},
    {"name": "Sneha Joshi", "phone": "9998887774", "dob": "2015-01-30", "height_cm": 110, "weight_kg": 22},
    {"name": "Karan Desai", "phone": "9998887775", "dob": "2005-09-15", "height_cm": 172, "weight_kg": 60},
    {"name": "Neha Trivedi", "phone": "9998887776", "dob": "2019-03-08", "height_cm": 95, "weight_kg": 15},
    {"name": "Vikram Rao", "phone": "9998887777", "dob": "1975-07-22", "height_cm": 165, "weight_kg": 90},
    {"name": "Anjali Nair", "phone": "9998887778", "dob": "2002-12-01", "height_cm": 160, "weight_kg": 55},
]


def _age_from_dob(dob_str: str) -> int:
    """Turn a 'YYYY-MM-DD' date of birth into a whole number age in years."""
    dob = date.fromisoformat(dob_str)
    today = date.today()
    had_birthday_this_year = (today.month, today.day) >= (dob.month, dob.day)
    return today.year - dob.year - (0 if had_birthday_this_year else 1)


def query_users(
    min_age: int = None,
    max_age: int = None,
    min_weight_kg: float = None,
    max_weight_kg: float = None,
    min_height_cm: float = None,
    max_height_cm: float = None,
    phone: str = None,
) -> str:
    """
    Search DUMMY_USERS using any combination of filters.
    Every filter is optional; the ones you pass in are combined with AND
    (e.g. min_age=18 + max_weight_kg=70 -> users who are 18+ AND weigh <=70kg).
    """
    matches = []
    for user in DUMMY_USERS:
        age = _age_from_dob(user["dob"])

        if min_age is not None and age < min_age:
            continue
        if max_age is not None and age > max_age:
            continue
        if min_weight_kg is not None and user["weight_kg"] < min_weight_kg:
            continue
        if max_weight_kg is not None and user["weight_kg"] > max_weight_kg:
            continue
        if min_height_cm is not None and user["height_cm"] < min_height_cm:
            continue
        if max_height_cm is not None and user["height_cm"] > max_height_cm:
            continue
        if phone is not None and user["phone"] != phone:
            continue

        matches.append({**user, "age": age})

    if not matches:
        return "No matching users found."
    return json.dumps(matches)


# ---------------------------------------------------------------------------
# 4. Tool registry
# ---------------------------------------------------------------------------
# TOOLS is what we send to the model so it knows these functions exist and
# what arguments they take (this is standard OpenAI "function calling" JSON
# schema format). AVAILABLE_FUNCTIONS maps each tool name to the real Python
# function we run when the model asks for it.

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a basic arithmetic expression. Use this for any math question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate, e.g. '12 * (3 + 4)'.",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_users",
            "description": (
                "Search a small static list of users by age, weight, height and/or exact phone "
                "number. All filters are optional and combine together. Use this for any question "
                "about the user list, e.g. 'list users 18 or older', 'who weighs less than 25kg', "
                "'find the user with phone 9998887771'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_age": {"type": "integer", "description": "Only users at least this age (inclusive)."},
                    "max_age": {"type": "integer", "description": "Only users at most this age (inclusive)."},
                    "min_weight_kg": {"type": "number", "description": "Only users weighing at least this many kg."},
                    "max_weight_kg": {"type": "number", "description": "Only users weighing at most this many kg."},
                    "min_height_cm": {"type": "number", "description": "Only users at least this tall (cm)."},
                    "max_height_cm": {"type": "number", "description": "Only users at most this tall (cm)."},
                    "phone": {"type": "string", "description": "Exact phone number to look up."},
                },
                "required": [],
            },
        },
    },
]

AVAILABLE_FUNCTIONS = {
    "calculate": calculate,
    "query_users": query_users,
}


# ---------------------------------------------------------------------------
# 5. FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI()


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.get("/health")
def health():
    """Simple health check endpoint - Azure Container Apps uses this to know the app is alive."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. Use the calculate tool for any math question, "
                "and the query_users tool for any question about the user list."
            ),
        },
        {"role": "user", "content": request.message},
    ]

    # First call: give the model the tools list. It replies either with a
    # normal text answer, or with one or more "tool_calls" it wants us to run.
    response = client.chat.completions.create(model=DEPLOYMENT_NAME, messages=messages, tools=TOOLS)
    reply_message = response.choices[0].message

    if reply_message.tool_calls:
        # The model wants to use one or more tools. Add its request to the
        # conversation, then run each tool locally and add the results too.
        messages.append(reply_message.model_dump())

        for tool_call in reply_message.tool_calls:
            function_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            result = AVAILABLE_FUNCTIONS[function_name](**arguments)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,  # links this result back to the model's request
                    "content": result,
                }
            )

        # Second call: now the model has the tool results and can write the
        # final, human-readable answer. No "tools" needed this time.
        response = client.chat.completions.create(model=DEPLOYMENT_NAME, messages=messages)
        reply_message = response.choices[0].message

    return ChatResponse(reply=reply_message.content or "No reply generated.")
