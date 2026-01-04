import os
import sys
import asyncio
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.callbacks import StreamingStdOutCallbackHandler
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, AIMessageChunk

# MCP Imports
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

# 加载环境变量
load_dotenv()


# ==========================================
# 1. 定义工具 (Tools)
# ==========================================
@tool
def magic_calculator(a: int, b: int) -> int:
    """
    一个神奇的计算器，它会将两个数字相加，然后乘以 2。
    用于演示工具调用。
    """
    return (a + b) * 2


@tool
def get_weather(city: str) -> str:
    """
    获取指定城市的天气。
    """
    return f"{city} 的天气是晴朗，气温 25 度。"


tools = [magic_calculator, get_weather]

# ==========================================
# 2. 配置 Memory (SQLite)
# ==========================================
DB_CONNECTION = "sqlite:///memory.db"


def get_chat_history(session_id: str) -> SQLChatMessageHistory:
    """
    获取基于 SQLite 的聊天记录管理器。
    """
    return SQLChatMessageHistory(session_id=session_id, connection=DB_CONNECTION)


ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "deepseek-v3-2-251201"


# ==========================================
# 3. 定义流式生成器方法
# ==========================================
async def chat_generator(agent, history: SQLChatMessageHistory, user_input: str):
    """
    流式对话生成器 (Async)。
    
    Args:
        agent: 编译好的 LangGraph Agent
        history: 聊天记录管理器
        user_input: 用户输入
        
    Yields:
        str: AI 回复的文本片段
    """
    # 1. 将用户消息添加到历史记录
    history.add_user_message(user_input)
    
    # 2. 获取当前上下文
    current_messages = history.messages
    
    accumulated_content = ""
    
    # 3. 使用 stream 模式调用 Agent (Async)
    # stream_mode="messages" 会返回消息块 (MessageChunk)
    try:
        async for chunk, metadata in agent.astream(
            {"messages": current_messages}, 
            stream_mode="messages"
        ):
            # 我们只关心 AI 的回复内容 (AIMessageChunk)
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                content = chunk.content
                accumulated_content += content
                yield content
                
    except Exception as e:
        print(f"\n❌ 流式生成出错: {e}")
        yield f"[Error: {e}]"
        
    # 4. 保存完整回复
    if accumulated_content:
        history.add_ai_message(accumulated_content)

# ==========================================
# 4. 主程序
# ==========================================
async def main():
    # 检查 API Key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ 错误: 未找到 OPENAI_API_KEY。")
        print("请在 .env 文件中设置 OPENAI_API_KEY=sk-...")

    # 初始化 LLM
    try:
        # 注意：使用 generator yield 方式时，通常不需要 StreamingStdOutCallbackHandler
        # 除非你想在控制台同时也看到输出。这里我们去掉它，演示纯 generator 控制。
        llm = ChatOpenAI(
            model=DEFAULT_MODEL,
            temperature=0,
            base_url=ARK_BASE_URL,
            api_key=api_key,
            streaming=True, # 依然需要开启 streaming
            # callbacks=[StreamingStdOutCallbackHandler()] # 移除 stdout callback
        )
    except Exception as e:
        print(f"LLM 初始化失败: {e}")
        return

    # ==========================================
    # MCP 工具加载逻辑
    # ==========================================
    mcp_tools = []
    
    # 使用 AsyncExitStack 管理多个上下文管理器 (MCP Sessions)
    async with AsyncExitStack() as stack:
        # 示例：连接到一个本地 MCP 服务器
        # server_params = StdioServerParameters(
        #     command="npx",
        #     args=["-y", "@modelcontextprotocol/server-filesystem", "/Users/macbook/Desktop"],
        # )
        
        # 实际使用时，请取消注释并配置正确的 command/args
        mcp_servers = [
            # (StdioServerParameters(command="...", args=[...])) 
        ]
        
        for params in mcp_servers:
            try:
                # 连接到 MCP 服务器
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                
                # 加载工具
                tools_from_server = await load_mcp_tools(session)
                mcp_tools.extend(tools_from_server)
                print(f"✅ 已加载 MCP 工具: {[t.name for t in tools_from_server]}")
                
            except Exception as e:
                print(f"❌ 连接 MCP 服务器失败 ({params.command}): {e}")

        # 合并所有工具
        all_tools = tools + mcp_tools

        # 创建 Agent
        print(f"正在创建 Agent (工具数: {len(all_tools)})...")
        agent_app = create_agent(llm, all_tools)

        # 模拟用户会话
        session_id = "user_session_001"
        history = get_chat_history(session_id)
        
        print(f"\n🚀 Agent 已启动 (Session ID: {session_id})")
        print(f"💾 记忆存储于: {DB_CONNECTION}")
        print("您可以输入问题，输入 'quit' 或 'exit' 退出。\n")

        while True:
            try:
                # 使用 run_in_executor 来避免阻塞 async loop (虽然 input 本身是阻塞的)
                # 简单的脚本中可以直接用 input，但为了更好的 async 体验：
                user_input = await asyncio.to_thread(input, "User: ")
                user_input = user_input.strip()
            except EOFError:
                break

            if not user_input:
                continue
                
            if user_input.lower() in ["quit", "exit"]:
                print("再见！")
                break

            # 3. 调用 Agent (使用 Generator)
            try:
                print("AI: ", end="", flush=True)
                
                async for token in chat_generator(agent_app, history, user_input):
                    print(token, end="", flush=True)
                    
                print("") # 换行
                    
            except Exception as e:
                print(f"❌ 发生错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())
