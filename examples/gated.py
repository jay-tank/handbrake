"""The same job, fixed: a human approves before the destructive tool runs.

Run:  handbrake examples/gated.py   ->  exits 0 (clean).

Two things make this safe, and either one is enough for handbrake to stay
quiet:

  * A LangGraph ``interrupt`` puts a human in the loop before the tool runs —
    an approval / human-in-the-loop marker short-circuits the check.
  * ``delete_customer`` requires an explicit ``require_approval`` /
    confirmation before it performs the irreversible delete.

Because an approval / confirmation / human-in-the-loop marker is present in the
file, the destructive tool is treated as gated and is not flagged.
"""

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.tools import tool
from langgraph.types import interrupt


@tool
def delete_customer(customer_id: str, require_approval: bool = True) -> str:
    # Gated: a human must approve via the interrupt before the delete happens.
    decision = interrupt({"action": "delete_customer", "customer_id": customer_id})
    if decision != "approved":
        return "cancelled by reviewer"
    db.execute("DELETE FROM customers WHERE id = ?", customer_id)
    return f"deleted {customer_id}"


def build(llm, prompt):
    agent = create_tool_calling_agent(llm, [delete_customer], prompt)
    return AgentExecutor(agent=agent, tools=[delete_customer])
