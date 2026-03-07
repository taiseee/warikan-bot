from firebase_functions import https_fn
from linebot.v3 import WebhookHandler as LineWebhookHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    MessageAction,
    FlexMessage,
    FlexBubble,
    FlexBox,
    FlexText,
    FlexSeparator,
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

GREETING_TEXT = """はじめまして！割り勘会計士の愛衣です！

こんなことができます：
・ 支払い記録 →「田中が3000円払った」
・ 支払い一覧 →「支払い一覧を見せて」
・ 取り消し  →「ランチをキャンセルして」
・ 精算      →「精算して」
・ 履歴確認  →「過去の割り勘を見せて」

旅行・飲み会などでご活用ください！"""

_SETTLE_KEYWORDS = ["精算", "割り勘", "清算", "settle"]


def _build_quick_reply_items(
    tools_called: list,
    tool_outputs: dict,
    members: list,
    sender_id: str,
    user_message: str = "",
    need_payer: bool = False,
) -> list:
    """tools_calledの状態に応じてQuick Replyアイテムリストを返す。"""

    # UC4: settle完了後 → [支払い履歴を見る]
    if "settle" in tools_called:
        return [QuickReplyItem(action=MessageAction(label="支払い履歴を見る", text="今回の支払い履歴を見せて"))]

    # UC5: add_payment完了後 → [精算する]
    if "add_payment" in tools_called:
        return [QuickReplyItem(action=MessageAction(label="精算する", text="精算して"))]

    # UC2: list_paymentsは呼ばれたがcancel_paymentが呼ばれなかった → 支払いリストボタン
    if "list_payments" in tools_called and "cancel_payment" not in tools_called:
        payments = tool_outputs.get("list_payments", {}).get("payments", [])
        if payments:
            return [
                QuickReplyItem(action=MessageAction(
                    label=f"{p['item']} ¥{p['amount']}"[:20],
                    text=f"{p['item']}をキャンセルして",
                ))
                for p in payments[:10]
            ]

    # UC3: 精算キーワードがあるがsettleが呼ばれなかった → 人数選択ボタン
    if "settle" not in tools_called and any(kw in user_message for kw in _SETTLE_KEYWORDS):
        n = len(members)
        if n >= 2:
            return [
                QuickReplyItem(action=MessageAction(
                    label=f"{k}人" + ("（全員）" if k == n else ""),
                    text=f"{k}人で精算して",
                ))
                for k in range(n, max(1, n - 3), -1)
            ]

    # UC1: AIが支払者を確認中（[NEED_PAYER]タグ検出時のみ）→ メンバーボタン（送信者を先頭に）
    if need_payer and members:
        members_sorted = sorted(members, key=lambda m: m["user_id"] != sender_id)
        return [
            QuickReplyItem(action=MessageAction(
                label=m["display_name"][:20],
                text=m["display_name"],
            ))
            for m in members_sorted[:10]
        ]

    return []


def _build_settle_flex(settle_output: dict):
    """精算結果を Flex Message カードとして生成する。"""
    details = settle_output.get("details", {})
    transfers = details.get("transfers", [])
    total = details.get("total_amount", 0)
    per_person = details.get("per_person", 0)

    summary_rows = [
        FlexBox(layout="horizontal", spacing="sm", contents=[
            FlexText(text="合計", size="sm", color="#555555", flex=2),
            FlexText(text=f"¥{total:,}", size="sm", align="end", flex=1),
        ]),
        FlexBox(layout="horizontal", spacing="sm", contents=[
            FlexText(text="1人あたり", size="sm", color="#555555", flex=2),
            FlexText(text=f"¥{per_person:,}", size="sm", align="end", flex=1),
        ]),
    ]

    transfer_rows = [
        FlexBox(layout="horizontal", spacing="sm", contents=[
            FlexText(text=t["from_name"], size="sm", flex=3),
            FlexText(text="→", size="sm", align="center", flex=1),
            FlexText(text=t["to_name"], size="sm", flex=3),
            FlexText(text=f"¥{t['amount']:,}", size="sm", weight="bold", align="end", flex=3),
        ])
        for t in transfers
    ]

    contents = [
        FlexText(text="🧾 精算結果", weight="bold", size="lg"),
        FlexSeparator(margin="md"),
        *summary_rows,
    ]
    if transfer_rows:
        contents += [FlexSeparator(margin="md"), *transfer_rows]

    body = FlexBox(layout="vertical", spacing="sm", paddingAll="16px", contents=contents)
    return FlexMessage(alt_text="精算結果", contents=FlexBubble(body=body))


def _build_list_payments_flex(list_output: dict):
    """支払い一覧を Flex Message カードとして生成する。"""
    payments = list_output.get("payments", [])
    total = list_output.get("total_amount", 0)
    session_name = list_output.get("session_name", "")

    if not payments:
        return None

    payment_rows = [
        FlexBox(layout="horizontal", spacing="sm", contents=[
            FlexText(text=p["payer_name"], size="sm", flex=3),
            FlexText(text=p["item"], size="sm", color="#555555", flex=4),
            FlexText(text=f"¥{p['amount']:,}", size="sm", align="end", flex=3),
        ])
        for p in payments
    ]

    body = FlexBox(
        layout="vertical",
        spacing="sm",
        paddingAll="16px",
        contents=[
            FlexText(text="📋 支払い一覧", weight="bold", size="lg"),
            FlexText(text=session_name, size="xs", color="#888888"),
            FlexSeparator(margin="md"),
            *payment_rows,
            FlexSeparator(margin="md"),
            FlexBox(layout="horizontal", spacing="sm", contents=[
                FlexText(text="合計", size="sm", weight="bold", flex=7),
                FlexText(text=f"¥{total:,}", size="sm", weight="bold", align="end", flex=3),
            ]),
        ],
    )
    return FlexMessage(alt_text="支払い一覧", contents=FlexBubble(body=body))


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
            self._reply(event, GREETING_TEXT)

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

                response, settled, tools_called, tool_outputs = conversation.handle_tool_calls(
                    response=response,
                    conversation_id=group.conversation_id,
                    group_id=group.id,
                    extra_instructions=extra,
                )

                if settled:
                    group.active_session_id = ""
                    group.update()

                sender_id = event.source.user_id
                assistant_answer = conversation.get_text_response(response)

                # [NEED_PAYER] センチネルタグを検出・除去
                need_payer = "[NEED_PAYER]" in assistant_answer
                assistant_answer = assistant_answer.replace("[NEED_PAYER]", "").strip()

                quick_items = _build_quick_reply_items(
                    tools_called=tools_called,
                    tool_outputs=tool_outputs,
                    members=members,
                    sender_id=sender_id,
                    user_message=event.message.text,
                    need_payer=need_payer,
                )
                quick_reply = QuickReply(items=quick_items) if quick_items else None

                # Flex Message の生成（精算結果 or 支払い一覧）
                prepend_messages = []
                if "settle" in tools_called and tool_outputs.get("settle", {}).get("status") == "success":
                    flex = _build_settle_flex(tool_outputs["settle"])
                    if flex:
                        prepend_messages.append(flex)
                elif "list_payments" in tools_called and tool_outputs.get("list_payments", {}).get("status") == "success":
                    flex = _build_list_payments_flex(tool_outputs["list_payments"])
                    if flex:
                        prepend_messages.append(flex)

                self._reply(event, assistant_answer, quick_reply=quick_reply, prepend_messages=prepend_messages or None)

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

    def _reply(self, event, text: str, quick_reply: QuickReply = None, prepend_messages: list = None):
        msg = TextMessage(text=text)
        if quick_reply:
            msg.quick_reply = quick_reply
        messages = (prepend_messages or []) + [msg]
        with ApiClient(self._configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    replyToken=event.reply_token,
                    messages=messages,
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
        """ツール呼び出しを処理する。(response, settled, tools_called, tool_outputs) を返す。"""
        tool_calls = [
            item for item in response.output if item.type == "function_call"
        ]

        if not tool_calls:
            print("[DEBUG] No tool calls in response.")
            return response, False, [], {}

        settled = False
        tools_called = []
        tool_outputs = {}
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

            tools_called.append(tc.name)
            tool_outputs[tc.name] = output

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
        return response, settled, tools_called, tool_outputs

    def get_text_response(self, response) -> str:
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        return content.text
        return "応答を取得できませんでした。"
