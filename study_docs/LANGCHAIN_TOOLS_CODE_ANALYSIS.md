# LangChain Tools 代码分析

LangChain 中的 `Tool` 是 Agent 与外部世界交互的桥梁。Agent 本身只具备文本生成能力，通过调用 Tool，它可以执行搜索、数据库查询、API 请求等具体操作。核心定义位于 `langchain_core.tools.base.BaseTool`。

## 1. 核心类：`BaseTool`

`BaseTool` 是所有工具的抽象基类，定义了工具必须具备的属性和方法。

### 1.1 关键属性

```python
class BaseTool(RunnableSerializable[str | dict | ToolCall, Any]):
    name: str
    """工具的唯一名称，用于 Agent 识别和调用。"""
    
    description: str
    """工具的描述。LLM 会读取这个描述来决定何时以及如何使用该工具。
    Prompt 中的 "You have access to the following tools: ..." 部分通常就是由这个 description 填充的。
    """
    
    args_schema: Annotated[ArgsSchema | None, SkipValidation()] = Field(default=None)
    """参数结构定义（通常是 Pydantic 模型）。
    它定义了工具接受哪些参数、参数类型以及参数说明。
    LLM 会根据这个 schema 生成符合要求的结构化调用指令。
    """
    
    return_direct: bool = False
    """如果为 True，工具执行后的结果将直接作为 Agent 的最终回复返回给用户，而不再经过 LLM 总结。
    适用于生成图片、下载文件等不需要 LLM 再次处理的场景。
    """
```

### 1.2 核心方法

*   **`_run(self, *args, **kwargs)`**:
    这是工具执行的具体逻辑所在。所有自定义工具都需要覆盖这个方法来实现具体功能。
    
*   **`_arun(self, *args, **kwargs)`**:
    异步版本的执行逻辑。如果需要在异步环境（如 FastAPI）中使用 Agent，建议实现此方法。

*   **`run` 和 `arun`**:
    这是外部调用的入口方法。它们不仅调用 `_run` / `_arun`，还负责：
    *   **参数验证**: 使用 `args_schema` 验证输入参数是否合法。
    *   **回调管理 (Callbacks)**: 触发 `on_tool_start`, `on_tool_end`, `on_tool_error` 等事件，用于日志记录和监控。
    *   **错误处理**: 捕获并处理 `ToolException`。

## 2. 工具的创建方式

LangChain 提供了多种创建工具的方式，最常见的是使用 `@tool` 装饰器。

### 2.1 使用 `@tool` 装饰器 (推荐)

这是最简单的方式。LangChain 会自动从函数签名和文档字符串中提取 `name`, `description` 和 `args_schema`。

```python
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """Look up things online."""
    return "LangChain"
    
# 自动生成的属性：
# search.name -> "search"
# search.description -> "Look up things online."
# search.args_schema -> Pydantic model with 'query' field
```

### 2.2 继承 `BaseTool`

适用于逻辑复杂、需要维护状态或依赖其他组件的工具。

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(description="should be a search query")

class CustomSearchTool(BaseTool):
    name = "custom_search"
    description = "useful for when you need to answer questions about current events"
    args_schema: Type[BaseModel] = SearchInput

    def _run(self, query: str) -> str:
        return f"Search results for: {query}"
```

### 2.3 使用 `StructuredTool`

允许直接从函数创建工具，并手动指定配置。

```python
from langchain_core.tools import StructuredTool

def search_function(query: str):
    return "Results"

tool = StructuredTool.from_function(
    func=search_function,
    name="Search",
    description="useful for searching",
    # args_schema can be inferred or provided explicitly
)
```

## 3. 工具的工作流

当 Agent 决定调用工具时，流程如下：

1.  **生成指令**: LLM 输出包含工具名称和参数的文本（如 JSON 或特定格式）。
2.  **解析指令**: OutputParser 解析 LLM 的输出，提取出工具名称 (`name`) 和参数 (`tool_input`)。
3.  **参数验证**: `BaseTool.run` 接收参数，并使用 `args_schema` 验证其合法性。如果参数缺失或类型错误，可能会抛出 `ValidationError`。
4.  **执行逻辑**: 验证通过后，调用 `_run` 方法执行实际业务逻辑。
5.  **返回结果**: 执行结果（Observation）被返回给 Agent，作为下一步推理的依据。

## 4. 错误处理 (`handle_tool_error`)

工具执行可能会失败（例如网络超时、参数无效）。`BaseTool` 提供了 `handle_tool_error` 属性来控制错误处理策略：

*   **`True`**: 将异常信息作为工具的输出返回给 Agent，让 Agent 知道出错了并尝试自我修正。
*   **`False` (默认)**: 抛出异常，中断整个 Agent 执行。
*   **字符串**: 返回固定的错误提示信息。
*   **函数**: 自定义错误处理逻辑。

```python
@tool(handle_tool_error=True)
def flaky_tool(x: int):
    """A tool that might fail."""
    raise ValueError("Something went wrong")

# 当工具失败时，Agent 会收到 "ValueError: Something went wrong" 作为观察结果，
# 并且可以据此尝试其他工具或通知用户。
```
