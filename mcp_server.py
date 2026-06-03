# This file is an MCP (Model Context Protocol) server.
# It provides tools that the AI agent can call to do tasks like
# managing Jira tickets.
#
# The @mcp.tool() line above each function tells the MCP system
# that this function is a "tool" the AI can use.

import os
from answer_app_from_jira_rag import AnswerAppFromJiraRag
from jira import JIRA                            # library to talk to Jira
from mcp.server.fastmcp import FastMCP            # MCP server framework



# Create the MCP server with a name
mcp = FastMCP("MCP Tools")


# ----------------------------------------------------------------------
# JIRA HELPERS
# ----------------------------------------------------------------------

def _get_jira_client() -> JIRA:
    """Creates a connection to Jira using credentials from environment variables."""
    jira_url = os.environ["JIRA_URL"]
    jira_user = os.environ["JIRA_USER"]
    jira_token = os.environ["JIRA_API_TOKEN"]
    return JIRA(server=jira_url, basic_auth=(jira_user, jira_token))


# ----------------------------------------------------------------------
# MATH TOOL
# ----------------------------------------------------------------------

@mcp.tool()
def math_numbers(operation: str, a: float, b: float) -> float:
    """Does math operation on two numbers and returns the result."""
    if operation == "add":
        return a + b
    elif operation == "substract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "devide":
        return a / b
    else:
        return 0


# ----------------------------------------------------------------------
# JIRA TOOLS
# ----------------------------------------------------------------------

@mcp.tool()
def get_jira_ticket(ticket_key: str) -> str:
    """Fetches a Jira ticket by key (e.g. KAN-2) and returns its summary and status."""
    issue = _get_jira_client().issue(ticket_key)
    status = issue.fields.status.name if issue.fields.status else "Unknown"
    return f"{issue.key}: {issue.fields.summary} (description:{issue.fields.description}) (status: {status})"


@mcp.tool()
def add_jira_ticket(title: str, description: str, issue_type: str) -> str:
    """Creates a Jira ticket and returns a confirmation message."""
    new_issue = _get_jira_client().create_issue(
        project="KAN",
        summary=title,
        description=description,
        issuetype={"name": issue_type},
    )
    return f"Jira ticket {new_issue.key} created with title: '{title}'"


@mcp.tool()
def add_jira_comment(ticket_key: str, comment: str) -> str:
    """Adds a comment to an existing Jira ticket and returns a confirmation."""
    _get_jira_client().add_comment(ticket_key, comment)
    return f"Comment added to Jira ticket {ticket_key}"


@mcp.tool()
def update_jira_ticket_status(ticket_key: str, target_status: str) -> str:
    """Updates the status of a Jira ticket (e.g. 'In Progress', 'Done')."""
    jira = _get_jira_client()
    transitions = jira.transitions(ticket_key)
    for t in transitions:
        if t['name'].lower() == target_status.lower():
            jira.transition_issue(ticket_key, t['id'])
            return f"Jira ticket {ticket_key} transitioned to '{t['name']}'"
    available = [t['name'] for t in transitions]
    return f"Transition to '{target_status}' not available. Available transitions for {ticket_key}: {', '.join(available)}"

@mcp.tool()
def answer_question(question: str,history: list) -> str:
    """Answers a question using the RAG agent for any question not related to Jira tickets operations or math operations"""
    rag_agent = AnswerAppFromJiraRag()
    answer, doc_retrived = rag_agent.chat_with_jira_agent(message=question,history=history)
    return answer
    


if __name__ == "__main__":
    mcp.run(transport="stdio")