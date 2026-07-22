"""
One-off script: creates the Azure AI Search index used for the RAG tool.
Run this once (and again any time you want to reset/recreate the schema).

Auth: DefaultAzureCredential -> your az login session, same as the other
test_*.py scripts. Needs "Search Service Contributor" on the search resource.
"""

import os

from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SearchField,
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
)
from dotenv import load_dotenv

load_dotenv()

SEARCH_ENDPOINT = "https://parth-agent-search.search.windows.net"
INDEX_NAME = "documents-index"
EMBEDDING_DIMENSIONS = 1536  # text-embedding-ada-002

# Same Foundry resource used everywhere else - Azure AI Search calls out to
# this at query time to embed the user's question automatically.
AOAI_RESOURCE_URL = "https://devrajvasani-7513-resource.services.ai.azure.com"
EMBEDDING_DEPLOYMENT = os.environ["EMBEDDING_DEPLOYMENT"]
AOAI_API_KEY = os.environ["KEY"]

VECTORIZER_NAME = "ada-vectorizer"

credential = DefaultAzureCredential()
index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)

fields = [
    SimpleField(name="id", type=SearchFieldDataType.String, key=True),
    SimpleField(name="filename", type=SearchFieldDataType.String, filterable=True),
    SearchableField(name="content", type=SearchFieldDataType.String),
    SearchField(
        name="embedding",
        type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
        searchable=True,
        vector_search_dimensions=EMBEDDING_DIMENSIONS,
        vector_search_profile_name="default-vector-profile",
    ),
]

vector_search = VectorSearch(
    algorithms=[HnswAlgorithmConfiguration(name="default-hnsw")],
    profiles=[
        VectorSearchProfile(
            name="default-vector-profile",
            algorithm_configuration_name="default-hnsw",
            vectorizer_name=VECTORIZER_NAME,
        )
    ],
    vectorizers=[
        AzureOpenAIVectorizer(
            vectorizer_name=VECTORIZER_NAME,
            kind="azureOpenAI",
            parameters=AzureOpenAIVectorizerParameters(
                resource_url=AOAI_RESOURCE_URL,
                deployment_name=EMBEDDING_DEPLOYMENT,
                model_name=EMBEDDING_DEPLOYMENT,
                api_key=AOAI_API_KEY,
            ),
        )
    ],
)

index = SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)

result = index_client.create_or_update_index(index)
print(f"Index '{result.name}' created/updated successfully.")
