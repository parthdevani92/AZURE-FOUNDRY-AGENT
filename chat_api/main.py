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

import io
import os
import uuid
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel
from pypdf import PdfReader

# .env lives at the repo root, one level up from this file.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PROJECT_ENDPOINT = os.environ["PROJECT_ENDPOINT"]
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
SEARCH_ENDPOINT = os.environ["SEARCH_ENDPOINT"]
SEARCH_INDEX_NAME = os.environ["SEARCH_INDEX_NAME"]
EMBEDDING_DEPLOYMENT = os.environ["EMBEDDING_DEPLOYMENT"]
EMBEDDING_ENDPOINT = os.environ["EMBEDDING_ENDPOINT"]

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

# Agents the UI can pick between - each has different tools attached in the
# Foundry portal, so they're not interchangeable mid-conversation.
AGENTS = {
    "kimi-agnet": "Kimi-K2.6 - calculator & user lookup tools",
    "gptagnet": "GPT-5.4-mini - document search (RAG)",
}
DEFAULT_AGENT_NAME = "kimi-agnet"

credential = DefaultAzureCredential()
project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=credential, allow_preview=True)
openai_clients = {name: project_client.get_openai_client(agent_name=name) for name in AGENTS}

# Embeddings live at the resource-level OpenAI-compatible endpoint, not the
# project-scoped one used above for the agent.
embedding_token_provider = get_bearer_token_provider(credential, "https://ai.azure.com/.default")
embedding_client = OpenAI(base_url=EMBEDDING_ENDPOINT, api_key=embedding_token_provider)

search_client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=SEARCH_INDEX_NAME, credential=credential)

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
    agent_name: str | None = None


class ChatResponse(BaseModel):
    reply: str
    response_id: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/agents")
def list_agents():
    return {
        "agents": [{"name": name, "label": label} for name, label in AGENTS.items()],
        "default": DEFAULT_AGENT_NAME,
    }


def _extract_text(filename: str, content: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return content.decode("utf-8", errors="ignore")


def _chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start : start + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    content = await file.read()
    text = _extract_text(file.filename, content)
    chunks = _chunk_text(text)

    if not chunks:
        raise HTTPException(status_code=400, detail="No extractable text found in file.")

    try:
        embeddings = embedding_client.embeddings.create(model=EMBEDDING_DEPLOYMENT, input=chunks)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Embedding call failed: {exc}") from exc

    documents = [
        {
            "id": str(uuid.uuid4()),
            "filename": file.filename,
            "content": chunk,
            "embedding": item.embedding,
        }
        for chunk, item in zip(chunks, embeddings.data)
    ]

    search_client.upload_documents(documents=documents)

    return {"filename": file.filename, "chunks_indexed": len(documents)}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    agent_name = request.agent_name or DEFAULT_AGENT_NAME
    client = openai_clients.get(agent_name)
    if client is None:
        raise HTTPException(status_code=400, detail=f"Unknown agent '{agent_name}'.")

    kwargs = {"input": request.message}
    if request.response_id:
        kwargs["previous_response_id"] = request.response_id

    try:
        response = client.responses.create(**kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agent call failed: {exc}") from exc

    return ChatResponse(reply=response.output_text, response_id=response.id)
