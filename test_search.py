"""
One-off script: tests that vector search against `documents-index` actually
works, independent of the Foundry portal's Azure AI Search tool. Embeds the
query the same way chat_api's /upload does, then runs a vector search.
"""

import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SEARCH_ENDPOINT = os.environ["SEARCH_ENDPOINT"]
SEARCH_INDEX_NAME = os.environ["SEARCH_INDEX_NAME"]
EMBEDDING_DEPLOYMENT = os.environ["EMBEDDING_DEPLOYMENT"]
EMBEDDING_ENDPOINT = os.environ["EMBEDDING_ENDPOINT"]

QUESTION = "What is AACE?"

credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(credential, "https://ai.azure.com/.default")
embedding_client = OpenAI(base_url=EMBEDDING_ENDPOINT, api_key=token_provider)

search_client = SearchClient(endpoint=SEARCH_ENDPOINT, index_name=SEARCH_INDEX_NAME, credential=credential)

query_embedding = embedding_client.embeddings.create(model=EMBEDDING_DEPLOYMENT, input=QUESTION).data[0].embedding

results = search_client.search(
    search_text=None,
    vector_queries=[VectorizedQuery(vector=query_embedding, k_nearest_neighbors=5, fields="embedding")],
    select=["filename", "content"],
)

print(f"Question: {QUESTION}\n")
for i, result in enumerate(results, start=1):
    print(f"--- Result {i} (score={result['@search.score']:.4f}) ---")
    print(f"filename: {result['filename']}")
    print(f"content: {result['content'][:300]}...\n")
