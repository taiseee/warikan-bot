"""LINE UI message builders -- Flex Messages and QuickReply construction."""

from linebot.v3.messaging import (
    QuickReply,
    QuickReplyItem,
    PostbackAction,
    FlexMessage,
    FlexBubble,
    FlexBox,
    FlexText,
    FlexSeparator,
)

_SETTLE_KEYWORDS = ["精算", "割り勘", "清算", "settle"]


def build_quick_reply_items(
    tools_called: list,
    tool_outputs: dict,
    members: list,
    sender_id: str,
    user_message: str = "",
    need_payer: bool = False,
) -> list:
    """tools_calledの状態に応じてQuick Replyアイテムリストを返す。"""

    def _qr(label: str, text: str) -> QuickReplyItem:
        return QuickReplyItem(action=PostbackAction(label=label, data=text, display_text=text))

    # UC4: settle完了後 → [支払い履歴を見る]
    if "settle" in tools_called:
        return [_qr("支払い履歴を見る", "今回の支払い履歴を見せて")]

    # UC5: add_payment完了後 → [精算する]
    if "add_payment" in tools_called:
        return [_qr("精算する", "精算して")]

    # UC2: list_paymentsは呼ばれたがcancel_paymentが呼ばれなかった → 支払いリストボタン
    if "list_payments" in tools_called and "cancel_payment" not in tools_called:
        payments = tool_outputs.get("list_payments", {}).get("payments", [])
        if payments:
            return [
                _qr(f"{p['item']} ¥{p['amount']}"[:20], f"{p['item']}をキャンセルして")
                for p in payments[:10]
            ]

    # UC3: 精算キーワードがあるがsettleが呼ばれなかった → 人数選択ボタン
    if "settle" not in tools_called and any(kw in user_message for kw in _SETTLE_KEYWORDS):
        n = len(members)
        if n >= 2:
            return [
                _qr(f"{k}人" + ("（全員）" if k == n else ""), f"{k}人で精算して")
                for k in range(n, max(1, n - 3), -1)
            ]

    # UC1: AIが支払者を確認中（[NEED_PAYER]タグ検出時のみ）→ メンバーボタン（送信者を先頭に）
    if need_payer and members:
        members_sorted = sorted(members, key=lambda m: m["user_id"] != sender_id)
        return [
            _qr(m["display_name"][:20], m["display_name"])
            for m in members_sorted[:10]
        ]

    return []


def build_settle_flex(settle_output: dict):
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


def build_get_session_detail_flex(detail_output: dict):
    """セッション詳細を Flex Message カードとして生成する。"""
    payments = detail_output.get("payments", [])
    session_name = detail_output.get("name", "")
    is_settled = detail_output.get("is_settled", False)
    settlement_result = detail_output.get("settlement_result") or {}

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

    total = sum(p["amount"] for p in payments)
    contents = [
        FlexText(text="📋 支払い履歴", weight="bold", size="lg"),
        FlexText(text=session_name, size="xs", color="#888888"),
        FlexSeparator(margin="md"),
        *payment_rows,
        FlexSeparator(margin="md"),
        FlexBox(layout="horizontal", spacing="sm", contents=[
            FlexText(text="合計", size="sm", weight="bold", flex=7),
            FlexText(text=f"¥{total:,}", size="sm", weight="bold", align="end", flex=3),
        ]),
    ]

    if is_settled and settlement_result:
        per_person = settlement_result.get("per_person", 0)
        transfers = settlement_result.get("transfers", [])
        contents.append(FlexSeparator(margin="md"))
        contents.append(FlexBox(layout="horizontal", spacing="sm", contents=[
            FlexText(text="1人あたり", size="sm", color="#555555", flex=7),
            FlexText(text=f"¥{per_person:,}", size="sm", align="end", flex=3),
        ]))
        for t in transfers:
            contents.append(FlexBox(layout="horizontal", spacing="sm", contents=[
                FlexText(text=t["from_name"], size="sm", flex=3),
                FlexText(text="→", size="sm", align="center", flex=1),
                FlexText(text=t["to_name"], size="sm", flex=3),
                FlexText(text=f"¥{t['amount']:,}", size="sm", weight="bold", align="end", flex=3),
            ]))

    body = FlexBox(layout="vertical", spacing="sm", paddingAll="16px", contents=contents)
    return FlexMessage(alt_text=f"{session_name} 支払い履歴", contents=FlexBubble(body=body))


def build_list_payments_flex(list_output: dict):
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
