import asyncio
import os
from llm_bridge.type.message import Message, Content

async def test_llm():
    from llm_bridge.logic.chat_generate.chat_client_factory import create_chat_client
    os.environ['GEMINI_API_KEY'] = "dummy"
    client = await create_chat_client(
        api_keys={}, 
        messages=[Message(role="user", content=[Content(text="Hello", type="text")])],
        model="gemini-1.5-flash",
        api_type="gemini",
        temperature=0.0,
        stream=False,
        thought=False,
        web_search=False,
        code_execution=False,
        structured_output_schema=None
    )
    print("ChatClient methods:")
    print(dir(client))
    
asyncio.run(test_llm())
