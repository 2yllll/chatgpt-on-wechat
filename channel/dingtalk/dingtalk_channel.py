import copy
import json

# -*- coding=utf-8 -*-
import logging
import time

import dingtalk_stream
from dingtalk_stream import AckMessage
from dingtalk_stream.card_replier import AICardReplier
from dingtalk_stream.card_replier import AICardStatus
from dingtalk_stream.card_replier import CardReplier
from alibabacloud_dingtalk.oauth2_1_0.client import Client as dingtalkoauth2_1_0Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dingtalk.oauth2_1_0 import models as dingtalkoauth_2__1__0_models
from alibabacloud_dingtalk.robot_1_0.client import Client as dingtalkrobot_1_0Client
from alibabacloud_dingtalk.robot_1_0 import models as dingtalkrobot__1__0_models
from alibabacloud_tea_util import models as util_models

from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.dingtalk.dingtalk_message import DingTalkMessage
from common.expired_dict import ExpiredDict
from common.log import logger
from common.singleton import singleton
from common.time_check import time_checker
from config import conf

_token_cache = {"token": None, "expire": 0}


class CustomAICardReplier(CardReplier):
    def __init__(self, dingtalk_client, incoming_message):
        super(AICardReplier, self).__init__(dingtalk_client, incoming_message)

    def start(
        self,
        card_template_id: str,
        card_data: dict,
        recipients: list = None,
        support_forward: bool = True,
    ) -> str:
        """
        AI卡片的创建接口
        :param support_forward:
        :param recipients:
        :param card_template_id:
        :param card_data:
        :return:
        """
        card_data_with_status = copy.deepcopy(card_data)
        card_data_with_status["flowStatus"] = AICardStatus.PROCESSING
        return self.create_and_send_card(
            card_template_id,
            card_data_with_status,
            at_sender=True,
            at_all=False,
            recipients=recipients,
            support_forward=support_forward,
        )


# 对 AICardReplier 进行猴子补丁
AICardReplier.start = CustomAICardReplier.start


def _check(func):
    def wrapper(self, cmsg: DingTalkMessage):
        msgId = cmsg.msg_id
        if msgId in self.receivedMsgs:
            logger.info("DingTalk message {} already received, ignore".format(msgId))
            return
        self.receivedMsgs[msgId] = True
        create_time = cmsg.create_time  # 消息时间戳
        if conf().get("hot_reload") == True and int(create_time) < int(time.time()) - 60:  # 跳过1分钟前的历史消息
            logger.debug("[DingTalk] History message {} skipped".format(msgId))
            return
        if cmsg.my_msg and not cmsg.is_group:
            logger.debug("[DingTalk] My message {} skipped".format(msgId))
            return
        return func(self, cmsg)

    return wrapper


@singleton
class DingTalkChanel(ChatChannel, dingtalk_stream.ChatbotHandler):
    dingtalk_client_id = conf().get("dingtalk_client_id")
    dingtalk_client_secret = conf().get("dingtalk_client_secret")
    dingtalk_robot_code = conf().get("dingtalk_robot_code")

    def get_token(self):
        now = time.time()
        if _token_cache["token"] and now < _token_cache["expire"]:
            return _token_cache["token"]
        config = open_api_models.Config()
        config.protocol = "https"
        config.region_id = "central"
        authclient = dingtalkoauth2_1_0Client(config)
        get_access_token_request = dingtalkoauth_2__1__0_models.GetAccessTokenRequest(
            app_key=self.dingtalk_client_id, 
            app_secret=self.dingtalk_client_secret
        )
        try:
            response = authclient.get_access_token(get_access_token_request)
            token = getattr(response.body, "access_token", None)
            expire_in = getattr(response.body, "expire_in", 7200)
            if token:
                _token_cache["token"] = token
                _token_cache["expire"] = now + expire_in - 500  # 提前200秒刷新
            return token
        except Exception as err:
            print(f"获取token失败: {err}")
            return None

    def setup_logger(self):
        logger = logging.getLogger()
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)-8s %(levelname)-8s %(message)s [%(filename)s:%(lineno)d]"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger

    def __init__(self):
        super().__init__()
        super(dingtalk_stream.ChatbotHandler, self).__init__()
        self.logger = self.setup_logger()
        # 历史消息id暂存，用于幂等控制
        self.receivedMsgs = ExpiredDict(conf().get("expires_in_seconds", 3600))
        logger.info("[DingTalk] client_id={}, client_secret={} ".format(self.dingtalk_client_id, self.dingtalk_client_secret))
        # 无需群校验和前缀
        conf()["group_name_white_list"] = ["ALL_GROUP"]
        # 单聊无需前缀
        conf()["single_chat_prefix"] = [""]

    def startup(self):
        credential = dingtalk_stream.Credential(self.dingtalk_client_id, self.dingtalk_client_secret)
        streamclient = dingtalk_stream.DingTalkStreamClient(credential)
        streamclient.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, self)
        streamclient.start_forever()

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        try:
            incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)
            image_download_handler = self  # 传入方法所在的类实例
            dingtalk_msg = DingTalkMessage(incoming_message, image_download_handler)

            if dingtalk_msg.is_group:
                self.handle_group(dingtalk_msg)
            else:
                self.handle_single(dingtalk_msg)
            return AckMessage.STATUS_OK, "OK"
        except Exception as e:
            logger.error(f"dingtalk process error={e}")
            return AckMessage.STATUS_SYSTEM_EXCEPTION, "ERROR"

    @time_checker
    @_check
    def handle_single(self, cmsg: DingTalkMessage):
        # 处理单聊消息
        if cmsg.ctype == ContextType.VOICE:
            logger.debug("[DingTalk]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[DingTalk]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE_CREATE:
            logger.debug("[DingTalk]receive image create msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[DingTalk]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[DingTalk]receive text msg: {}".format(cmsg.content))
        else:
            logger.debug("[DingTalk]receive other msg: {}".format(cmsg.content))
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=False, msg=cmsg)
        if context:
            self.produce(context)

    @time_checker
    @_check
    def handle_group(self, cmsg: DingTalkMessage):
        # 处理群聊消息
        if cmsg.ctype == ContextType.VOICE:
            logger.debug("[DingTalk]receive voice msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE:
            logger.debug("[DingTalk]receive image msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.IMAGE_CREATE:
            logger.debug("[DingTalk]receive image create msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.PATPAT:
            logger.debug("[DingTalk]receive patpat msg: {}".format(cmsg.content))
        elif cmsg.ctype == ContextType.TEXT:
            logger.debug("[DingTalk]receive text msg: {}".format(cmsg.content))
        else:
            logger.debug("[DingTalk]receive other msg: {}".format(cmsg.content))
        context = self._compose_context(cmsg.ctype, cmsg.content, isgroup=True, msg=cmsg)
        context["no_need_at"] = True
        if context:
            self.produce(context)

    def send(self, reply: Reply, context: Context):
        receiver = context["receiver"]
        isgroup = context.kwargs["msg"].is_group
        from_message = context.kwargs["msg"].incoming_message

        # if conf().get("dingtalk_card_enabled"):
        #     logger.info("[Dingtalk] sendMsg={}, receiver={}".format(reply, receiver))

        #     def reply_with_text():
        #         self.reply_text(reply.content, incoming_message)

        #     def reply_with_at_text():
        #         self.reply_text("📢 您有一条新的消息，请查看。", incoming_message)

        #     def reply_with_ai_markdown():
        #         button_list, markdown_content = self.generate_button_markdown_content(context, reply)
        #         self.reply_ai_markdown_button(incoming_message, markdown_content, button_list, "", "📌 内容由AI生成", "", [incoming_message.sender_staff_id])

        #     if reply.type in [ReplyType.IMAGE_URL, ReplyType.IMAGE, ReplyType.TEXT]:
        #         if isgroup:
        #             reply_with_ai_markdown()
        #             reply_with_at_text()
        #         else:
        #             reply_with_ai_markdown()
        #     else:
        #         # 暂不支持其它类型消息回复
        #         reply_with_text()
        # else:
            # self.reply_text(reply.content, from_message)

        if isgroup:
            self.reply_group_message(reply.content, receiver, from_message)
        else:
            self.reply_single_message(reply.content, receiver, from_message)

    def generate_button_markdown_content(self, context, reply):
        image_url = context.kwargs.get("image_url")
        promptEn = context.kwargs.get("promptEn")
        reply_text = reply.content
        button_list = []
        markdown_content = f"""{reply.content}"""
        if image_url is not None and promptEn is not None:
            button_list = [{"text": "查看原图", "url": image_url, "iosUrl": image_url, "color": "blue"}]
            markdown_content = f"""{promptEn}!["图片"]({image_url}){reply_text}"""
        logger.debug(f"[Dingtalk] generate_button_markdown_content, button_list={button_list} , markdown_content={markdown_content}")

        return button_list, markdown_content

    def create_client(self):
        config = open_api_models.Config()
        config.protocol = "https"
        config.region_id = "central"
        return dingtalkrobot_1_0Client(config)

    def reply_group_message(self, reply_content, receiver, from_message):
        replyclient = self.create_client()
        org_group_send_headers = dingtalkrobot__1__0_models.OrgGroupSendHeaders()
        org_group_send_headers.x_acs_dingtalk_access_token = self.get_token()
        org_group_send_request = dingtalkrobot__1__0_models.OrgGroupSendRequest(
            msg_param=json.dumps({"content":reply_content}),
            msg_key="sampleText",
            open_conversation_id=receiver, 
            robot_code=self.dingtalk_robot_code
        )
        try:
            response = replyclient.org_group_send_with_options(org_group_send_request, org_group_send_headers, util_models.RuntimeOptions())
            print("消息发送成功，返回：", response)
            return response
        except Exception as err:
            print(f"发送群消息失败: {err}")
            return None

    def reply_single_message(self, reply_content, receiver, from_message):
        replyclient = self.create_client()
        batch_send_otoheaders = dingtalkrobot__1__0_models.BatchSendOTOHeaders()
        batch_send_otoheaders.x_acs_dingtalk_access_token = self.get_token()
        batch_send_otorequest = dingtalkrobot__1__0_models.BatchSendOTORequest(
            robot_code=self.dingtalk_robot_code,
            user_ids=[
                from_message.sender_staff_id
            ],
            msg_key='sampleText',
            msg_param=json.dumps({"content":reply_content}),
        )
        try:
            response = replyclient.batch_send_otowith_options(batch_send_otorequest, batch_send_otoheaders, util_models.RuntimeOptions())
            print("消息发送成功，返回：", response)
            return response
        except Exception as err:
            print(f"发送消息失败: {err}")
            return None
