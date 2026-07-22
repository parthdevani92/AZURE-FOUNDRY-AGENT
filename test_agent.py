import os
from azure.identity import DefaultAzureCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import ListSortOrder

project_endpoint = os.environ["PROJECT_ENDPOINT"]  # https://<resource>.services.ai.azure.com/api/projects/<project-name>
deployment_name = "Kimi-K2.6"

agents_client = AgentsClient(
    endpoint=project_endpoint,
    credential=DefaultAzureCredential(),
)

# 1. Create a persistent agent (model + instructions + optional tools)
agent = agents_client.create_agent(
    model=deployment_name,
    name="my-first-agent",
    instructions="You are a helpful assistant. Keep answers short.",
)
print(f"Created agent: {agent.id}")

# 2. Open a conversation thread
thread = agents_client.threads.create()
print(f"Created thread: {thread.id}")

# 3. Add a user message to the thread
agents_client.messages.create(
    thread_id=thread.id,
    role="user",
    content="What is the capital of France?",
)

# 4. Run the agent on the thread (blocks until finished)
run = agents_client.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)
print(f"Run status: {run.status}")

if run.status == "failed":
    print(f"Run failed: {run.last_error}")
else:
    # 5. Read back the conversation
    messages = agents_client.messages.list(thread_id=thread.id, order=ListSortOrder.ASCENDING)
    for message in messages:
        if message.text_messages:
            print(f"{message.role}: {message.text_messages[-1].text.value}")

# Optional cleanup
agents_client.delete_agent(agent.id)
