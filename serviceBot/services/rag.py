import os
from threading import RLock
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["CHROMA_TELEMETRY_IMPL"] = "None"
import chromadb
from chromadb.api.types import DefaultEmbeddingFunction
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from serviceBot.logger import get_logger

logger = get_logger("services.rag")

EMBEDDING_ADD_BATCH_SIZE = 1
_DEFAULT_ENCODER = None


class _SingleThreadOnnxRuntime:
    """Bound only this encoder's session options; leave the runtime untouched."""

    def __init__(self, runtime):
        self._runtime = runtime

    def __getattr__(self, name):
        if name == "SessionOptions":
            return self._session_options
        return getattr(self._runtime, name)

    def _session_options(self):
        options = self._runtime.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        return options


class _ProcessDefaultEmbeddingFunction(DefaultEmbeddingFunction):
    """Chroma's default identity with one lazy encoder for this process."""

    def __call__(self, input):
        global _DEFAULT_ENCODER
        with FAQService.operation_lock:
            if _DEFAULT_ENCODER is None:
                from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
                    ONNXMiniLM_L6_V2,
                )
                encoder = ONNXMiniLM_L6_V2()
                encoder.ort = _SingleThreadOnnxRuntime(encoder.ort)
                _DEFAULT_ENCODER = encoder
            return _DEFAULT_ENCODER(input)

    @staticmethod
    def build_from_config(config):
        DefaultEmbeddingFunction.validate_config(config)
        return _ProcessDefaultEmbeddingFunction()

class FAQService:
    operation_lock = RLock()

    def __init__(self, collection=None):
        """
        Initializes the FAQService.
        By default, it uses an in-process persistent ChromaDB client pointing to ./chroma_db.
        If a collection is explicitly passed (e.g. in tests), it uses that collection instead.
        """
        with self.operation_lock:
            if collection is not None:
                self.collection = collection
            else:
                import sys
                is_testing = "pytest" in sys.modules or any("pytest" in arg or "unittest" in arg for arg in sys.argv)
                path = "./scratch/chroma_db" if is_testing else "./chroma_db"
                client = chromadb.PersistentClient(path=path)
                self.collection = client.get_or_create_collection("faq_collection", embedding_function=_ProcessDefaultEmbeddingFunction())

    def answer_question(self, question: str) -> str:
        """
        Queries the vector database for the closest semantic chunks and passes them
        as context to ChatOpenAI, ensuring strict adherence to context without hallucination.
        """
        with self.operation_lock:
            # Query ChromaDB collection for matches
            try:
                count = self.collection.count()
                n_results = max(1, min(20, count))
            except Exception:
                n_results = 2
            
            results = self.collection.query(
                query_texts=[question],
                n_results=n_results
            )
        
        # Consolidate retrieved document snippets
        context_snippets = []
        if results and "documents" in results and results["documents"]:
            context_snippets = results["documents"][0]

        # Dynamically retrieve the actual services catalog from the database
        try:
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("SELECT name, description, price_range, duration_minutes FROM services")
                    rows = cursor.fetchall()
                if rows:
                    db_services = []
                    for row in rows:
                        desc = f" ({row['description']})" if row['description'] else ""
                        price = f" - Price: {row['price_range']}" if row['price_range'] else ""
                        duration = f" - Duration: {row['duration_minutes']} minutes" if row['duration_minutes'] else ""
                        db_services.append(f"- {row['name']}{desc}{price}{duration}")
                    services_context = "Actual Available Services (from the live service catalog):\n" + "\n".join(db_services)
                    context_snippets.insert(0, services_context)
        except Exception:
            # Fall back gracefully in testing or if database is unavailable
            pass
        
        context = "\n".join(context_snippets) if context_snippets else "No relevant context found."
            
        # Initialize ChatOpenAI for answering the user question
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        
        from serviceBot.api.portal import load_config
        config = load_config()
        faq_prompt = config.get("system_prompt", "You are a helpful customer service FAQ assistant for the configured business.\nAnswer the caller's question strictly using the provided search snippets context.\nIf the answer is not contained in the context, reply with: 'I am sorry, but I do not have that information in my knowledge base.'\nDo not make up any information or hallucinate.")
        
        if "{context}" not in faq_prompt:
            faq_prompt += "\n\nContext:\n{context}"
            
        prompt = ChatPromptTemplate.from_messages([
            ("system", faq_prompt),
            ("human", "{question}")
        ])
        
        chain = prompt | llm
        
        try:
            response = chain.invoke({"context": context, "question": question})
            return response.content
        except Exception as e:
            # Return the top matching text snippets directly as a robust local fallback
            if context_snippets:
                fallback_ans = "\n\n".join([s for s in context_snippets[:2] if "Actual Available Services" not in s])
                if not fallback_ans.strip():
                    fallback_ans = context_snippets[0]
                return fallback_ans
            return f"Error querying FAQ: {str(e)}"

    def index_text(self, text: str, filename: str) -> int:
        """Add chunks while serializing the shared embedding implementation."""
        with self.operation_lock:
            return len(self._add_text(text, filename))

    def _add_text(self, text: str, filename: str) -> list[str]:
        # Split text into chunks of ~500 characters
        chunk_size = 500
        words = text.split()
        chunks = []
        current_chunk = []
        current_length = 0
        
        for word in words:
            current_chunk.append(word)
            current_length += len(word) + 1
            if current_length >= chunk_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_length = 0
        if current_chunk:
            chunks.append(" ".join(current_chunk))
            
        if not chunks:
            return []
            
        import uuid
        attempt = uuid.uuid4().hex
        ids = [f"chunk_{filename}_{attempt}_{i}" for i in range(len(chunks))]
        metadatas = [{"filename": filename} for _ in range(len(chunks))]
        try:
            for offset in range(0, len(chunks), EMBEDDING_ADD_BATCH_SIZE):
                end = offset + EMBEDDING_ADD_BATCH_SIZE
                self.collection.add(documents=chunks[offset:end],
                                    metadatas=metadatas[offset:end], ids=ids[offset:end])
        except Exception:  # Any batch may persist before raising.
            # Include the failing batch, whose acknowledgement can be unknown.
            # A cleanup error must propagate instead of reporting clean rollback.
            self.collection.delete(ids=ids)
            raise
        return ids

    def replace_text(self, text: str, filename: str) -> int:
        """Keep prior searchable chunks until replacement embedding succeeds."""
        with self.operation_lock:
            old_ids = self.collection.get(where={"filename": filename}, include=[])['ids']
            new_ids = self._add_text(text, filename)
            if not new_ids:
                raise ValueError("Replacement knowledge must contain searchable text")
            if old_ids:
                self.collection.delete(ids=old_ids)
            return len(new_ids)

    def delete_file(self, filename: str):
        """Delete only this document under the shared collection boundary."""
        with self.operation_lock:
            self.collection.delete(where={"filename": filename})
