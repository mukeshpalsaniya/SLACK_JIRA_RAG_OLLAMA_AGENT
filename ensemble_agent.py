# ensemble_agent.py
import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Pydantic AI Core Imports
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

load_dotenv(override=True)

MCP_SERVER_SCRIPT = Path(__file__).resolve().parent / "mcp_server.py"

SYSTEM_PROMPT = (
    """You are an expert AI assistant for "Salesforce CRM Application" Your role is to help users with Salesforce CRM Application inquiries and any business process questions that have answers in the Rag agent, and manage support tickets using your integrated Jira tools.

## Core Capabilities
1. Answer customer and operational questions strictly using the ticket data provided to you.
2. Answer any question not related to Jira tickets operations or math operations using the tool 'answer_question' that uses the Rag agent to answer the question.
3. **General & Operational Inquiries**: For any question not related to Jira tickets operations or math operations, you MUST use the tool 'answer_question'. 
  - Pass the active user message as the `user_query` argument.
  - **Crucial**: You must pass the compiled conversational history from your active message payload context directly into the `history` argument so the RAG agent retains memory of previous turns. Do not leave the history argument empty if past turns exist.
4. Create new Jira tickets for Application/process issues, complaints, or suggestions using the `add_jira_ticket` tool.
5. Utilize direct programmatic access to Jira system tools.
6. Always fetch existing ticket details to verify context before modifying any ticket.

## Rules & Guidelines
- **Tone**: Maintain a friendly, helpful, and polite attitude at all times.
- **Application Inquiries**: Base your answers *only* on the provided ticket data. Do not make up or assume details about Mario's Pizza. If the information is missing from the ticket, state honestly that you do not know.
- **Jira Ticket Creation**: For any restaurant-related issue, customer complaint, or improvement suggestion, invoke the `add_jira_ticket` tool. 
  - Synthesize an appropriate **title** and **description** based on the user's input.
  - Set the ticket type strictly as **"Task"**.
  - **Crucial**: Once the ticket is successfully created, you must include the newly generated ticket number in your final response to the user.
- **Honesty**: If you do not know something or lack the data to answer, admit it honestly.
"""
)

# --- INTERNAL ENVIRONMENT CONFIGURATIONS ---
def get_jira_credentials() -> tuple[str, str, str]:
    jira_url = os.environ.get("JIRA_URL", "https://dexter0711.atlassian.net")
    jira_user = os.environ.get("JIRA_USER")
    jira_token = os.environ.get("JIRA_API_TOKEN")

    if not jira_user or not jira_token:
        raise ValueError("Set JIRA_USER and JIRA_API_TOKEN in your .env file before running.")
    return jira_url, jira_user, jira_token

def create_mcp_server() -> MCPServerStdio:
    jira_url, jira_user, jira_token = get_jira_credentials()
    mcp_env = {
        **os.environ,
        "JIRA_URL": jira_url,
        "JIRA_USER": jira_user,
        "JIRA_API_TOKEN": jira_token,
    }
    return MCPServerStdio(
        command=sys.executable,
        args=[str(MCP_SERVER_SCRIPT)],
        env=mcp_env,
        cwd=str(MCP_SERVER_SCRIPT.parent),
    )

def create_model() -> OpenAIChatModel:
    ollama_url = "http://localhost:11434/v1"
    ollama_key = "ollama"
    ollama_provider = OpenAIProvider(base_url=ollama_url, api_key=ollama_key)
    model_name = "gemma4:31b-cloud"
    return OpenAIChatModel(model_name=model_name, provider=ollama_provider)

def create_agent(mcp_server: MCPServerStdio) -> Agent:
    return Agent(
        model=create_model(),
        system_prompt=SYSTEM_PROMPT,
        toolsets=[mcp_server],
    )


# --- SLACK PLUGGING ROUTER LAYER ---
def map_slack_history_to_pydantic_ai(slack_history: list) -> list:
    """
    Transforms standard [{"role": "user/assistant", "content": "..."}] history 
    into correct Pydantic AI ModelMessage structures so your local model tracks context safely.
    """
    pydantic_messages = []
    for msg in slack_history:
        role = msg.get("role")
        content = msg.get("content", "")
        
        if role == "user":
            # Users submit ModelRequests wrapping a UserPromptPart
            pydantic_messages.append(
                ModelRequest(parts=[UserPromptPart(content=content)])
            )
        elif role == "assistant":
            # The model outputs ModelResponses wrapping a TextPart
            pydantic_messages.append(
                ModelResponse(parts=[TextPart(content=content)])
            )
            
    return pydantic_messages

async def execute_agent_thinking_pipeline(slack_history: list) -> str:
    """
    Asynchronously boots the MCP context engine instance, converts 
    Slack thread tokens, runs tool checking pipelines, and returns back raw strings.
    """
    if not slack_history:
        return "🤖 No conversation context found to compute."

    # 1. Pop out the most recent user prompt message to feed as the main driver
    last_message = slack_history[-1].get("content", "")
    
    # 2. Extract past context message structures (excluding the active current message prompt)
    past_history = slack_history[:-1]
    pydantic_history_payload = map_slack_history_to_pydantic_ai(past_history)
    
    # 3. Securely hook onto the MCP local subprocess runner
    mcp_server = create_mcp_server()
    mcp_server.timeout = 30.0 # 30 seconds timeout to prevent hanging
    
    async with mcp_server as connected_server:
        # Create a fresh context instance bound to your Ollama runtime
        agent = create_agent(connected_server)
        try:
            # 4. Trigger the multi-tool check execution
            result = await agent.run(
                last_message, 
                message_history=pydantic_history_payload
            )
            return result.output or "🤖 System computed correctly but produced no text output output summary."
        except Exception as e:
            return f"❌ Agent Failure executing request processing loop: {str(e)}"

def process_ensemble_thinking(slack_history: list) -> str:
    """
    Synchronous structural bridge called directly inside your synchronous 
    Slack Bolt handler thread loop blocks.
    """
    return asyncio.run(execute_agent_thinking_pipeline(slack_history))
