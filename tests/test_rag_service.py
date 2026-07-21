import pytest
from unittest.mock import MagicMock, patch
from serviceBot.services.rag import FAQService

def test_rag_index_text():
    mock_collection = MagicMock()
    faq = FAQService(collection=mock_collection)
    
    # Index some text
    num_chunks = faq.index_text("Hello world. " * 100, "test_doc.txt")
    
    assert num_chunks > 0
    assert mock_collection.add.called
    _, kwargs = mock_collection.add.call_args
    assert "test_doc.txt" in kwargs["ids"][0]
    assert kwargs["metadatas"][0]["filename"] == "test_doc.txt"

def test_rag_delete_file():
    mock_collection = MagicMock()
    faq = FAQService(collection=mock_collection)
    
    faq.delete_file("test_doc.txt")
    mock_collection.delete.assert_called_once_with(where={"filename": "test_doc.txt"})

@patch("serviceBot.services.rag.ChatOpenAI")
def test_rag_answer_question_success(mock_chat_openai):
    """Verify answer_question queries Chroma collection and invokes ChatOpenAI."""
    mock_collection = MagicMock()
    mock_collection.count.return_value = 1
    mock_collection.query.return_value = {
        "documents": [["Test context snippet about oil change."]]
    }
    
    faq = FAQService(collection=mock_collection)
    
    mock_llm_instance = MagicMock()
    mock_chat_openai.return_value = mock_llm_instance
    
    mock_response = MagicMock()
    mock_response.content = "This is the answer from GPT."
    
    # Mock both direct call (callable) and .invoke() methods for maximum compatibility
    mock_llm_instance.invoke.return_value = mock_response
    mock_llm_instance.return_value = mock_response
    
    ans = faq.answer_question("What is an oil change?")
    assert ans == "This is the answer from GPT."
    assert mock_collection.query.called

@patch("serviceBot.services.rag.ChatOpenAI")
def test_rag_answer_question_fallback(mock_chat_openai):
    """Verify fallback response if ChatOpenAI throws an exception."""
    mock_collection = MagicMock()
    mock_collection.count.return_value = 1
    mock_collection.query.return_value = {
        "documents": [["Fallback context snippet here."]]
    }
    
    faq = FAQService(collection=mock_collection)
    
    # ChatOpenAI throws exception on invoke
    mock_llm_instance = MagicMock()
    mock_llm_instance.invoke.side_effect = Exception("OpenAI API Key expired")
    mock_llm_instance.side_effect = Exception("OpenAI API Key expired")
    mock_chat_openai.return_value = mock_llm_instance
    
    # Should fall back to return the retrieved context snippet directly
    ans = faq.answer_question("Any question?")
    assert "Fallback context snippet here." in ans
