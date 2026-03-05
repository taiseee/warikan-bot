from firebase_functions import https_fn
from linebot.v3 import WebhookHandler as LineWebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, JoinEvent
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
        @self._handler.add(JoinEvent)
        def handler_join(event: JoinEvent):
            if not hasattr(event.source, "group_id"):
                return
            group_id = event.source.group_id
            Group().fetch_or_create(group_id)
            self._sync_all_members(group_id)

        @self._handler.add(MessageEvent, message=TextMessageContent)
        def handler_message(event: MessageEvent) -> https_fn.Response:
            group_id = event.source.group_id
            group = Group().fetch_or_create(group_id)

            # メッセージ送信者のプロフィールを更新
            self._sync_member(group_id, event.source.user_id)

            conversation = Conversation()

            try:
                if not group.conversation_id:
                    conv_id = conversation.create()
                    group.conversation_id = conv_id
                    group.update()

                members = Group.get_members(group_id)
                members_context = "\n".join(
                    f"- {m['user_id']}: {m['display_name']}" for m in members
                )
                extra = f"\n\n## グループメンバー\n{members_context}" if members_context else ""

                response = conversation.send_message(
                    conversation_id=group.conversation_id,
                    message=event.message.text,
                    extra_instructions=extra,
                )

                response, settled = conversation.handle_tool_calls(
                    response=response,
                    conversation_id=group.conversation_id,
                    group_id=group.id,
                    extra_instructions=extra,
                )

                if settled:
                    group.active_session_id = ""
                    group.update()

                assistant_answer = conversation.get_text_response(response)
                self._reply(event, assistant_answer)

            except Exception as e:
                print(f"Error: {e}")
                self._reply(event, "すみません、技術的な問題が発生しました。")
                # conversation_id はリセットしない（文脈を保持）

            return https_fn.Response({"message": "success"}, status=200)

        @self._handler.default()
        def default(event):
            return https_fn.Response({"message": "success"}, status=200)

    def _sync_all_members(self, group_id: str):
        with ApiClient(self._configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            try:
                response = line_bot_api.get_group_member_ids(group_id)
                for user_id in response.member_ids:
                    self._sync_member(group_id, user_id, api_client=api_client)
            except Exception as e:
                print(f"[DEBUG] Failed to sync all members for group {group_id}: {e}")

    def _sync_member(self, group_id: str, user_id: str, api_client=None):
        def _do_sync(client):
            line_bot_api = MessagingApi(client)
            try:
                profile = line_bot_api.get_group_member_profile(group_id, user_id)
                Group.upsert_member(
                    group_id,
                    user_id,
                    profile.display_name,
                    profile.picture_url or "",
                )
                print(f"[DEBUG] Synced member {user_id}: {profile.display_name}")
            except Exception as e:
                print(f"[DEBUG] Failed to sync member {user_id}: {e}")

        if api_client:
            _do_sync(api_client)
        else:
            with ApiClient(self._configuration) as client:
                _do_sync(client)

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
        svc = PaymentService()
        name = self._name
        args = self._args
        gid = self._group_id

        if name == "start_session":
            return svc.create_session(gid, name=args.get("name"))

        if name == "add_payment":
            return svc.add_payment(
                gid,
                payer_id=args["payer_id"],
                amount=args["amount"],
                item=args["item"],
            )

        if name == "cancel_payment":
            return svc.cancel_payment(gid, payment_id=args["payment_id"])

        if name == "list_payments":
            return svc.list_payments(gid)

        if name == "settle":
            return svc.settle(gid, div_num=args.get("div_num"))

        if name == "list_sessions":
            is_settled = args.get("is_settled")
            return svc.list_sessions(gid, is_settled=is_settled)

        if name == "get_session_detail":
            return svc.get_session_detail(gid, session_id=args["session_id"])

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

    def send_message(self, conversation_id: str, message: str, extra_instructions: str = ""):
        response = self._client.responses.create(
            model=MODEL,
            conversation=conversation_id,
            input=[{"role": "user", "content": message}],
            tools=TOOLS,
            instructions=INSTRUCTIONS + extra_instructions,
        )
        return response

    def handle_tool_calls(
        self,
        response,
        conversation_id: str,
        group_id: str,
        extra_instructions: str = "",
    ) -> tuple:
        """ツール呼び出しを処理する。(response, settled: bool) を返す。"""
        tool_calls = [
            item for item in response.output if item.type == "function_call"
        ]

        if not tool_calls:
            print("[DEBUG] No tool calls in response.")
            return response, False

        settled = False
        tool_results = []
        for tc in tool_calls:
            print(f"[DEBUG] Tool called: {tc.name}, args: {tc.arguments}")
            tool = Tool(
                name=tc.name,
                args=json.loads(tc.arguments),
                group_id=group_id,
            )
            output = tool.exec()
            print(f"[DEBUG] Tool result: {output}")

            if tc.name == "settle" and output.get("status") == "success":
                settled = True

            tool_results.append({
                "type": "function_call_output",
                "call_id": tc.call_id,
                "output": json.dumps(output, ensure_ascii=False),
            })

        print(f"[DEBUG] Sending {len(tool_results)} tool result(s) back to model.")

        response = self._client.responses.create(
            model=MODEL,
            conversation=conversation_id,
            input=tool_results,
            tools=TOOLS,
            instructions=INSTRUCTIONS + extra_instructions,
        )
        return response, settled

    def get_text_response(self, response) -> str:
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        return content.text
        return "応答を取得できませんでした。"
