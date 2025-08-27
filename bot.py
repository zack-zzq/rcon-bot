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
    """处理收到的消息"""
    # 仅处理群消息
    if not (data.get('post_type') == 'message' and data.get('message_type') == 'group'):
        return

    user_id = data.get('user_id')
    group_id = data.get('group_id')
    raw_message = data.get('raw_message', '')
    
    # 1. 权限检查：发送者是否在授权列表里
    if str(user_id) not in AUTHORIZED_QQS:
        return
        
    # 2. 格式检查：消息是否是AT机器人开头
    at_me_cq = f'[CQ:at,qq={BOT_QQ}]'
    if not raw_message.strip().startswith(at_me_cq):
        return

    # 3. 提取AT之后的内容
    # 使用正则表达式去除CQ码和首尾空格，更稳定
    content = re.sub(r'\[CQ:at,qq=\d+\]', '', raw_message).strip()
    
    # 4. 指令检查：内容是否以指令前缀开头
    if content.startswith(COMMAND_PREFIX):
        command = content[len(COMMAND_PREFIX):].strip()
        
        if not command:
            reply_text = "请输入Minecraft指令。"
        else:
            # 执行RCON指令
            reply_text = await send_rcon_command(command)

        # 构建回复消息，AT回发送者
        at_sender_cq = f'[CQ:at,qq={user_id}]'
        full_reply = f"{at_sender_cq}\n[MC服务器返回]\n----------------\n{reply_text}"

        reply_payload = {
            "action": "send_group_msg",
            "params": {
                "group_id": group_id,
                "message": full_reply
            }
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