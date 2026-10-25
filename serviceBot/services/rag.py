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
        Guarantees that live database service catalog facts take absolute precedence over
        retrieved documents and during model failure fallbacks.
        """
        import re

        with self.operation_lock:
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
        docs = results.get("documents", [[]])[0] if results and "documents" in results else []
        metas = results.get("metadatas", [[]])[0] if results and "metadatas" in results and results["metadatas"] else []

        # Dynamically retrieve the actual services catalog from the database
        db_services_loaded = False
        db_error = None
        rows = []
        try:
            from serviceBot.db.connection import get_db_connection, dict_cursor
            with get_db_connection() as conn:
                with dict_cursor(conn) as cursor:
                    cursor.execute("SELECT name, description, price_range, duration_minutes FROM services")
                    rows = [dict(r) for r in cursor.fetchall()]
            db_services_loaded = True
        except Exception as e:
            db_error = e

        # Database failure handling: report catalogue as unavailable rather than falling back to stale docs
        if not db_services_loaded:
            services_context = (
                "CRITICAL SYSTEM STATUS: The live service catalog database is currently unavailable due to a database connection error.\n"
                "You MUST NOT quote or state service offerings, prices, or durations from any uploaded documents.\n"
                "If the customer is asking about services, prices, or durations, answer strictly: "
                "'Service catalog information is currently unavailable due to a database connection error. Please try again later.'"
            )
            filtered_snippets = [doc for i, doc in enumerate(docs) if (metas[i] if i < len(metas) else {}).get("filename") != "auto_services_catalog.txt"]
            context_snippets = [services_context] + filtered_snippets
            context = "\n".join(context_snippets)
        elif rows:
            db_services = []
            for row in rows:
                desc = f" ({row['description']})" if row.get('description') else ""
                price = f" - Price: {row['price_range']}" if row.get('price_range') else ""
                duration = f" - Duration: {row['duration_minutes']} minutes" if row.get('duration_minutes') else ""
                db_services.append(f"- {row['name']}{desc}{price}{duration}")
            services_context = "Actual Available Services (from the live service catalog):\n" + "\n".join(db_services)
            filtered_snippets = [doc for i, doc in enumerate(docs) if (metas[i] if i < len(metas) else {}).get("filename") != "auto_services_catalog.txt"]
            context_snippets = [services_context] + filtered_snippets
            context = "\n".join(context_snippets)
        else:
            # Empty catalog: must remain authoritative
            services_context = "Actual Available Services (from the live service catalog):\nNo services are currently listed in the catalog."
            filtered_snippets = [doc for i, doc in enumerate(docs) if (metas[i] if i < len(metas) else {}).get("filename") != "auto_services_catalog.txt"]
            context_snippets = [services_context] + filtered_snippets
            context = "\n".join(context_snippets)
            
        # Initialize ChatOpenAI for answering the user question
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        
        from serviceBot.api.portal import load_config
        config = load_config()
        base_prompt = config.get("system_prompt", "You are a helpful customer service FAQ assistant for the configured business.")
        
        authoritative_instructions = (
            "\n\nAUTHORITATIVE SERVICE CATALOG RULES:\n"
            "The live service catalog above is the single, absolute source of truth for all service offerings, names, prices, and durations.\n"
            "If any uploaded document or search snippet contains conflicting prices, older figures, or contradicts the live catalog, "
            "you MUST strictly use and state the live service catalog details.\n"
            "If a service is NOT listed in the live service catalog above, it is NOT offered. Never quote prices, durations, or availability from uploaded documents for services not listed in the live catalog.\n"
            "If the live catalog is empty, you must state that no services are currently listed.\n"
        )

        faq_prompt = base_prompt + authoritative_instructions
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
            # Model failure fallback: NEVER substitute stale retrieved facts over live catalog
            if not db_services_loaded:
                return "Service catalog information is currently unavailable due to a database connection error. Please try again later."

            # Check if requested service is unambiguously identified in live rows
            matched_services = []
            q_clean = question.lower()
            for r in rows:
                name_clean = r["name"].lower()
                if re.search(rf"\b{re.escape(name_clean)}\b", q_clean):
                    matched_services.append(r)

            if len(matched_services) == 1:
                r = matched_services[0]
                price_desc = f"is {r['price_range']}" if r.get('price_range') else "pricing is available upon request"
                dur_desc = f" (Duration: {r['duration_minutes']} minutes)" if r.get('duration_minutes') else ""
                return f"{r['name']} {price_desc}{dur_desc}."

            if not rows:
                return "No services are currently listed in the catalog."

            # Service is not unambiguously identified or general question failed
            return "I'm sorry, I'm currently unable to retrieve that information. Please try again later."

    def index_text(self, text: str, filename: str, generation: int = None) -> int:
        """Add chunks while serializing the shared embedding implementation."""
        with self.operation_lock:
            return len(self._add_text(text, filename, generation=generation))

    def _add_text(self, text: str, filename: str, generation: int = None) -> list[str]:
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
        meta = {"filename": filename}
        if generation is not None:
            meta["generation"] = int(generation)
        metadatas = [dict(meta) for _ in range(len(chunks))]
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

    def replace_text(self, text: str, filename: str, generation: int = None) -> int:
        """Keep prior searchable chunks until replacement embedding succeeds."""
        with self.operation_lock:
            old_ids = self.collection.get(where={"filename": filename}, include=[])['ids']
            new_ids = self._add_text(text, filename, generation=generation)
            if not new_ids:
                raise ValueError("Replacement knowledge must contain searchable text")
            if old_ids:
                self.collection.delete(ids=old_ids)
            return len(new_ids)

    def delete_file(self, filename: str):
        """Delete only this document under the shared collection boundary."""
        with self.operation_lock:
            self.collection.delete(where={"filename": filename})
