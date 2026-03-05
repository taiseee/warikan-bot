from firebase_functions import https_fn
from linebot.v3 import WebhookHandler as LineWebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
from openai import OpenAI
import json
from .secrets import (
    OPENAI_API_KEY,
    OPENAI_ORGANIZATION,
    CHANNEL_SECRET,
    CHANNEL_ACCESS_TOKEN,
)
from .assistant_factory import MODEL, TOOLS, INSTRUCTIONS
from .model import Group
from .payment_service import PaymentService


class WebhookHandler:
    _CHANNEL_SECRET: str = CHANNEL_SECRET
    _CHANNEL_ACCESS_TOKEN: str = CHANNEL_ACCESS_TOKEN

    def __init__(self):
        self._configuration = Configuration(access_token=self._CHANNEL_ACCESS_TOKEN)
        self._handler = LineWebhookHandler(self._CHANNEL_SECRET)
        self._add()

    def handle(self, body: str, signature: str) -> https_fn.Response:
        try:
            self._handler.handle(body, signature)
            return https_fn.Response({"message": "success"}, status=200)
        except InvalidSignatureError as e:
            print(f"catch InvalidSignatureError: {e}")
            return https_fn.Response(
                {
                    "message": "Invalid signature. Please check your channel access token/channel secret."
                },
                status=400,
            )

    def _add(self):
        @self._handler.add(MessageEvent, message=TextMessageContent)
        def handler_message(event: MessageEvent) -> https_fn.Response:
            group = Group().fetch_or_create(event.source.group_id)
            conversation = Conversation()

            try:
                if not group.conversation_id:
                    conv_id = conversation.create()
                    group.conversation_id = conv_id
                    group.update()

                response = conversation.send_message(
                    conversation_id=group.conversation_id,
                    message=event.message.text,
                )

                response = conversation.handle_tool_calls(
                    response=response,
                    conversation_id=group.conversation_id,
                    group_id=group.id,
                )

                assistant_answer = conversation.get_text_response(response)
                self._reply(event, assistant_answer)

                if conversation.has_settled(response):
                    group.conversation_id = ""
                    group.update()

            except Exception as e:
                print(f"Error: {e}")
                self._reply(event, "すみません、技術的な問題が発生しました。")
                group.conversation_id = ""
                group.update()

            return https_fn.Response({"message": "success"}, status=200)

        @self._handler.default()
        def default(event):
            return https_fn.Response({"message": "success"}, status=200)

    def _reply(self, event: MessageEvent, text: str):
        with ApiClient(self._configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    replyToken=event.reply_token,
                    messages=[TextMessage(text=text)],
                )
            )


class Tool:
    def __init__(self, name: str = "", args: dict = None, group_id: str = ""):
        self._name = name
        self._args = args or {}
        self._group_id = group_id

    def exec(self) -> dict:
        if self._name == "PaymentService_add":
            return PaymentService().add(
                group_id=self._group_id, payment=self._args
            )
        if self._name == "PaymentService_settle":
            return PaymentService().settle(
                group_id=self._group_id, args=self._args
            )
        return {"status": "error", "code": 500, "message": "Tool not found."}


class Conversation:
    _OPENAI_API_KEY: str = OPENAI_API_KEY
    _OPENAI_ORGANIZATION: str = OPENAI_ORGANIZATION

    def __init__(self):
        self._client = OpenAI(
            api_key=self._OPENAI_API_KEY,
            organization=self._OPENAI_ORGANIZATION,
        )

    def create(self) -> str:
        conv = self._client.conversations.create()
        return conv.id

    def send_message(self, conversation_id: str, message: str):
        response = self._client.responses.create(
            model=MODEL,
            conversation=conversation_id,
            input=[{"role": "user", "content": message}],
            tools=TOOLS,
            instructions=INSTRUCTIONS,
        )
        return response

    def handle_tool_calls(self, response, conversation_id: str, group_id: str):
        tool_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        if not tool_calls:
            return response

        tool_results = []
        for tc in tool_calls:
            tool = Tool(
                name=tc.name,
                args=json.loads(tc.arguments),
                group_id=group_id,
            )
            output = tool.exec()
            tool_results.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": json.dumps(output),
            })

        response = self._client.responses.create(
            model=MODEL,
            conversation=conversation_id,
            input=tool_results,
            tools=TOOLS,
            instructions=INSTRUCTIONS,
        )
        return response

    def get_text_response(self, response) -> str:
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        return content.text
        return "応答を取得できませんでした。"

    def has_settled(self, response) -> bool:
        for item in response.output:
            if item.type == "function_call" and item.name == "PaymentService_settle":
                return True
        return False
