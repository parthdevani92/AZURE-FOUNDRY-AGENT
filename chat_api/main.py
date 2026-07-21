"""
Chat proxy API — sits between the custom UI (Static Web App) and the
published "kimi-agnet" agent in Azure AI Foundry.

kimi-agnet is a versioned Foundry Agent (Entra-identity backed), called
through the Responses API. Conversation continuity across turns uses the
Responses API's own `previous_response_id` chaining — each reply's id is
passed back on the next turn so the model sees prior context. (Foundry's
newer explicit "agent session" API exists too, but was returning
agent_version_not_ready in testing even though the agent version itself
is active — previous_response_id needs no separate session step.)

Auth to Foundry uses DefaultAzureCredential: locally that's your `az login`
session; once deployed to Azure, it automatically uses this Container App's
managed identity — no keys stored anywhere. The identity needs the
"Azure AI User" role on the Foundry project.
"""

import os

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PROJECT_ENDPOINT = os.environ["PROJECT_ENDPOINT"]
AGENT_NAME = os.environ["AGENT_NAME"]
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

credential = DefaultAzureCredential()
project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential, allow_preview=True)
openai_client = project_client.get_openai_client(agent_name=AGENT_NAME)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    response_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    response_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    kwargs = {"input": request.message}
    if request.response_id:
        kwargs["previous_response_id"] = request.response_id

    try:
        response = openai_client.responses.create(**kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent call failed: {exc}") from exc

    return ChatResponse(reply=response.output_text, response_id=response.id)
