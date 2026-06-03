import os
import sys
import json
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from answer_app_from_jira_rag import AnswerAppFromJiraRag
from ensemble_agent import process_ensemble_thinking
from dotenv import load_dotenv

load_dotenv(override=True)
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))
rag_agent = AnswerAppFromJiraRag()

# In-memory memory storage to keep track of active threads.
# Structure: {'thread_timestamp_id'}
ACTIVE_THREADS = set()

# The local JSON file path where thread state will be safely stored
DB_FILE = os.path.join(os.getcwd(), "tracked_threads.json")

# --- HELPER FUNCTIONS FOR STATE MANAGEMENT ---
def load_tracked_threads() -> set:
    """Reads the local JSON file and returns a unique set of tracked thread IDs."""
    if not os.path.exists(DB_FILE):
        return set()
    try:
        with open(DB_FILE, "r") as f:
            data = json.load(f)
            # JSON arrays load as Python lists; convert to a Set for faster lookups
            return set(data)
    except Exception as e:
        print(f"⚠️ Error loading database file: {e}", file=sys.stderr)
        return set()

def save_tracked_threads(threads_set: set):
    """Saves the current tracked thread unique set back into the local JSON file."""
    try:
        with open(DB_FILE, "w") as f:
            # Sets cannot be directly converted to JSON; convert back to a sorted list
            json.dump(list(threads_set), f, indent=4)
    except Exception as e:
        print(f"⚠️ Error saving state to database file: {e}", file=sys.stderr)


# --- SLACK THREAD HISTORY EXTRACTOR ---
def get_thread_history_for_llm(client, channel_id: str, thread_ts: str) -> list:
    """
    Fetches the raw Slack thread replies and structures them into a standard
    LLM message format: [{"role": "user/assistant", "content": "..."}]
    """
    llm_history = []
    try:
        # Call the Slack API to get all replies in the target thread
        response = client.conversations_replies(channel=channel_id, ts=thread_ts)
        messages = response.get("messages", [])

        for msg in messages:
            text = msg.get("text", "")
            
            # Identify the role based on whether a bot/app sent the message
            # If 'bot_id' or 'app_id' exists, classify it as the Assistant
            if msg.get("bot_id") or msg.get("app_id"):
                role = "assistant"
            else:
                role = "user"
                
            llm_history.append({
                "role": role,
                "content": text
            })
            
    except Exception as e:
        print(f"⚠️ Error fetching thread history from Slack: {e}", file=sys.stderr)
        
    return llm_history



# --- TRIGGER 1: Explicit Mention ---
@app.event("app_mention")
def handle_mention(event, client, say):
    """
    Triggers when someone explicitly types @YourBot.
    This registers the thread to start auto-following.
    """
    channel_id = event.get("channel")
    user_text = event.get("text")
    # Identify the unique thread ID. If it's a top-level message, use its own timestamp.
    thread_ts = event.get("thread_ts", event.get("ts"))
    # Load freshest state from the file, add the thread, and save it immediately
    active_threads = load_tracked_threads()
    active_threads.add(thread_ts)
    save_tracked_threads(active_threads)
    if thread_ts and thread_ts in active_threads:    
    
        # Pull the initial history (usually just the one mention message)
        history = get_thread_history_for_llm(client, channel_id, thread_ts)
        print(f"\n📂 Initialized Thread [{thread_ts}]. Current History for LLM:\n{json.dumps(history, indent=2)}")
    
    
    print(history)
    answer, doc_retrived = rag_agent.chat_with_jira_agent(message=user_text,history=history)
    print(answer)
    
    
    print(f"🎯 Bot mentioned. Tracking started for thread: {thread_ts}")
    
    # Agent Logic Pipeline Placeholder
    reply = f"🤖 {answer}"
    say(text=reply, thread_ts=thread_ts)


# --- TRIGGER 2: Message Listener (Auto-Follow) ---
@app.event("message")
def handle_message(event, client, say):
    """
    Fires on EVERY message in the channel. 
    We filter it down to ONLY replies inside our tracked threads.
    """
    # 1. Ignore messages sent by the bot itself to prevent infinite loops
    if event.get("bot_id") is not None:
        return
        
    # 2. Grab the thread timestamp (will be None if it's a top-level message)
    thread_ts = event.get("thread_ts")
    channel_id = event.get("channel")
    
    

    # 3. Pull current active thread records directly from disk file
    active_threads = load_tracked_threads()
    
    # 3. Check if this reply belongs to a thread we are tracking
    if thread_ts and thread_ts in active_threads:
        user_text = event.get("text")
        user_id = event.get("user")

        # Fetch the complete, sequentially ordered thread timeline history
        history = get_thread_history_for_llm(client, channel_id, thread_ts)
        
        # 2. Print or preview what will be passed directly into your LLM engine
        print(f"📦 Formatted History Payload for LLM:\n{json.dumps(history, indent=2)}")
        

        # answer, doc_retrived = rag_agent.chat_with_jira_agent(message=user_text,history=["history"])
        # print(answer)
        answer = process_ensemble_thinking(history)
        print(answer)
        
        
        print(f"🧵 Auto-following thread {thread_ts} | Message from <@{user_id}>: '{user_text}'")
        
        # Pass 'user_text' to your agent pipeline
        # reply = f"🤖 (Auto-Reply) I heard that, <@{user_id}>! Processing your thread update..."
        reply=answer
        
        say(text=reply, thread_ts=thread_ts)
    # else:
    #     reply = f"🤖 (Auto-Reply) I heard that, but it will not be tracked and replied"
        
    #     say(text=reply, thread_ts=thread_ts)


# if __name__ == "__main__":
#     print("⚡️ Slack Bolt Agent running in Auto-Follow Thread Mode...")
#     handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
#     handler.start()


if __name__ == "__main__":
    if not os.environ.get("SLACK_BOT_TOKEN") or not os.environ.get("SLACK_APP_TOKEN"):
        print("Error: Missing Slack tokens inside your environment configuration.", file=sys.stderr)
        sys.exit(1)
        
    import time

    print("⚡️ Slack Bolt Agent starting up...")
    
    # Run in a persistent loop so if the connection drops, it boots back up automatically
    while True:
        try:
            handler = SocketModeHandler(app, os.environ.get("SLACK_APP_TOKEN"))
            
            # 💡 CRITICAL FIX FOR WINDOWS & STABILITY:
            # ping_interval sends a heartbeat every 30 seconds to keep the pipe alive.
            # max_consecutive_ping_failures forces a fresh reconnect if Slack goes silent.
            print("⚡️ Connecting to Slack Socket Mode stream...")
            handler.connect() 
            
            # Keep the main thread alive safely
            while True:
                time.sleep(1)
                
        except (ConnectionResetError, Exception) as e:
            # Catch the Errno 10054 or SSL bad length silently, wait, and reconnect
            print(f"⚠️ Connection disrupted ({e}). Reconnecting in 10 seconds...", file=sys.stderr)
            time.sleep(10)
        except KeyboardInterrupt:
            print("\n👋 Gracefully shutting down Slack Bot listener.")
            break