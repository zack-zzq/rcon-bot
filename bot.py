# bot.py
import asyncio
import json
import os
import re
import logging
from mcrcon import MCRcon
import websockets

# --- 配置 ---
# 从环境变量获取配置
RCON_HOST = os.getenv('MCRCON_HOST', 'localhost')
RCON_PORT = int(os.getenv('MCRCON_PORT', 25575))
RCON_PASS = os.getenv('MCRCON_PASS', 'your_rcon_password')

# OneBot (go-cqhttp) 的反向WebSocket地址
ONEBOT_WS_URL = os.getenv('ONEBOT_WS_URL', 'ws://go-cqhttp:8080/onebot/v11/ws')

# 机器人自身的QQ号，用于判断是否被AT
BOT_QQ = int(os.getenv('BOT_QQ', 0))

# 授权使用指令的QQ号列表，用逗号分隔
# 例如: "12345,67890,54321"
AUTHORIZED_QQS_STR = os.getenv('AUTHORIZED_QQS', '')
AUTHORIZED_QQS = [qq.strip() for qq in AUTHORIZED_QQS_STR.split(',') if qq.strip()]

# 指令前缀
COMMAND_PREFIX = "/"

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def send_rcon_command(command: str) -> str:
    """连接RCON并发送指令"""
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

async def handle_message(websocket, data: dict):
    """处理收到的消息 (V5 - 最终版，使用消息数组解析)"""
    # 仅处理群消息
    if not (data.get('post_type') == 'message' and data.get('message_type') == 'group'):
        return

    logging.info(f"Received group message data: {data}")

    user_id = data.get('user_id')
    group_id = data.get('group_id')
    message_array = data.get('message')

    # 检查消息数组是否存在且不为空
    if not message_array:
        return

    # 1. 权限检查：发送者是否在授权列表里
    if str(user_id) not in AUTHORIZED_QQS:
        return
        
    # 2. 检查消息开头是否是AT机器人 (核心修改)
    # 不再解析raw_message，直接检查消息数组的第一个元素
    first_segment = message_array[0]
    if not (first_segment.get('type') == 'at' and first_segment.get('data', {}).get('qq') == str(BOT_QQ)):
        return

    # 3. 提取指令 (核心修改)
    # 从消息数组的第二个元素开始，拼接所有文本作为指令
    command_parts = []
    for segment in message_array[1:]:
        if segment.get('type') == 'text':
            command_parts.append(segment.get('data', {}).get('text', ''))
    
    content = "".join(command_parts).strip()

    # 4. 指令前缀检查
    if content.startswith(COMMAND_PREFIX):
        command = content[len(COMMAND_PREFIX):].strip()
        logging.info(f"Extracted command: '{command}'")
        
        if not command:
            reply_text = "请输入Minecraft指令。"
        else:
            logging.info(f"EXECUTING RCON COMMAND!")
            reply_text = await send_rcon_command(command)

        # 构建回复消息
        at_sender_cq = f'[CQ:at,qq={user_id}]'
        full_reply = f"{at_sender_cq}\n[MC服务器返回]\n----------------\n{reply_text}"
        reply_payload = {
            "action": "send_group_msg",
            "params": { "group_id": group_id, "message": full_reply }
        }
        await websocket.send(json.dumps(reply_payload))
        logging.info(f"Replied to authorized user {user_id} in group {group_id}.")



async def bot_client():
    """连接到OneBot WebSocket并持续监听"""
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

if __name__ == "__main__":
    logging.info("Starting QQ-MC Bot...")
    if BOT_QQ == 0 or not AUTHORIZED_QQS:
        logging.error("关键环境变量 BOT_QQ 或 AUTHORIZED_QQS 未设置！机器人无法正常工作。")
    elif not all([RCON_HOST, RCON_PORT, RCON_PASS]):
        logging.error("RCON相关环境变量未完全设置！")
    else:
        logging.info(f"Bot QQ ID: {BOT_QQ}")
        logging.info(f"Authorized users: {AUTHORIZED_QQS}")
        asyncio.run(bot_client())