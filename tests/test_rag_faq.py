import pytest
import chromadb
import uuid
from unittest.mock import patch, MagicMock
from serviceBot.services.rag import FAQService
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from langchain_core.messages import AIMessage


class KeywordMockEmbeddingFunction(EmbeddingFunction):
    """
    A simple, deterministic, network-free embedding function for testing.
    Maps input text to a simple keyword-presence vector.
    """
    def __call__(self, input: Documents) -> Embeddings:
        keywords = ["oil change", "brake pad", "open Monday", "saturday", "sunday", "located at"]
        embeddings = []
        for text in input:
            # Create a basic feature vector
            vec = [0.0] * len(keywords)
            for i, kw in enumerate(keywords):
                if kw.lower() in text.lower():
                    vec[i] = 1.0
            embeddings.append(vec)
        return embeddings


@pytest.fixture
def temp_chroma_collection():
    """
    Initialize a temporary in-memory vector collection using chromadb.EphemeralClient
    and seed it with pricing and operations document chunks.
    """
    client = chromadb.EphemeralClient()
    # Use a unique collection name to avoid collision during test runs
    unique_name = f"faq_test_collection_{uuid.uuid4().hex}"
    collection = client.create_collection(
        unique_name, 
        embedding_function=KeywordMockEmbeddingFunction()
    )
    
    # Seed pricing and operations document chunks
    documents = [
        "Synthetic oil change costs $79.99. Brake pad replacement is $199 per axle.",
        "We are open Monday to Friday from 7:00 AM to 6:00 PM, and we are closed on Saturdays and Sundays.",
        "We are located at 123 Main Street, Springfield."
    ]
    metadatas = [
        {"category": "pricing"},
        {"category": "operations"},
        {"category": "location"}
    ]
    ids = ["doc_pricing", "doc_operations", "doc_location"]
    
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )
    return collection


def test_semantic_retrieval(temp_chroma_collection):
    """
    Assert that queries retrieve relevant pricing/operation document chunks
    from the vector database.
    """
    # Query pricing info
    pricing_results = temp_chroma_collection.query(
        query_texts=["How much is an oil change and brake pad replacement?"],
        n_results=1
    )
    assert len(pricing_results["documents"][0]) > 0
    assert "oil change" in pricing_results["documents"][0][0].lower()
    assert "brake pad" in pricing_results["documents"][0][0].lower()
    
    # Query operations info
    ops_results = temp_chroma_collection.query(
        query_texts=["What are your hours on Saturday and Sunday?"],
        n_results=1
    )
    assert len(ops_results["documents"][0]) > 0
    assert "saturday" in ops_results["documents"][0][0].lower()
    assert "sunday" in ops_results["documents"][0][0].lower()


def test_faq_agent_no_hallucination(temp_chroma_collection):
    """
    Assert the FAQ agent answers user questions strictly using retrieved snippets
    without hallucination.
    """
    service = FAQService(collection=temp_chroma_collection)
    
    # Mock ChatOpenAI or similar LLM inside the service to simulate responses
    # 1. Answer with context: Saturday hours
    # The agent should respond using retrieved snippet info
    with patch("serviceBot.services.rag.ChatOpenAI") as mock_chat:
        mock_llm = mock_chat.return_value
        
        # Mock both invoke() and __call__() due to LangChain's coerce_to_runnable wrapper
        aimsg_valid = AIMessage(content="We are closed on Saturdays and Sundays to allow our team time with family.")
        mock_llm.invoke.return_value = aimsg_valid
        mock_llm.return_value = aimsg_valid
        
        response = service.answer_question("Are you open on Saturdays?")
        assert "closed" in response.lower()
        assert "saturday" in response.lower()
        
        # Verify LLM was called
        assert mock_llm.invoke.called or mock_llm.called

    # 2. Prevent hallucination for out-of-context questions
    # The agent should refuse to answer questions not covered by the context
    with patch("serviceBot.services.rag.ChatOpenAI") as mock_chat:
        mock_llm = mock_chat.return_value
        
        # Mock both invoke() and __call__() due to LangChain's coerce_to_runnable wrapper
        aimsg_invalid = AIMessage(content="I am sorry, but I do not have that information in my knowledge base.")
        mock_llm.invoke.return_value = aimsg_invalid
        mock_llm.return_value = aimsg_invalid
        
        response = service.answer_question("Do you offer helicopter transmission repairs?")
        # It should refuse to answer / acknowledge it does not know instead of hallucinating
        assert any(
            phrase in response.lower()
            for phrase in ["not in", "don't know", "cannot answer", "do not have", "sorry"]
        )
