from bot.bot import Bot
from bridge.context import ContextType, Context
from bridge.reply import Reply, ReplyType
from common.log import logger
from config import conf
from cozepy import Coze, TokenAuth, MessageContentType, MessageType
import json

from .workflows import Workflow
from .user_session import UserSessionManager
from .conversation_manager import ConversationManager
from pathlib import Path
import re


class CozeBot(Bot):
    def __init__(self):
        # 调用父类的初始化方法
        super().__init__()
        # 从配置文件获取 token 和 bot_id
        self.token = conf().get("coze_api_key")
        self.bot_id = conf().get("coze_bot_id")
        self.app_id = conf().get("coze_space_id")
        # 初始化Coze客户端
        self.coze_client = Coze(auth=TokenAuth(token=self.token), base_url=conf().get("coze_api_base"))
        # 初始化会话管理组件
        self.session_manager = UserSessionManager()
        self.conv_manager = ConversationManager(coze_client=self.coze_client, session_manager=self.session_manager)
        self.workflows = Workflow(self.coze_client, self.app_id, self.bot_id)

    def reply(self, query, context: Context = None) -> Reply:
        try:
            # 统一获取用户ID
            user_id = context["session_id"]
            # 消息预处理逻辑
            query, reply = self._preprocess_message(context)
            if reply:
                return reply

            # 获取或创建会话（使用数据库管理）
            conversation_id = self.session_manager.get_session(user_id)
            if not conversation_id:
                if not (conversation_id := self.conv_manager.create_conversation(user_id)):
                    return Reply(ReplyType.TEXT, "会话创建失败")

            # 创建消息并获取回复
            return self._create_message_and_get_reply(conversation_id, query, context)

        except Exception as e:
            logger.error(f"处理消息异常: {str(e)}", exc_info=True)
            return Reply(ReplyType.TEXT, "消息处理失败")

    def _preprocess_message(self, context):
        """消息预处理"""
        # 保留图片处理
        if context.type == ContextType.IMAGE:
            try:
                file_path = Path(context.content).resolve()
                if not file_path.exists():
                    raise FileNotFoundError(f"图片文件不存在: {file_path}")

                file = self.coze_client.files.upload(file=str(file_path))
                return json.dumps([{"type": "file", "file_id": file.id}]), None

            except Exception as e:
                logger.error(f"图片处理失败: {str(e)}")
                return None, Reply(ReplyType.TEXT, "图片上传失败")

        # 分享链接处理
        if context.type == ContextType.SHARING:
            return json.dumps([{"type": "text", "text": context.content}]), None

        # 处理清除记忆指令
        if context.type == ContextType.TEXT and "清除记忆" in context.content:
            user_id = context["receiver"]
            if not user_id:
                return None, Reply(ReplyType.TEXT, "用户ID获取失败")
            new_id = self.conv_manager.create_conversation(user_id)
            return None, Reply(ReplyType.TEXT, "记忆已清除") if new_id else (None, Reply(ReplyType.TEXT, "清除失败"))

        if context.type == ContextType.TEXT and "关闭机器人" in context.content:
            user_id = context["receiver"]
            if not user_id:
                return None, Reply(ReplyType.TEXT, "用户ID获取失败")
            new_id = self.conv_manager.create_conversation(user_id)
            return None, Reply(ReplyType.TEXT, "记忆已清除") if new_id else (None, Reply(ReplyType.TEXT, "清除失败"))

        # 调用workflow
        try:
            test = re.findall(r"{([^{}:]*)}", context.content)
            if len(test):
                matches = test
                task_config = None
            else:
                json_content = re.sub(r"(\w+):", r'"\1":', context.content)
                workflow_config = json.loads(json_content)
                matches = list(workflow_config.keys())
                task_config = list(workflow_config.values())[0]

            if context.type == ContextType.TEXT and len(matches) > 0:
                if not task_config:
                    return None, self.workflows.apply(matches[0], context)
                elif task_config:
                    return None, self.workflows.timer_trigger(matches[0], context, **task_config)
        except Exception as e:
            # 基础文本处理
            return json.dumps([{"type": "text", "text": context.content}]), None

        return json.dumps([{"type": "text", "text": context.content}]), None

    def _create_message_and_get_reply(self, conversation_id, query, context):
        """创建消息并获取回复"""
        try:
            message = self.coze_client.conversations.messages.create(conversation_id=conversation_id, content=query, role="user", content_type="object_string")
            logger.debug(f"消息已创建: {message.id}")

            chat = self.coze_client.chat.create_and_poll(
                conversation_id=conversation_id, bot_id=self.bot_id, user_id=context["receiver"], additional_messages=[message], auto_save_history=True
            )

            replies = []
            for messages in chat.messages:
                if messages.type.value == MessageType.ANSWER:
                    link_reply = None
                    text_reply = None

                    if messages.content_type.value == MessageContentType.CARD:
                        try:
                            # 解析卡片信息
                            card_data = json.loads(messages.content)
                            info_str = card_data.get("info_in_card", "")

                            # 解析键值对
                            info_dict = {}
                            for line in info_str.split("\n"):
                                if "," in line:
                                    key, value = line.split(",", 1)
                                    info_dict[key.strip()] = value.strip()
                            # 提取字段并设置互备逻辑
                            title = info_dict.get("title")
                            url = info_dict.get("linkUrl")
                            image = info_dict.get("thumbUrl")
                            desc = info_dict.get("desc")

                            # 当只有图片字段时，使用ReplyType.IMAGE回复
                            if "image" in info_dict:
                                image_url = info_dict.get("image")
                                link_reply = Reply(ReplyType.IMAGE_URL, image_url)
                            else:
                                link_content = {"title": title, "desc": desc, "link_url": url, "thumb_url": image}
                                link_reply = Reply(ReplyType.LINK, link_content)
                        except Exception as e:
                            logger.error(f"解析卡片信息失败: {str(e)}")
                            logger.error("原始内容:", messages.content)
                    elif messages.content_type.value == MessageContentType.TEXT:
                        text_reply = Reply(ReplyType.TEXT, messages.content)

                    # 按优先级添加有效回复
                    if link_reply:
                        replies.append(link_reply)
                    if text_reply:
                        replies.append(text_reply)

            # 返回所有有效回复或错误提示
            if replies:
                return replies[0] if len(replies) == 1 else replies
            logger.error("未找到有效回复内容")
            return Reply(ReplyType.TEXT, "未能获取到回复")

        except Exception as e:
            logger.error(f"消息处理失败: {str(e)}")
            return Reply(ReplyType.TEXT, "请求处理超时")
