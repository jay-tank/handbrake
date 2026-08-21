from models import HB001, HB002
from scanner import scan_source


def _rules(findings):
    return {f.rule for f in findings}


# --- HB001 blockers: destructive tool + autonomous agent, no approval -------
def test_langchain_destructive_tool_with_executor_is_hb001():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def delete_user(uid):\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[delete_user])\n"
    )
    findings = scan_source(src, "u.py")
    hb001 = [f for f in findings if f.rule == HB001]
    assert len(hb001) == 1
    assert hb001[0].severity == "blocker"
    assert "delete_user" in hb001[0].message


def test_crewai_destructive_tool_with_crew_is_hb001():
    src = (
        "from crewai import Crew, Agent\n"
        "from crewai.tools import tool\n"
        "@tool\n"
        "def refund_payment(charge_id):\n"
        "    stripe.Refund.create(charge=charge_id)\n"
        "def build(agents, tasks):\n"
        "    return Crew(agents=agents, tasks=tasks)\n"
    )
    assert HB001 in _rules(scan_source(src, "u.py"))


def test_autogen_register_destructive_with_initiate_chat_is_hb001():
    src = (
        "import autogen\n"
        "def send_email(to, body):\n"
        "    smtp.sendmail('me', to, body)\n"
        "def go(user, assistant, msg):\n"
        "    autogen.register_function(send_email, caller=assistant, executor=user)\n"
        "    user.initiate_chat(assistant, message=msg, human_input_mode='NEVER')\n"
    )
    assert HB001 in _rules(scan_source(src, "u.py"))


def test_llamaindex_functiontool_with_runner_is_hb001():
    src = (
        "from llama_index.core.agent import AgentRunner\n"
        "from llama_index.core.tools import FunctionTool\n"
        "def drop_table(name):\n"
        "    engine.execute('DROP TABLE ' + name)\n"
        "def build(llm):\n"
        "    t = FunctionTool.from_defaults(fn=drop_table)\n"
        "    return AgentRunner(tools=[t], llm=llm)\n"
    )
    assert HB001 in _rules(scan_source(src, "u.py"))


def test_openai_tools_list_run_with_shell_is_hb001():
    src = (
        "import openai\n"
        "def run_shell(cmd):\n"
        "    import subprocess\n"
        "    subprocess.run(cmd, shell=True)\n"
        "def go(client):\n"
        "    client.chat.completions.create(model='gpt-4o', messages=[], tools=[run_shell])\n"
    )
    assert HB001 in _rules(scan_source(src, "u.py"))


def test_body_destructive_name_neutral_still_hb001():
    # Name is neutral ('process') but body deletes a file -> destructive by body.
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "import os\n"
        "@tool\n"
        "def process(path):\n"
        "    os.remove(path)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[process])\n"
    )
    assert HB001 in _rules(scan_source(src, "u.py"))


def test_http_delete_tool_is_hb001():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "import requests\n"
        "@tool\n"
        "def wipe_resource(url):\n"
        "    requests.delete(url)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[wipe_resource])\n"
    )
    assert HB001 in _rules(scan_source(src, "u.py"))


# --- HB002 warnings: destructive tool defined, wiring uncertain -------------
def test_destructive_tool_no_executor_is_hb002():
    src = (
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def deploy_service(name):\n"
        "    subprocess.run(['kubectl', 'apply', '-f', name])\n"
    )
    findings = scan_source(src, "u.py")
    assert HB002 in _rules(findings)
    assert HB001 not in _rules(findings)


def test_tool_wrapper_without_executor_is_hb002():
    src = (
        "from langchain_core.tools import Tool\n"
        "def charge_card(amount):\n"
        "    stripe.Charge.create(amount=amount)\n"
        "t = Tool(name='charge', func=charge_card, description='x')\n"
    )
    assert HB002 in _rules(scan_source(src, "u.py"))


# --- clean cases -----------------------------------------------------------
def test_approval_marker_short_circuits():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "from langgraph.types import interrupt\n"
        "@tool\n"
        "def delete_user(uid):\n"
        "    decision = interrupt({'uid': uid})\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[delete_user])\n"
    )
    assert scan_source(src, "u.py") == []


def test_require_approval_kwarg_short_circuits():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def delete_user(uid):\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[delete_user], require_approval=True)\n"
    )
    assert scan_source(src, "u.py") == []


def test_human_input_mode_always_short_circuits():
    src = (
        "import autogen\n"
        "def delete_user(uid):\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "def go(user, assistant, msg):\n"
        "    autogen.register_function(delete_user, caller=assistant, executor=user)\n"
        "    user.initiate_chat(assistant, message=msg, human_input_mode='ALWAYS')\n"
    )
    assert scan_source(src, "u.py") == []


def test_readonly_tool_never_fires():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def get_customer(cid):\n"
        "    return db.query('SELECT * FROM customers WHERE id=%s', cid)\n"
        "@tool\n"
        "def search_orders(q):\n"
        "    return db.query('SELECT * FROM orders WHERE name LIKE %s', q)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[get_customer, search_orders])\n"
    )
    assert scan_source(src, "u.py") == []


def test_no_agent_framework_stays_quiet():
    # Destructive registered-looking tool but no agent framework imported.
    src = (
        "def delete_user(uid):\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "tools = [delete_user]\n"
    )
    assert scan_source(src, "u.py") == []


def test_unregistered_destructive_function_is_ignored():
    # delete_user is never registered as a tool -> not an agent tool.
    src = (
        "from langchain.agents import AgentExecutor\n"
        "def delete_user(uid):\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[])\n"
    )
    assert scan_source(src, "u.py") == []


def test_inline_ignore_suppresses():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def delete_user(uid):  # handbrake: ignore\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[delete_user])\n"
    )
    assert scan_source(src, "u.py") == []


def test_noqa_with_rule_suppresses():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def delete_user(uid):  # noqa: HB001\n"
        "    db.execute('DELETE FROM users WHERE id=%s', uid)\n"
        "def build(agent):\n"
        "    return AgentExecutor(agent=agent, tools=[delete_user])\n"
    )
    assert scan_source(src, "u.py") == []


def test_unknown_extension_is_ignored():
    src = (
        "from langchain.agents import AgentExecutor\n"
        "from langchain_core.tools import tool\n"
        "@tool\n"
        "def delete_user(uid):\n"
        "    db.execute('DELETE FROM users')\n"
    )
    assert scan_source(src, "notes.txt") == []
