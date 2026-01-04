# LangChain Agent 核心大脑代码分析

基于 LangChain v1.2.0+ 的源码分析，Agent 架构已从传统的 `AgentExecutor` 演进为基于 **LangGraph** 的图架构。

## 1. 架构演进

在新的架构中，Agent 的“大脑”不再是一个单独的类，而是由 **图中的一个节点（Node）** 和 **条件边（Conditional Edge）** 共同构成的。核心逻辑位于 `langchain.agents.factory` 模块中。

## 2. 核心大脑：`model_node`

`model_node` 函数承担了 Agent 的“思考”职责。它直接调用 LLM，传入当前的状态（消息历史），并获取 LLM 的决策。

```python
# 源码位置: langchain/agents/factory.py
def model_node(state: AgentState, runtime: Runtime[ContextT]) -> dict[str, Any]:
    """Sync model request handler with sequential middleware processing."""
    request = ModelRequest(
        model=model,
        messages=state["messages"], # 获取历史上下文
        # ...
    )
    # ... 执行 LLM 调用 ...
    response = _execute_model_sync(request)
    
    # 返回 LLM 的决策结果（包含文本回复或工具调用请求）
    return {"messages": response.result}
```

**分析**：Agent 的“思考”过程本质上就是 LLM 的一次推理（Inference）。`model_node` 封装了这个过程，将输入状态转换为新的消息更新。

## 3. 决策逻辑：条件边 (Routing)

Agent 如何决定“下一步做什么”（是结束还是调用工具）？这部分逻辑被定义在图的**条件边**中，具体实现在 `_make_model_to_tools_edge` 函数里。

```python
# 源码位置: langchain/agents/factory.py
def _make_model_to_tools_edge(...):
    def model_to_tools(state: dict[str, Any]) -> str | list[Send] | None:
        last_ai_message, tool_messages = _fetch_last_ai_and_tool_messages(state["messages"])
        
        # 决策 1: 如果 LLM 没有请求调用工具，则结束 (END)
        if len(last_ai_message.tool_calls) == 0:
            return end_destination
            
        # 决策 2: 如果有待处理的工具调用，跳转到工具节点 ("tools")
        # 过滤掉已经执行过的工具调用
        pending_tool_calls = [
            c for c in last_ai_message.tool_calls
            if c["id"] not in tool_message_ids ...
        ]
        
        if pending_tool_calls:
            return [
                Send(
                    "tools",
                    ToolCallWithContext(
                        __type="tool_call_with_context",
                        tool_call=tool_call,
                        state=state,
                    ),
                )
                for tool_call in pending_tool_calls
            ]
            
        # ...
```

**分析**：这是 Agent 的“判断力”。它检查 LLM 的输出：
*   如果 LLM 输出包含 `tool_calls`，路由到 `tools` 节点执行工具。
*   如果 LLM 输出仅包含文本内容，路由到 `END` 节点结束当前交互。

## 4. 执行循环：`StateGraph`

`create_agent` 函数通过构建 `StateGraph` 来定义整个执行循环。

```python
# 源码位置: langchain/agents/factory.py
def create_agent(...):
    # ...
    graph = StateGraph(...)

    # 1. 添加节点：大脑(model) 和 手脚(tools)
    graph.add_node("model", ...)
    if tool_node is not None:
        graph.add_node("tools", tool_node)

    # 2. 定义循环：启动 -> 大脑
    graph.add_edge(START, entry_node) # 通常 entry_node 就是 "model"

    # 3. 定义大脑后的去向：去工具还是结束？
    graph.add_conditional_edges(
        "model",
        RunnableCallable(_make_model_to_tools_edge(...)),
        ["tools", END, "model"]
    )

    # 4. 定义工具后的去向：工具执行完后，通常回到大脑进行下一次思考
    graph.add_conditional_edges(
        "tools",
        RunnableCallable(_make_tools_to_model_edge(...)),
        ["model", END]
    )
    
    return graph.compile(...)
```

## 5. 总结

现代 LangChain Agent 的核心机制可以概括为：

1.  **输入**: 用户消息 + 历史记录 (`state["messages"]`)
2.  **思考 (Thinking)**: `model_node` 调用 LLM 生成 `AIMessage`。
3.  **决策 (Routing)**: `_make_model_to_tools_edge` 检查 `AIMessage.tool_calls`。
4.  **行动 (Acting)**: 如果有工具调用，进入 `tools` 节点执行。
5.  **观察 (Observing)**: 工具执行结果作为 `ToolMessage` 添加到历史记录。
6.  **循环**: 带着新的 `ToolMessage` 再次进入 `model_node`，让 LLM 根据观察结果继续思考。

这种基于图（Graph）的设计比以前的类继承方式更加灵活，更容易调试，并且天然支持更复杂的控制流（如人机回环 HITL、并行执行等）。
