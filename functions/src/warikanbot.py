from firebase_functions import https_fn
from linebot.v3 import WebhookHandler as LineWebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    QuickReply,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, JoinEvent, PostbackEvent
from linebot.v3.exceptions import InvalidSignatureError

from .secrets import CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN
from .model import Group
from .payment_service import PaymentService
from .repository import GroupRepository, SessionRepository, PaymentRepository
from .conversation import Conversation
from .line_ui import (
    build_quick_reply_items,
    build_settle_flex,
    build_get_session_detail_flex,
    build_list_payments_flex,
)

GREETING_TEXT = """はじめまして！割り勘会計士の愛衣です！

こんなことができます：
・ 支払い記録 →「田中が3000円払った」
・ 支払い一覧 →「支払い一覧を見せて」
・ 取り消し  →「ランチをキャンセルして」
・ 精算      →「精算して」
・ 履歴確認  →「過去の割り勘を見せて」

旅行・飲み会などでご活用ください！"""


class WebhookHandler:
    _CHANNEL_SECRET: str = CHANNEL_SECRET
    _CHANNEL_ACCESS_TOKEN: str = CHANNEL_ACCESS_TOKEN

    def __init__(self):
        self._configuration = Configuration(access_token=self._CHANNEL_ACCESS_TOKEN)
        self._handler = LineWebhookHandler(self._CHANNEL_SECRET)

        # --- Composition Root: 具象リポジトリの生成と注入 ---
        self._group_repo = GroupRepository()
        session_repo = SessionRepository()
        payment_repo = PaymentRepository()
        self._payment_service = PaymentService(self._group_repo, session_repo, payment_repo)

        self._add()

    def _is_mentioned(self, event: MessageEvent) -> bool:
        mention = getattr(event.message, "mention", None)
        if not mention:
            return False
        return any(getattr(m, "is_self", False) for m in (mention.mentionees or []))

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
            group = self._group_repo.find_by_id(group_id)
            if not group:
                group = Group(id=group_id)
                self._group_repo.save(group)
            self._sync_all_members(group_id)
            self._reply(event, GREETING_TEXT)

        @self._handler.add(MessageEvent, message=TextMessageContent)
        def handler_message(event: MessageEvent) -> https_fn.Response:
            # グループチャットではメンションされた時だけ応答
            if getattr(event.source, "type", "") == "group" and not self._is_mentioned(event):
                return
            self._process_group_message(event, event.message.text)
            return https_fn.Response({"message": "success"}, status=200)

        @self._handler.add(PostbackEvent)
        def handler_postback(event: PostbackEvent) -> https_fn.Response:
            # PostbackEvent はQuick Replyボタン操作 → メンションチェック不要
            self._process_group_message(event, event.postback.data)
            return https_fn.Response({"message": "success"}, status=200)

        @self._handler.default()
        def default(event):
            return https_fn.Response({"message": "success"}, status=200)

    def _make_tool_executor(self, group_id: str):
        """Conversation に注入する tool_executor クロージャを生成する。"""
        def _exec_tool(name: str, args: dict) -> dict:
            return Tool(
                name=name, args=args, group_id=group_id,
                payment_service=self._payment_service,
            ).exec()
        return _exec_tool

    def _process_group_message(self, event, message_text: str):
        """グループメッセージ・ポストバックの共通処理。"""
        group_id = event.source.group_id
        group = self._group_repo.find_by_id(group_id)
        if not group:
            group = Group(id=group_id)
            self._group_repo.save(group)

        self._sync_member(group_id, event.source.user_id)

        conversation = Conversation()
        extra = ""
        tool_executor = self._make_tool_executor(group_id)

        try:
            if not group.conversation_id:
                conv_id = conversation.create()
                group.conversation_id = conv_id
                self._group_repo.save(group)

            # Group集約からメンバー取得（sync後に再取得）
            group = self._group_repo.find_by_id(group_id)
            members = [
                {"user_id": m.user_id, "display_name": m.display_name}
                for m in group.members
            ]
            members_context = "\n".join(
                f"- {m['user_id']}: {m['display_name']}" for m in members
            )
            extra = f"\n\n## グループメンバー\n{members_context}" if members_context else ""

            response = conversation.send_message(
                conversation_id=group.conversation_id,
                message=message_text,
                extra_instructions=extra,
            )

            response, settled, tools_called, tool_outputs = conversation.handle_tool_calls(
                response=response,
                conversation_id=group.conversation_id,
                tool_executor=tool_executor,
                extra_instructions=extra,
            )

            if settled:
                group.active_session_id = ""
                self._group_repo.save(group)

            sender_id = event.source.user_id
            assistant_answer = conversation.get_text_response(response)

            need_payer = "[NEED_PAYER]" in assistant_answer
            assistant_answer = assistant_answer.replace("[NEED_PAYER]", "").strip()

            quick_items = build_quick_reply_items(
                tools_called=tools_called,
                tool_outputs=tool_outputs,
                members=members,
                sender_id=sender_id,
                user_message=message_text,
                need_payer=need_payer,
            )
            quick_reply = QuickReply(items=quick_items) if quick_items else None

            prepend_messages = []
            if "settle" in tools_called and tool_outputs.get("settle", {}).get("status") == "success":
                flex = build_settle_flex(tool_outputs["settle"])
                if flex:
                    prepend_messages.append(flex)
            elif "list_payments" in tools_called and tool_outputs.get("list_payments", {}).get("status") == "success":
                flex = build_list_payments_flex(tool_outputs["list_payments"])
                if flex:
                    prepend_messages.append(flex)
            elif "get_session_detail" in tools_called and tool_outputs.get("get_session_detail", {}).get("status") == "success":
                flex = build_get_session_detail_flex(tool_outputs["get_session_detail"])
                if flex:
                    prepend_messages.append(flex)

            self._reply(event, assistant_answer, quick_reply=quick_reply, prepend_messages=prepend_messages or None)

        except Exception as e:
            print(f"Error: {e}")
            if "No tool output found" in str(e) and group.conversation_id:
                print("[DEBUG] Resetting broken conversation and retrying.")
                try:
                    conv_id = conversation.create()
                    group.conversation_id = conv_id
                    self._group_repo.save(group)
                    response = conversation.send_message(
                        conversation_id=group.conversation_id,
                        message=message_text,
                        extra_instructions=extra,
                    )
                    response, settled, tools_called, tool_outputs = conversation.handle_tool_calls(
                        response=response,
                        conversation_id=group.conversation_id,
                        tool_executor=tool_executor,
                        extra_instructions=extra,
                    )
                    if settled:
                        group.active_session_id = ""
                        self._group_repo.save(group)
                    sender_id = event.source.user_id
                    quick_items = build_quick_reply_items(
                        tools_called=tools_called,
                        tool_outputs=tool_outputs,
                        members=members,
                        sender_id=sender_id,
                        user_message=message_text,
                    )
                    quick_reply = QuickReply(items=quick_items) if quick_items else None
                    assistant_answer = conversation.get_text_response(response)
                    self._reply(event, assistant_answer, quick_reply=quick_reply)
                    return
                except Exception as retry_e:
                    print(f"Error on retry: {retry_e}")
            self._reply(event, "すみません、技術的な問題が発生しました。")

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
                group = self._group_repo.find_by_id(group_id)
                if group:
                    group.upsert_member(
                        user_id,
                        profile.display_name,
                        profile.picture_url or "",
                    )
                    self._group_repo.save(group)
                print(f"[DEBUG] Synced member {user_id}: {profile.display_name}")
            except Exception as e:
                print(f"[DEBUG] Failed to sync member {user_id}: {e}")

        if api_client:
            _do_sync(api_client)
        else:
            with ApiClient(self._configuration) as client:
                _do_sync(client)

    def _reply(self, event, text: str, quick_reply: QuickReply = None, prepend_messages: list = None):
        if prepend_messages:
            # Flex あり → TextMessage を省略し Quick Reply を Flex に付ける
            if quick_reply:
                prepend_messages[-1].quick_reply = quick_reply
            messages = prepend_messages
        else:
            msg = TextMessage(text=text)
            if quick_reply:
                msg.quick_reply = quick_reply
            messages = [msg]
        with ApiClient(self._configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    replyToken=event.reply_token,
                    messages=messages,
                )
            )


class Tool:
    def __init__(self, name: str = "", args: dict = None, group_id: str = "", payment_service: PaymentService = None):
        self._name = name
        self._args = args or {}
        self._group_id = group_id
        self._payment_service = payment_service

    def exec(self) -> dict:
        svc = self._payment_service
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
