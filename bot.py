# bot.py
import asyncio
import json
import os
import re
import logging
from mcrcon import MCRcon
import websockets
from openai import AsyncOpenAI  # 导入新的库

# --- 配置 ---
# ... (RCON, OneBot, Bot QQ等配置保持不变) ...
RCON_HOST = os.getenv('MCRCON_HOST', 'localhost')
RCON_PORT = int(os.getenv('MCRCON_PORT', 25575))
RCON_PASS = os.getenv('MCRCON_PASS', 'your_rcon_password')
ONEBOT_WS_URL = os.getenv('ONEBOT_WS_URL', 'ws://go-cqhttp:8080/onebot/v11/ws')
BOT_QQ = int(os.getenv('BOT_QQ', 0))
AUTHORIZED_QQS_STR = os.getenv('AUTHORIZED_QQS', '')
AUTHORIZED_QQS = [qq.strip() for qq in AUTHORIZED_QQS_STR.split(',') if qq.strip()]
COMMAND_PREFIX = "/"

# --- 新增的大语言模型(LLM)配置 ---
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL')
OPENAI_MODEL_ID = os.getenv('OPENAI_MODEL_ID')

# 初始化异步OpenAI客户端
if all([OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_ID]):
    llm_client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
else:
    llm_client = None

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def process_with_llm(text: str) -> str:
    """使用大语言模型处理文本"""
    if not llm_client:
        logging.warning("LLM client not configured. Returning original text.")
        return text

    # 这是给大模型的指令(Prompt)，你可以根据喜好修改
    system_prompt = """
    你是一个专业的Minecraft服务器助手。
    你的任务是将服务器返回的原始、技术性的英文信息，转换成通俗易懂、对玩家友好的简体中文。
    - 如果信息是执行成功的回应, 例如 'Player kicked' 或 'Set time to 1000', 请用更自然的中文表达。
    - 如果信息是查询结果, 例如玩家列表, 请清晰地呈现。
    - 如果信息是错误信息, 例如 'Player not found', 请解释可能的原因。
    - 如果信息没有实际内容或只是一些代码, 就直说“服务器执行了指令，但没有返回具体信息”。
    - 你的回答应该直接是转换后的内容, 不要包含“好的, 这是转换后的内容：”等多余的解释。
    """
    
    try:
        logging.info(f"Sending to LLM for processing: '{text}'")
        response = await llm_client.chat.completions.create(
            model=OPENAI_MODEL_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.5, # 温度可以调整，0.5比较中性
        )
        processed_text = response.choices[0].message.content.strip()
        logging.info(f"LLM processed result: '{processed_text}'")
        return processed_text
    except Exception as e:
        logging.error(f"An error occurred with the LLM API: {e}")
        # 如果API调用失败，返回原始文本并附带一条错误提示
        return f"{text}\n\n[AI处理失败: {e}]"


# send_rcon_command 函数保持不变
async def send_rcon_command(command: str) -> str:
    # ... (此函数无需任何修改) ...
    try:
        with MCRcon(RCON_HOST, RCON_PASS, port=RCON_PORT) as mcr:
            logging.info(f"Sending RCON command: {command}")
            resp = mcr.command(command)
            logging.info(f"RCON response: {resp}")
            return resp if resp else "指令已执行，但服务器没有返回信息。"
    except ConnectionRefusedError:
        logging.error("RCON connection refused. 请检查MC服务器RCON是否开启，以及地址、端口是否正确。")
        return "错误：无法连接到RCON服务器，请检查服务器状态。"
    except Exception as e:
        logging.error(f"An RCON error occurred: {e}")
        return f"错误：执行RCON指令时发生未知错误: {e}"


# handle_message 函数需要修改
async def handle_message(websocket, data: dict):
    """处理收到的消息 (V6 - 集成LLM)"""
    # ... (前面的消息检查和指令提取逻辑保持不变) ...
    if not (data.get('post_type') == 'message' and data.get('message_type') == 'group'):
        return
    
    user_id = data.get('user_id')
    group_id = data.get('group_id')
    message_array = data.get('message')

    if not message_array: return
    if str(user_id) not in AUTHORIZED_QQS: return
        
    first_segment = message_array[0]
    if not (first_segment.get('type') == 'at' and first_segment.get('data', {}).get('qq') == str(BOT_QQ)):
        return

    command_parts = [seg.get('data', {}).get('text', '') for seg in message_array[1:] if seg.get('type') == 'text']
    content = "".join(command_parts).strip()

    if content.startswith(COMMAND_PREFIX):
        command = content[len(COMMAND_PREFIX):].strip()
        
        if not command:
            raw_reply_text = "请输入Minecraft指令。"
            processed_reply_text = raw_reply_text
        else:
            # 1. 从RCON获取原始回复
            raw_reply_text = await send_rcon_command(command)
            # 2. 将原始回复交给LLM处理
            processed_reply_text = await process_with_llm(raw_reply_text)

        # 3. 发送处理后的回复
        at_sender_cq = f'[CQ:at,qq={user_id}]'
        # 修改了回复的标题，让用户知道这是AI助手处理过的
        full_reply = f"{at_sender_cq}\n[服务器助手]\n----------------\n{processed_reply_text}"
        reply_payload = {
            "action": "send_group_msg",
            "params": { "group_id": group_id, "message": full_reply }
        }
        await websocket.send(json.dumps(reply_payload))
        logging.info(f"Replied to authorized user {user_id} in group {group_id} with LLM-processed message.")


# bot_client 函数保持不变
async def bot_client():
    # ... (此函数无需任何修改) ...
    while True:
        try:
            async with websockets.connect(ONEBOT_WS_URL) as websocket:
                logging.info(f"Successfully connected to OneBot WebSocket at {ONEBOT_WS_URL}")
                while True:
                    try:
                        message = await websocket.recv()
                        data = json.loads(message)
                        asyncio.create_task(handle_message(websocket, data))
                    except websockets.exceptions.ConnectionClosed:
                        logging.warning("Connection to OneBot closed. Reconnecting...")
                        break
        except Exception as e:
            logging.error(f"Failed to connect to OneBot: {e}. Retrying in 10 seconds...")
            await asyncio.sleep(10)


# 启动器需要更新，检查新的环境变量
if __name__ == "__main__":
    logging.info("Starting QQ-MC Bot...")
    if not all([llm_client, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL_ID]):
        logging.warning("OpenAI environment variables not fully set. LLM feature will be disabled.")
    else:
        logging.info(f"LLM feature enabled. Model: {OPENAI_MODEL_ID}, Base URL: {OPENAI_BASE_URL}")

    if BOT_QQ == 0 or not AUTHORIZED_QQS:
        logging.error("Critical environment variables BOT_QQ or AUTHORIZED_QQS not set!")
    else:
        asyncio.run(bot_client())