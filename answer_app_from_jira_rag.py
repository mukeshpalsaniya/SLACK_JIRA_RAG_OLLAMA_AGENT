import os
import chromadb
import ollama
from sentence_transformers import SentenceTransformer

class AnswerAppFromJiraRag():

    LLM_MODEL = "gemma4:31b-cloud"
    EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self):
        self.embedding_model = SentenceTransformer(self.EMBEDDING_MODEL_NAME)
        # print("Connecting to local ChromaDB knowledge base...")
        chroma_client = chromadb.PersistentClient(path="./jira_knowledge_base")
        self.collection = chroma_client.get_or_create_collection(name="jira_tickets")
        # print(f"Connected to ChromaDB collection: {self.collection}")

    # ==========================================
    # 2. CONVERSATIONAL RAG LOGIC 
    # ==========================================
    def chat_with_jira_agent(self,message, history: list):
        """Processes conversational turns, keeping track of history and updating documents."""
        # Safe Extraction: Convert dictionary or None objects into a clean string
        user_question = ""
        if message is None:
            user_question = ""
        elif isinstance(message, dict):
            user_question = str(message.get("text", "")).strip()
        else:
            user_question = str(message).strip()
            
        if not user_question:
            return "Please enter a valid question.", "*No query processed.*"
            
        # Generate query vector from user's text
        query_vector = self.embedding_model.encode(user_question).tolist()
        
        # Retrieve top 5 matching chunks
        results = self.collection.query(
            query_embeddings=[query_vector], 
            n_results=5
        )
        
        # CRITICAL FIX: Add [0] to flatten Chroma's nested tracking matrix list layers
        retrieved_docs = results['documents'][0] if (results['documents'] and results['documents'][0]) else []
        retrieved_meta = results['metadatas'][0] if (results['metadatas'] and results['metadatas'][0]) else []
        # print(f"Retrived docs: {retrieved_docs}")
        # print(f"\n\nRetrived metadata: {retrieved_meta}")
        if not retrieved_docs:
            return "I couldn't find any historical support tickets related to your query.", "*No matching reference documents found.*"

        # Format raw docs for the right-hand sidebar UI container ONLY
        formatted_docs_list = []
        for i, doc in enumerate(retrieved_docs):
            source_info = retrieved_meta[i].get('key', f"Chunk {i+1}") if i < len(retrieved_meta) else f"Chunk {i+1}"
            formatted_docs_list.append(f"### 📑 Source: {source_info}\n```text\n{doc}\n```")
        
        docs_sidebar_content = "\n\n---\n\n".join(formatted_docs_list)

        # Format context blocks and compile historical conversation memory for Ollama
        context_str = "\n\n---\n\n".join(retrieved_docs)
        sources = list(set([meta.get('key') for meta in retrieved_meta if isinstance(meta, dict) and 'key' in meta]))
        
        # Initialize messages with System instructions
        messages = [
            {
                "role": "system", 
                "content": (
                    "You are an expert internal Application support agent. Answer the user's question "
                    "using ONLY the historical Jira support tickets provided below. If the text "
                    "doesn't contain the solution, don't show the which tickets you checked and just say 'I cannot find a historical solution for this.'\n"
                    "Incorporate context from past messages in the conversation history if relevant.\n\n"
                    f"HISTORICAL JIRA TICKETS:\n{context_str}"
                )
            }
        ]
        
        # Safely parse history items based on Gradio's format
        for msg in history:
            if isinstance(msg, dict):
                messages.append({
                    "role": msg.get("role"),
                    "content": str(msg.get("content"))
                })
            elif isinstance(msg, (list, tuple)) and len(msg) == 2:
                messages.append({"role": "user", "content": str(msg[0])})
                messages.append({"role": "assistant", "content": str(msg[1])})
                
        # Append the current active question payload turn
        messages.append({"role": "user", "content": user_question})
        
        try:
            # Run local Ollama generation pass
            response = ollama.chat(model=self.LLM_MODEL, messages=messages, options={"temperature": 0.1})
            answer = response['message']['content']
            
            # Appended exactly ONCE right here before returning to the chatbot box UI
            source_string = f"\n\n**Sources checked:** {', '.join(sources)}" if sources else ""
            final_answer = f"{answer}{source_string}"
            
            return final_answer, docs_sidebar_content
            
        except Exception as e:
            return f" Error communicating with local Ollama engine: {str(e)}", docs_sidebar_content

    



