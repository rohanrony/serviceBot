import os
from serviceBot.services.rag import FAQService

def index_all_kb():
    service = FAQService()
    kb_dir = "kb_documents"
    if not os.path.exists(kb_dir):
        print(f"Error: {kb_dir} directory does not exist.")
        return

    for filename in os.listdir(kb_dir):
        file_path = os.path.join(kb_dir, filename)
        if os.path.isfile(file_path) and filename.endswith(".txt"):
            print(f"Indexing {filename}...")
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Delete first to allow clean overwrite
            service.delete_file(filename)
            chunks = service.index_text(content, filename)
            print(f"Indexed {chunks} chunks from {filename}.")

if __name__ == "__main__":
    index_all_kb()
