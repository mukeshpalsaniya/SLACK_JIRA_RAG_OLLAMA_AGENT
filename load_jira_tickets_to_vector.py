import os
from multiprocessing import Pool
import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# ==========================================
# 1. CONFIGURATION
# ==========================================
CSV_FILE_PATH = "Jira_data_with_comment.csv"  
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2" 

# ==========================================
# 2. WORKER FUNCTION FOR TEXT STRUCTURING
# ==========================================
def process_single_row_text(args):
    """Worker function to parse wide rows into chunks (No API calls here)."""
    index, row_dict, comment_cols, header_keys = args
    
    KEY_COL = header_keys['key']
    SUMMARY_COL = header_keys['summary']
    DESC_COL = header_keys['desc']
    
    key = str(row_dict.get(KEY_COL, "")).strip()
    summary = str(row_dict.get(SUMMARY_COL, "")).strip()
    description = str(row_dict.get(DESC_COL, "")).strip()
    
    if not key:
        return None
        
    # Truncate to match all-MiniLM-L6-v2's token limits comfortably
    truncated_desc = description[:1000] + "..." if len(description) > 1000 else description
    header_context = f"Ticket: {key} | Summary: {summary} | Description: {truncated_desc}\n"
    
    row_chunks = []
    chunk_count = 0
    
    for col in comment_cols:
        comment_text = str(row_dict.get(col, "")).strip()
        if comment_text and comment_text.lower() != "nan":
            chunk_count += 1
            # Keep text compact for the small model dimensions
            chunk_document = f"{header_context}Comment: {comment_text[:1500]}"
            
            row_chunks.append({
                "id": f"{key}_chunk_{chunk_count}",
                "document": chunk_document,
                "metadata": {"source": f"CSV Row {index + 2}", "key": key}
            })
            
    if chunk_count == 0:
        base_doc = header_context + "No comments available."
        row_chunks.append({
            "id": f"{key}_base",
            "document": base_doc,
            "metadata": {"source": f"CSV Row {index + 2}", "key": key}
        })
        
    return row_chunks

# ==========================================
# 3. HIGH-SPEED INGESTION ENGINE
# ==========================================
def ingest_huggingface_jira_csv():
    print(f"🔄 Reading data from {CSV_FILE_PATH}...")
    try:
        df = pd.read_csv(CSV_FILE_PATH, encoding='utf-8').fillna("")
    except FileNotFoundError:
        print(f"❌ Error: The file '{CSV_FILE_PATH}' was not found. Please check your path.")
        return

    header_keys = {'key': "Issue key", 'summary': "Summary", 'desc': "Description"}
    comment_cols = [col for col in df.columns if "comment" in str(col).lower()]
    
    tasks = [(idx, row.to_dict(), comment_cols, header_keys) for idx, row in df.iterrows()]
    
    all_documents = []
    all_metadatas = []
    all_ids = []
    
    print(f"🚀 Splitting {len(tasks)} rows into text chunks using Multi-Process Pool...")
    with Pool() as pool:
        results = list(tqdm(pool.imap(process_single_row_text, tasks), total=len(tasks)))
        
    for row_output in results:
        if row_output is not None:
            for chunk in row_output:
                all_documents.append(chunk["document"])
                all_metadatas.append(chunk["metadata"])
                all_ids.append(chunk["id"])

    if not all_documents:
        print("⚠ Operational failure: No data blocks were structured.")
        return

    # Loading the model internally inside Python's process space
    print(f"🧠 Loading internal Hugging Face model '{EMBEDDING_MODEL_NAME}'...")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    
    # Fast bulk vector computation using batches natively optimized for CPU/GPU
    print(f"⚡ Batch embedding {len(all_documents)} chunks simultaneously...")
    all_embeddings = model.encode(all_documents, batch_size=64, show_progress_bar=True)
    all_embeddings = all_embeddings.tolist()

    print(f"💾 Bulk-saving {len(all_documents)} elements to local ChromaDB file store...")
    chroma_client = chromadb.PersistentClient(path="./jira_knowledge_base")
    collection = chroma_client.get_or_create_collection(name="jira_tickets")
    
    # FIX: Batch slicing to prevent crashing on the 5,461 limit rule
    CHROMA_MAX_BATCH = 5000 
    total_records = len(all_documents)
    
    for i in range(0, total_records, CHROMA_MAX_BATCH):
        end_idx = min(i + CHROMA_MAX_BATCH, total_records)
        print(f"📦 Writing batch: records {i} to {end_idx}...")
        
        collection.upsert(
            ids=all_ids[i:end_idx],
            documents=all_documents[i:end_idx],
            metadatas=all_metadatas[i:end_idx],
            embeddings=all_embeddings[i:end_idx]
        )
        
    print("✅ High-speed Hugging Face ingestion operation complete and safely batched!")

if __name__ == "__main__":
    ingest_huggingface_jira_csv()
