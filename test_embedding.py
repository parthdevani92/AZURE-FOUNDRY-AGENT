import os

from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv

load_dotenv()

deployment = os.environ["EMBEDDING_DEPLOYMENT"]

# Resource-level endpoint (same style test_chat.py used successfully),
# not the project-scoped AIProjectClient endpoint.
endpoint = "https://devrajvasani-7513-resource.services.ai.azure.com/openai/v1"
print(f"Endpoint: {endpoint}")
print(f"Deployment name: {deployment}")

token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://ai.azure.com/.default")
client = OpenAI(base_url=endpoint, api_key=token_provider)

response = client.embeddings.create(model=deployment, input="hello world")
print(f"SUCCESS! Vector length: {len(response.data[0].embedding)}")
