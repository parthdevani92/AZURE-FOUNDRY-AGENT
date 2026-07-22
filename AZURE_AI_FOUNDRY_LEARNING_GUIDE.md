# Learning Azure AI Foundry — From Zero to a Deployed Agent App

How to go from "what is Foundry" to a working agent with tools, a custom chat UI,
and a full Azure deployment with CI/CD.

## 1. Core concepts

- **Foundry project** — a workspace holding model deployments and agents. Agents and
  their permissions are scoped to a project (e.g. `.../api/projects/<name>`).
- **Model deployment** — an LLM (e.g. `gpt-5-mini`) deployed in your Foundry resource
  under a name you reference in code.
- **Agent** — an LLM plus persistent config: instructions, allowed tools, and memory
  across turns. Same model, more scaffolding.
- **Tool** — a function the agent can call mid-conversation (e.g. a lookup or
  calculation). The model never runs it — it asks the host to run it and reads back
  the result.
- **Memory** — how an agent remembers earlier turns. This project uses the Responses
  API's `previous_response_id`: pass the last reply's ID into the next call.

**Two unrelated SDKs, don't mix them up:**
1. Classic Assistants style — `AgentsClient`, explicit `threads`/`runs`, IDs like
   `asst_...`. Not what a Foundry-portal-created agent is.
2. Versioned Foundry Agent — `AIProjectClient` → `get_openai_client(agent_name=...)`
   → `responses.create(...)`. Addressed by **name**, not ID. Use this for
   portal-created agents.

## 2. Call an LLM with code (no agent yet)

```python
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())
openai = project.get_openai_client()
response = openai.responses.create(model="gpt-5-mini", input="Say hello in one sentence.")
print(response.output_text)
```

Good smoke test for credentials (`az login` locally) before building anything else.

## 3. Build the agent in the Foundry portal

1. ai.azure.com → your project → **Agents** → new agent.
2. Pick a model, give it a name and instructions.
3. Publish it, then test it in the **Playground**.

## 4. Call the portal agent from code

```python
project_client = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential(), allow_preview=True)
openai_client = project_client.get_openai_client(agent_name="kimi-agnet")

response = openai_client.responses.create(input="Hello!")
response2 = openai_client.responses.create(input="What did I just say?", previous_response_id=response.id)
```

- Use `agent_name`, not the Entra identity GUID from the Details tab.
- Only pass `previous_response_id` when you actually have one — sending it as `None`
  causes a `400 invalid_payload`.
- The newer explicit "agent session" API (`create_session`/`agent_session_id`)
  repeatedly failed with `agent_version_not_ready` in testing; `previous_response_id`
  chaining just works.
- `DefaultAzureCredential()` uses your `az login` locally and the compute's Managed
  Identity once deployed — no stored keys either way.

## 5. Add custom tools

Two example tools, exposed as plain HTTP endpoints (`azure_function_tool/`):
`/calculate` (safe arithmetic via `ast`, not `eval`) and `/queryUsers` (search a
hardcoded user list). Both check a shared secret sent as an `x-api-key` header.

Foundry agents consume tools via an **OpenAPI tool**: host the endpoints, describe
them in an OpenAPI 3.0 spec (`azure_function_tool/openapi.json`), attach the spec to
the agent. Foundry decides when to call it and feeds the result back to the model.

**Wiring it up:**
1. Deploy the tool app, get its HTTPS URL.
2. Put that URL in the spec's `servers[0].url`.
3. Agent → **Tools** → **Add** → **OpenAPI 3.0 specified tool** → paste spec → auth =
   API key, header `x-api-key`, value = the tool app's `TOOL_API_KEY`.
4. Test in the Playground ("What's 12 × (3+4)?", "Find users under 20").

## 6. Build the UI

A small React/Vite chat page (`web_ui/src/App.jsx`) that calls a FastAPI proxy — not
Foundry directly, since calling Foundry needs an Azure identity a browser can't hold.

```jsx
const res = await fetch(`${CHAT_API_URL}/chat`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: text, response_id: responseId }),
});
const data = await res.json();
setResponseId(data.response_id); // carried into the next call
```

`CHAT_API_URL` is a Vite env var — `.env` (local, gitignored) vs `.env.production`
(committed, just a public URL).

The proxy (`chat_api/main.py`) is two FastAPI routes: `/health` and `/chat`, the
latter calling `openai_client.responses.create(...)` and returning
`{reply, response_id}`. CORS is restricted via an `ALLOWED_ORIGIN` env var.

## 7. Deploy to Azure (Portal + GitHub Actions CI/CD)

Each app (`chat_api`, `azure_function_tool`, `web_ui`) is deployed the same general
way: create the Azure resource in the Portal, connect it to the GitHub repo/branch,
which auto-generates a GitHub Actions workflow that redeploys on every push.

**`chat_api` → Container App**
- Dockerize (`python:3.12-slim`, `uvicorn`, port `8000`).
- Continuous Deployment: use **Service Principal** auth (User-assigned Identity hit
  `federatedIdentityCredentials` preflight errors on this subscription).
- Enable **System-assigned Managed Identity** so `DefaultAzureCredential` works with
  no stored secrets.
- Grant that identity **"Foundry Agent Consumer"** (not "Azure AI Developer" — that's
  scoped to ML workspaces, not Foundry, and causes a 403 on `agents/write`), assigned
  at the **Foundry project** scope, not the account.
- Env vars: `PROJECT_ENDPOINT`, `AGENT_NAME`, `ALLOWED_ORIGIN`.
- **Set the port in two places, independently**: Ingress → Target port, *and*
  Containers → Health probes → Startup probe → Port. Both default to `80` on a new
  Container App; leaving either one wrong causes it to serve the placeholder image or
  crash-loop on failed startup probes even once the app itself is running fine.

**`azure_function_tool` → Container App** — same steps, plus a `TOOL_API_KEY` env var
matching the key configured on the agent's OpenAPI tool.

**`web_ui` → Static Web App**
- App location: `web_ui`. Output location: **`dist`** (Vite's output folder — the
  portal defaults this to `build`, which is React CRA's convention and fails the
  build if left unchanged).
- `web_ui/.env.production` must hold the real `chat_api` URL before building — Vite
  bakes `VITE_*` vars in at build time.

## 8. Test end-to-end

1. Locally first: run `chat_api` (`uvicorn main:app --reload`) against the real
   Foundry project, and `web_ui` (`npm run dev`) against it. Try a plain question, a
   tool-triggering question, and a follow-up that depends on memory.
2. Then the deployed pieces, in dependency order: tool app → agent (Playground) →
   `chat_api` (`/health`, then `/chat`) → Static Web App in a browser.
3. A `502` from the UI is `chat_api`'s own wrapper around a real error — read the
   response body in DevTools' Network tab, not just the status code.

## 9. Security, monitoring, cost

- Grant only the specific role needed (**Foundry Agent Consumer**) at the narrowest
  scope (the project), not broader "just in case" roles.
- No secrets in code — Managed Identity for Foundry auth, the one real secret
  (`TOOL_API_KEY`) lives only as a Container App env var.
- Tighten `ALLOWED_ORIGIN` to the real UI URL once deployed.
- Use the project's **Traces** tab to read a full request end-to-end, and **Monitor**
  for volume/errors/latency.
- Set a Cost Management **budget** with alert thresholds, scoped to the specific
  subscription/resource group (not the whole billing account, if other unrelated
  projects share it).

## Architecture

```
Browser → Static Web App (React/Vite)
        → chat_api (Container App, FastAPI proxy)
        → Foundry agent (Responses API, Managed Identity auth)
        → azure_function_tool (Container App: /calculate, /queryUsers, via OpenAPI tool)
```

Each of the three apps has its own GitHub Actions workflow — a push to `main`
redeploys just that piece.

## Repo layout

| Path | What it is |
|---|---|
| `test_chat.py`, `test_connection.py`, `test_agent.py` | Standalone scripts for the different ways to call an LLM/agent (§2) |
| `chat_api/` | FastAPI proxy → Container App |
| `web_ui/` | React/Vite chat UI → Static Web App |
| `azure_function_tool/` | Calculator + user-lookup tools, OpenAPI spec → Container App |
| `foundry_roadmap.html` | The learning roadmap this project follows |
