"""An agent wired to a destructive tool with NO human in the loop.

Run:  handbrake examples/ungated.py   ->  exits 1 (HB001).

The agent is given a ``delete_customer`` tool that permanently drops a row, and
an ``AgentExecutor`` is built around it. Nothing gates the destructive call: no
approval step, no confirmation, no human-in-the-loop. If the model decides to
call ``delete_customer``, the row is gone — autonomously and irreversibly.

The read-only ``get_customer`` tool right next to it is NOT flagged: read-only
tools never fire, which is the whole point of keeping the check low-noise.
"""

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.tools import tool


@tool
def get_customer(customer_id: str) -> dict:
    """Read a customer record. Read-only — handbrake never flags this."""
    return db.query("SELECT * FROM customers WHERE id = ?", customer_id)


@tool
def delete_customer(customer_id: str) -> str:
    # HB001: a destructive tool exposed to an autonomous agent, no approval gate.
    db.execute("DELETE FROM customers WHERE id = ?", customer_id)
    return f"deleted {customer_id}"


def build(llm, prompt):
    agent = create_tool_calling_agent(llm, [get_customer, delete_customer], prompt)
    return AgentExecutor(agent=agent, tools=[get_customer, delete_customer])
