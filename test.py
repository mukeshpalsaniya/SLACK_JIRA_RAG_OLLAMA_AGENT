from sentence_transformers import SentenceTransformer

# Point directly to your manual download directory
local_dir = r"D:\ai\slack_jira_rag_agent\all-MiniLM-L6-v2"

print("Loading model entirely offline...")
model = SentenceTransformer(local_dir)
print("🎉 Success! Model loaded from browser files perfectly!")