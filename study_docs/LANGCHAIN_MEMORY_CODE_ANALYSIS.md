# LangChain Memory 代码分析

Memory（记忆）组件赋予了 Agent 在多轮交互中保持上下文连续性的能力。在 LangChain v1.2.0+ 的新架构中，Memory 的实现方式已经从 `ConversationBufferMemory` 等类逐渐过渡到基于 `ChatMessageHistory` 和 `Checkpointer` 的更灵活机制。

## 1. 核心接口：`BaseChatMessageHistory`

Memory 的本质是存储和检索历史消息。`langchain_core.chat_history.BaseChatMessageHistory` 定义了这一标准接口。

### 1.1 关键方法

```python
class BaseChatMessageHistory(ABC):
    @property
    def messages(self) -> list[BaseMessage]:
        """获取所有历史消息列表。
        这通常涉及从数据库或文件系统中读取数据。
        """

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        """批量添加消息到历史记录中。
        这是更新记忆的主要方式，通常在每一轮对话结束后调用。
        """

    def clear(self) -> None:
        """清空历史记录。"""
```

## 2. 常见实现

### 2.1 `InMemoryChatMessageHistory` (基础)

最简单的实现，将消息存储在 Python 列表（RAM）中。

```python
class InMemoryChatMessageHistory(BaseChatMessageHistory, BaseModel):
    messages: list[BaseMessage] = Field(default_factory=list)

    def add_message(self, message: BaseMessage) -> None:
        self.messages.append(message)
        
    def clear(self) -> None:
        self.messages = []
```
*   **优点**: 速度快，无需外部依赖。
*   **缺点**: 程序重启后数据丢失，不适合生产环境。

### 2.2 持久化 Memory (生产级)

LangChain 社区提供了多种持久化实现（位于 `langchain_community.chat_message_histories`），支持将记忆存储到数据库中：

*   **Redis**: `RedisChatMessageHistory` - 高性能，适合实时对话。
*   **SQL**: `SQLChatMessageHistory` - 适合关系型数据存储。
*   **MongoDB**: `MongoDBChatMessageHistory` - 适合文档型存储。
*   **File**: `FileChatMessageHistory` - 简单的本地文件存储。

## 3. 在 Agent 运行中如何使用 Memory

在旧版 `AgentExecutor` 中，Memory 是作为一个对象传入的。但在新的 **LangGraph** 架构中，Memory 的管理变得更加显式和灵活，主要通过 **State（状态）** 和 **Checkpointer（检查点）** 来实现。

### 3.1 状态管理 (State)

Agent 的“记忆”实际上就是 `StateGraph` 中的 `messages` 列表。

```python
# 定义 Agent 的状态
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    # operator.add 表示新消息会被追加到列表中，而不是覆盖
```

当 `model_node` 执行时，它会从 `state["messages"]` 中读取所有历史消息，并将其传给 LLM：

```python
# langchain/agents/factory.py 中的 model_node
request = ModelRequest(
    messages=state["messages"], # <-- 读取记忆
    # ...
)
```

### 3.2 持久化 (Checkpointer)

为了在多轮对话之间保存状态（即实现真正的长时记忆），LangGraph 引入了 `Checkpointer`。

```python
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent

# 1. 创建一个 Checkpointer (这里使用内存存储，也可以用 SQLiteSaver 等)
checkpointer = MemorySaver()

# 2. 创建 Agent 时传入 checkpointer
agent_graph = create_agent(
    model=...,
    tools=...,
    checkpointer=checkpointer
)

# 3. 运行时指定 thread_id
config = {"configurable": {"thread_id": "session_123"}}

# 第一轮对话
agent_graph.invoke({"messages": [HumanMessage("我叫小明")]}, config=config)

# 第二轮对话 (Agent 会自动加载 session_123 的历史记录)
response = agent_graph.invoke({"messages": [HumanMessage("我叫什么？")]}, config=config)
# Agent 回复: "你叫小明"
```

**工作原理**:
1.  **加载**: 在处理新消息前，`agent_graph` 会根据 `thread_id` 从 `checkpointer` 中加载之前的状态（包括历史消息）。
2.  **更新**: `model_node` 生成新回复后，将新消息追加到状态中。
3.  **保存**: 这一轮执行结束后，`agent_graph` 会自动将最新的状态保存回 `checkpointer`。

## 4. 总结

*   **Memory 的本质**: 存储 `BaseMessage` 对象序列。
*   **新旧对比**:
    *   **旧版**: 依赖 `ConversationBufferMemory` 等类，逻辑封装较深。
    *   **新版 (LangGraph)**: Memory 变成了图的 **State**，并通过 **Checkpointer** 进行持久化和会话管理。这种方式更加透明，也更容易控制（例如可以随时回滚到之前的某个状态）。
*   **使用建议**: 在开发阶段使用 `MemorySaver` (内存)，生产阶段使用 `PostgresSaver` 或 `SqliteSaver` 等持久化方案。
