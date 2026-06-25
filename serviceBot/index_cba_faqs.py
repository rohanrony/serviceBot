import os
import sys

# Ensure serviceBot is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serviceBot.services.rag import FAQService

FAQ_FILES = [
    "cba_faq_warranty.txt",
    "cba_faq_shuttle_inspection.txt",
    "cba_faq_hours_locations.txt",
    "cba_faq_about_company.txt"
]

def main():
    service = FAQService()
    kb_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kb_documents")
    
    print("Starting Test FAQ indexing process...")
    for filename in FAQ_FILES:
        filepath = os.path.join(kb_dir, filename)
        if not os.path.exists(filepath):
            print(f"Error: File {filename} not found in {kb_dir}")
            continue
            
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Clean delete existing index entries first
            service.delete_file(filename)
            chunk_count = service.index_text(content, filename)
            print(f"Successfully indexed '{filename}' ({chunk_count} chunks added).")
        except Exception as e:
            print(f"Error indexing '{filename}': {str(e)}")
            
    print("Indexing process completed successfully.")

if __name__ == "__main__":
    main()
