from firebase_functions import https_fn
from firebase_functions.firestore_fn import (
    DocumentSnapshot,
)
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
import time
import json
from .secrets import (
    OPENAI_API_KEY,
    OPENAI_ORGANIZATION,
    ASSISTANT_ID,
    CHANNEL_SECRET,
    CHANNEL_ACCESS_TOKEN,
)
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
            return https_fn.Response({"message": "sucess"}, status=200)
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
            warikan_assistant = Assistant()

            # if not warikan_assistant.is_mentioned(event):
            #     return https_fn.Response(
            #         {"message": "warikan bot is not mentioned"}, status=200
            #     )
            group = Group().fetch_or_create(event.source.group_id)

            thread = Thread().open(group)

            group.thread_id = thread.id
            group.update()

            thread.add_message(event.message.text)

            active_thread = thread.run()
            print("runed")
            active_thread_with_status = active_thread.set_status()
            print("status" + active_thread_with_status._status)
            while active_thread_with_status.is_in_progress():
                time.sleep(1)
                active_thread_with_status = active_thread_with_status.set_status()
                print("status" + active_thread_with_status._status)
                
            if active_thread_with_status.is_completed():
                assistant_answer = active_thread_with_status.fetch_current_message()
                with ApiClient(self._configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            replyToken=event.reply_token,
                            notificationDisabled=None,
                            messages=[
                                TextMessage(
                                    text=assistant_answer,
                                    quickReply=None,
                                    quoteToken=None,
                                )
                            ],
                        )
                    )
                return https_fn.Response({"message": "thread is completed"}, status=200)

            if active_thread_with_status.requires_action():
                print("requires_action")
                action = active_thread_with_status.get_action()
                print(action)

                tool_call = action.submit_tool_outputs.tool_calls[0]
                tool = Tool(
                    id=tool_call.id,
                    type=tool_call.type,
                    name=tool_call.function.name,
                    args=json.loads(tool_call.function.arguments),
                    group_id=group.id,
                )

                execed_tool = tool.exec()
                
                active_thread_with_status.submit_tool_outputs(execed_tool)
            
            active_thread_with_status = active_thread.set_status()
            print("status" + active_thread_with_status._status)
            while active_thread_with_status.is_in_progress():
                time.sleep(1)
                active_thread_with_status = active_thread_with_status.set_status()
                print("status" + active_thread_with_status._status)
            
            if active_thread_with_status.is_completed():
                assistant_answer = active_thread_with_status.fetch_current_message()
                with ApiClient(self._configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            replyToken=event.reply_token,
                            notificationDisabled=None,
                            messages=[
                                TextMessage(
                                    text=assistant_answer,
                                    quickReply=None,
                                    quoteToken=None,
                                )
                            ],
                        )
                    )
                active_thread_with_status.delete(group)
                return https_fn.Response({"message": "thread is completed"}, status=200)
            
            if active_thread_with_status.is_faild():
                with ApiClient(self._configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message_with_http_info(
                        ReplyMessageRequest(
                            replyToken=event.reply_token,
                            notificationDisabled=None,
                            messages=[
                                TextMessage(
                                    text="すみません、技術的な問題が発生しました。",
                                    quickReply=None,
                                    quoteToken=None,
                                )
                            ],
                        )
                    )
                
                active_thread_with_status.delete(group)


            return https_fn.Response({"message": "sucess"}, status=200)

        @self._handler.default()
        def default(event):
            with ApiClient(self._configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        replyToken=event.reply_token,
                        notificationDisabled=None,
                        messages=[
                            TextMessage(
                                text="Hello, default", quickReply=None, quoteToken=None
                            )
                        ],
                    )
                )
            return https_fn.Response({"message": "sucess"}, status=200)

class Tool:
    def __init__(
        self,
        id: str = "",
        type: str = "",
        name: str = "",
        args: dict = {},
        group_id: str = "",
        output: dict = {},
    ):
        self._id = id
        self._type = type
        self._name = name
        self._args = args
        self._group_id = group_id
        self._output = output

    def exec(self) -> "Tool":
        if self._name == "PaymentService_add":
            return Tool(
                id=self._id,
                type=self._type,
                name=self._name,
                args=self._args,
                group_id=self._group_id,
                output=PaymentService().add(group_id=self._group_id, payment=self._args)
            )
        if self._name == "PaymentService_settle":
            return Tool(
                id=self._id,
                type=self._type,
                name=self._name,
                args=self._args,
                group_id=self._group_id,
                output=PaymentService().settle(group_id=self._group_id, args=self._args)
            )

        return Tool(
            id=self._id,
            type=self._type,
            name=self._name,
            args=self._args,
            group_id=self._group_id,
            output={
                "status": "error",
                "code": 500,
                "message": "Tool not found.",
            },
        )

class Thread:
    _OPENAI_API_KEY: str = OPENAI_API_KEY
    _OPENAI_ORGANIZATION: str = OPENAI_ORGANIZATION
    _ASSISTANT_ID: str = ASSISTANT_ID

    def __init__(self, id: str = "", run_id: str = "", status: str = ""):
        self._client = OpenAI(
            api_key=self._OPENAI_API_KEY, organization=self._OPENAI_ORGANIZATION
        ).beta.threads
        self.id = id
        self._run_id = run_id
        self._status = status

    def open(self, group: Group) -> "Thread":
        if not group.thread_id == "":
            thread = self._client.retrieve(thread_id=group.thread_id)
            return Thread(id=thread.id)

        thread = self._client.create()
        return Thread(id=thread.id)

    def delete(self, group: Group):
        self._client.delete(thread_id=self.id)
        group.thread_id = ""
        group.update()

    def add_message(self, message: str):
        self._client.messages.create(thread_id=self.id, role="user", content=message)

    def run(self) -> "Thread":
        run = self._client.runs.create(
            thread_id=self.id,
            assistant_id=self._ASSISTANT_ID,
        )
        return Thread(id=self.id, run_id=run.id)

    def fetch_current_message(self) -> str:
        messages = self._client.messages.list(thread_id=self.id, order="desc")
        current_message = messages._get_page_items()[0].content[0].text.value
        return current_message

    def set_status(self) -> "Thread":
        status = self._client.runs.retrieve(
            thread_id=self.id, run_id=self._run_id
        ).status

        return Thread(id=self.id, run_id=self._run_id, status=status)

    def get_action(self):
        return self._client.runs.retrieve(
            thread_id=self.id, run_id=self._run_id
        ).required_action

    def submit_tool_outputs(self, execed_tool: Tool):
        print(execed_tool._output)
        return self._client.runs.submit_tool_outputs(
            thread_id=self.id, run_id=self._run_id, tool_outputs=[
                {
                    "tool_call_id": execed_tool._id,
                    "output": json.dumps(execed_tool._output),
                }
            ]
        )

    def is_in_progress(self) -> bool:
        return self._status == "in_progress"

    def requires_action(self) -> bool:
        return self._status == "requires_action"

    def is_completed(self) -> bool:
        return self._status == "completed"
    
    def is_faild(self) -> bool:
        return self._status == "failed"


class Message:
    _OPENAI_API_KEY: str = OPENAI_API_KEY
    _OPENAI_ORGANIZATION: str = OPENAI_ORGANIZATION

    def __init__(self):
        self._client = OpenAI(
            api_key=self._OPENAI_API_KEY, organization=self._OPENAI_ORGANIZATION
        )

    def create(self, thread: Thread):
        thread._client.beta.messages.create(thread_id=thread.id, content="Hello")


class Assistant:
    _OPENAI_API_KEY: str = OPENAI_API_KEY
    _OPENAI_ORGANIZATION: str = OPENAI_ORGANIZATION
    _ASSISTANT_ID: str = ASSISTANT_ID

    def __init__(self):
        self._client = OpenAI(
            api_key=self._OPENAI_API_KEY, organization=self._OPENAI_ORGANIZATION
        )

    # @allメンションがあるか
    def is_mentioned(self, event: MessageEvent) -> bool:
        if event.message.mention is None:
            return False

        for mention in event.message.mention.mentionees:
            if mention.type == "all":
                return True

        return False