import subprocess
import sys

if __name__ == "__main__":
    print("Starting Slack Jira RAG Agent...")
    
    # sys.executable ensures it uses the exact same Python environment
    subprocess.run([sys.executable, "slack_app_agent.py"])
    