import os
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient

endpoint = os.environ["PROJECT_ENDPOINT"]
print(f"Using endpoint: {endpoint}")

project = AIProjectClient(
    endpoint=endpoint,
    credential=DefaultAzureCredential(),
)

openai = project.get_openai_client()

response = openai.responses.create(
    model="gpt-5-mini",  # change this to the deployment name you created in the portal
    input="Say hello in one short sentence.",
)

print("SUCCESS! Model responded:")
print(response.output_text)
