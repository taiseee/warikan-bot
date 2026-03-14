# warikan-bot 移行計画

## 概要

本計画は、warikan-bot の依存ライブラリおよび OpenAI API を最新版に移行するためのものです。

| 項目 | 現在 | 移行先 |
|---|---|---|
| OpenAI モデル | `gpt-4-1106-preview` | `gpt-4.1` |
| OpenAI API | Assistants API (`client.beta.threads`) | Responses API + Conversations API |
| line-bot-sdk | `3.9.0` | `3.22.0` |
| firebase-functions | `~=0.1.0` | `~=0.5.0` |
| openai | バージョン未固定 | `>=1.75.0` (Conversations API サポート版) |

**期限**: Assistants API は 2026年8月26日に廃止

---

## Phase 1: 依存ライブラリの更新 (低リスク)

### 目的
OpenAI 移行の前に、他の依存関係を安定させる。

### 変更内容

#### `functions/requirements.txt`
```
firebase_functions~=0.5.0
firebase_admin
openai>=1.75.0
line-bot-sdk~=3.22.0
```

### 確認事項
- [ ] Python >= 3.10 であることを確認 (firebase-functions 0.5.0 の要件)
- [ ] `firebase deploy --only functions` でデプロイが成功すること
- [ ] LINE Bot の基本的なメッセージ送受信が動作すること

### リスク
- **line-bot-sdk**: 本プロジェクトで使用する `MessagingApi`, `WebhookHandler` には破壊的変更なし
- **firebase-functions**: `SecretParam`, `https_fn`, `options` の基本 API は変更なし
- **Python バージョン**: firebase-functions 0.5.0 は Python >= 3.10 が必須。Cloud Functions のランタイムが対応していることを確認

---

## Phase 2: OpenAI Assistants API → Responses API + Conversations API 移行 (高リスク)

### 目的
廃止予定の Assistants API を、Responses API + Conversations API に置き換える。

### アーキテクチャの変更

#### 現在のフロー (Assistants API)
```
1. Thread.open()       → client.beta.threads.create() / .retrieve()
2. Thread.add_message() → client.beta.threads.messages.create()
3. Thread.run()         → client.beta.threads.runs.create(assistant_id=...)
4. ポーリングループ     → client.beta.threads.runs.retrieve() を1秒ごと
5. ツール実行           → client.beta.threads.runs.submit_tool_outputs()
6. Thread.delete()      → client.beta.threads.delete()
```

#### 新しいフロー (Responses API + Conversations API)
```
1. Conversation 作成/取得 → client.conversations.create() / Firestore から ID 取得
2. レスポンス作成        → client.responses.create(
                              model="gpt-4.1",
                              conversation=conversation_id,
                              input=[{"role": "user", "content": message}],
                              tools=TOOLS,
                              instructions=INSTRUCTIONS
                           )
3. ツール呼び出し判定    → response.output 内の function_call を確認
4. ツール実行+再送信     → function_call_output を input に追加して再度 responses.create()
5. 会話リセット          → Firestore の conversation_id をクリア
```

**主な改善点:**
- ポーリングループが不要 (同期的にレスポンスが返る)
- `ASSISTANT_ID` シークレットが不要 (instructions をインラインで指定)
- `create_assistant` Cloud Function が不要
- コードが大幅にシンプル化

### ファイルごとの変更内容

---

#### 1. `functions/src/secrets.py`

**変更**: `ASSISTANT_ID` の削除

```python
from firebase_functions.params import SecretParam

# openai
OPENAI_API_KEY: str = SecretParam("OPENAI_API_KEY").value
OPENAI_ORGANIZATION: str = SecretParam("OPENAI_ORGANIZATION").value

# line
CHANNEL_SECRET: str = SecretParam("CHANNEL_SECRET").value
CHANNEL_ACCESS_TOKEN: str = SecretParam("CHANNEL_ACCESS_TOKEN").value
```

---

#### 2. `functions/src/model/group.py`

**変更**: `thread_id` → `conversation_id` に変更

```python
from firebase_admin import firestore
from firebase_functions.firestore_fn import DocumentSnapshot


class Group:
    def __init__(self, id: str = "", conversation_id: str = "",
                 created_at=firestore.SERVER_TIMESTAMP,
                 updated_at=firestore.SERVER_TIMESTAMP):
        self._collection = firestore.client().collection("groups")
        self.id = id
        self.conversation_id = conversation_id
        self.created_at = created_at
        self.updated_at = updated_at

    def to_dict(self) -> dict:
        return {
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def from_doc(self, doc: DocumentSnapshot) -> "Group":
        dict = doc.to_dict()
        return Group(
            id=doc.id,
            conversation_id=dict.get("conversation_id", ""),
            created_at=dict.get("created_at"),
            updated_at=dict.get("updated_at"),
        )

    def fetch_or_create(self, group_id: str) -> "Group":
        group_ref = self._collection.document(group_id)
        group = group_ref.get()
        if group.exists:
            return Group().from_doc(group)
        group = Group(id=group_id)
        group_ref.set(group.to_dict())
        return group

    def update(self):
        self.updated_at = firestore.SERVER_TIMESTAMP
        self._collection.document(self.id).update(self.to_dict())
        return self
```

**Firestore 移行**: 既存ドキュメントの `thread_id` フィールドは、新しいコードでは参照されなくなる。次回の会話開始時に `conversation_id` が空として扱われ、新規会話が作成される。データの手動移行は不要。

---

#### 3. `functions/src/assistant_factory.py`

**変更**: `AssistantFactory` クラスを削除し、定数モジュールに変更

```python
# OpenAI Responses API 用の設定定数

MODEL = "gpt-4.1"

TOOLS = [
    {
        "type": "function",
        "name": "PaymentService_add",
        "description": "ユーザーが立て替えて行なった支払いを記録する",
        "parameters": {
            "type": "object",
            "properties": {
                "payer_name": {
                    "type": "string",
                    "description": "支払いを行なったユーザーの名前",
                },
                "amount": {"type": "integer", "description": "支払い金額"},
                "item": {"type": "string", "description": "支払いの項目"},
            },
            "required": ["payer_name", "amount", "item"],
        },
    },
    {
        "type": "function",
        "name": "PaymentService_settle",
        "description": "グループ内での支払いを精算し、誰が誰に対していくら支払うかを返す",
        "parameters": {
            "type": "object",
            "properties": {
                "div_num": {
                    "type": "integer",
                    "description": "精算を行う人数",
                }
            },
            "required": ["div_num"],
        },
    },
]

INSTRUCTIONS = """
あなたはグループ内の支払いを管理するための優秀な会計士です．
### 指示
あなたは以下の2つの仕事を遂行します．
支払いの記録...グループ内での支払いを記録する
支払いの精算...グループ内での支払いを精算し、誰が誰に対していくら支払うかを返す

### 支払いの記録フロー
1. ユーザーが立て替えに関して発言する
2. あなたはユーザーの発言から`支払った人`，`項目`，`いくらか`を読み取る
3. 情報が不足している場合はユーザーに質問を投げかける
4. 支払いを記録する
5. ユーザーに記録した内容を伝える

### 支払いの精算フロー
1. ユーザーが精算を要求する
2. あなたはユーザーの発言から`精算を行う人数`を読み取る
3. 読み取れない場合は`精算を行う人数`をユーザーに尋ねる
4. 支払いを精算する
5. ユーザーに精算結果を伝える
"""
```

**注意**: Responses API のツール定義形式は Assistants API と異なる。`function` ラッパーが不要になり、`name` がトップレベルに移動する。

---

#### 4. `functions/src/warikanbot.py`

**変更**: `Thread` クラスを削除し、Responses API ベースの `Conversation` クラスに置き換え

主要な変更点:
- `Thread` クラス → 削除
- `Message` クラス → 削除
- `Assistant` クラス → `is_mentioned` のみ残す (必要なら)
- 新規: `Conversation` クラス (Conversations API + Responses API をラップ)
- `WebhookHandler._add()` 内のフロー全体を書き換え

```python
from firebase_functions import https_fn
from linebot.v3 import WebhookHandler as LineWebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
from openai import OpenAI
import json
from .secrets import (
    OPENAI_API_KEY, OPENAI_ORGANIZATION,
    CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN,
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
                {"message": "Invalid signature."}, status=400,
            )

    def _add(self):
        @self._handler.add(MessageEvent, message=TextMessageContent)
        def handler_message(event: MessageEvent) -> https_fn.Response:
            group = Group().fetch_or_create(event.source.group_id)
            conversation = Conversation()

            try:
                # 会話IDがなければ新規作成
                if not group.conversation_id:
                    conv = conversation.create()
                    group.conversation_id = conv
                    group.update()

                # Responses API でメッセージ送信
                response = conversation.send_message(
                    conversation_id=group.conversation_id,
                    message=event.message.text,
                )

                # ツール呼び出しの処理
                response = conversation.handle_tool_calls(
                    response=response,
                    conversation_id=group.conversation_id,
                    group_id=group.id,
                )

                # アシスタントの応答テキストを取得
                assistant_answer = conversation.get_text_response(response)

                # LINE に返信
                self._reply(event, assistant_answer)

                # 精算完了時は会話をリセット
                if conversation.should_reset(response, group.id):
                    group.conversation_id = ""
                    group.update()

            except Exception as e:
                print(f"Error: {e}")
                self._reply(event, "すみません、技術的な問題が発生しました。")
                group.conversation_id = ""
                group.update()

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
        """新しい会話を作成し、会話IDを返す"""
        conv = self._client.conversations.create()
        return conv.id

    def send_message(self, conversation_id: str, message: str):
        """メッセージを送信してレスポンスを返す"""
        response = self._client.responses.create(
            model=MODEL,
            conversation=conversation_id,
            input=[{"role": "user", "content": message}],
            tools=TOOLS,
            instructions=INSTRUCTIONS,
        )
        return response

    def handle_tool_calls(self, response, conversation_id: str, group_id: str):
        """レスポンス内のツール呼び出しを処理し、結果を送信する"""
        tool_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        if not tool_calls:
            return response

        # ツールの実行結果を収集
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

        # ツール実行結果を送信して最終レスポンスを取得
        response = self._client.responses.create(
            model=MODEL,
            conversation=conversation_id,
            input=tool_results,
            tools=TOOLS,
            instructions=INSTRUCTIONS,
        )
        return response

    def get_text_response(self, response) -> str:
        """レスポンスからテキストを抽出する"""
        for item in response.output:
            if item.type == "message":
                for content in item.content:
                    if content.type == "output_text":
                        return content.text
        return "応答を取得できませんでした。"

    def should_reset(self, response, group_id: str) -> bool:
        """精算が完了したかどうかを判定する"""
        for item in response.output:
            if item.type == "function_call" and item.name == "PaymentService_settle":
                return True
        return False
```

---

#### 5. `functions/main.py`

**変更**: `ASSISTANT_ID` シークレットの削除、`create_assistant` 関数の削除

```python
from firebase_functions import https_fn, options
from firebase_admin import initialize_app
from src.warikanbot import WebhookHandler

initialize_app()
options.set_global_options(region=options.SupportedRegion.ASIA_NORTHEAST1)


@https_fn.on_request(
    secrets=[
        "CHANNEL_ACCESS_TOKEN",
        "CHANNEL_SECRET",
        "OPENAI_API_KEY",
        "OPENAI_ORGANIZATION",
    ],
    timeout_sec=120
)
def webhook(req: https_fn.Request) -> https_fn.Response:
    body = req.get_data(as_text=True)
    signature = req.headers["X-Line-Signature"]
    handler = WebhookHandler()
    return handler.handle(body, signature)
```

---

#### 6. `functions/db.md`

**変更**: スキーマの更新

```markdown
# groups
## column
id: int
conversation_id: string
created_at: datetime
updated_at: datetime
## subcollection
payers

# payers
## column
id: int
name: string
## subcollection
statements

# statements
## column
id: int
amount: int
```

---

## Phase 3: テストと検証

### テスト項目

#### 基本動作テスト
- [ ] LINE Bot がメッセージを受信して応答を返すこと
- [ ] 支払い記録: 「太郎がランチ代1000円を払った」→ 記録成功メッセージが返ること
- [ ] 情報不足時の質問: 「ランチ代払った」→ 金額や名前を聞き返すこと
- [ ] 精算: 「3人で精算して」→ 精算結果が返ること
- [ ] 精算後に会話がリセットされること

#### エラーハンドリングテスト
- [ ] OpenAI API エラー時にエラーメッセージが返ること
- [ ] 会話がリセットされ、次回正常に動作すること

#### 互換性テスト
- [ ] 既存の Firestore データ (`thread_id` フィールド) が残っていても動作すること
- [ ] 新規グループで `conversation_id` が正しく作成されること

---

## Phase 4: クリーンアップ

### 実施内容
- [ ] Firebase のシークレットから `ASSISTANT_ID` を削除
- [ ] OpenAI ダッシュボードから不要な Assistant を削除
- [ ] Firestore の `thread_id` フィールドを必要に応じてクリーンアップ (任意)

---

## ロールバック計画

### Phase 1 (依存ライブラリ) のロールバック
- `requirements.txt` を元のバージョンに戻してデプロイ

### Phase 2 (OpenAI API) のロールバック
- git で前のコミットに戻してデプロイ
- `ASSISTANT_ID` シークレットが残っていれば即時ロールバック可能
- **重要**: Phase 4 (ASSISTANT_ID 削除) を実施する前にロールバックが不要であることを確認

### リスク軽減策
- Phase 2 完了後、最低1週間は Phase 4 を実施しない
- ロールバックが必要になった場合に備えて、既存の Assistant ID を記録しておく

---

## タイムライン (推奨)

| Phase | 内容 | 推定期間 |
|---|---|---|
| Phase 1 | 依存ライブラリの更新 | 1日 |
| Phase 2 | OpenAI API 移行 | 2-3日 |
| Phase 3 | テスト・検証 | 1-2日 |
| Phase 4 | クリーンアップ | Phase 3 完了の1週間後 |

---

## 参考リンク

- [OpenAI Responses API ドキュメント](https://developers.openai.com/api/docs/responses)
- [OpenAI Conversations API ドキュメント](https://developers.openai.com/api/docs/guides/conversation-state)
- [OpenAI Function Calling ガイド](https://developers.openai.com/api/docs/guides/function-calling)
- [Assistants API 移行ガイド](https://developers.openai.com/api/docs/assistants/migration/)
- [firebase-functions-python リリースノート](https://github.com/firebase/firebase-functions-python/releases)
- [line-bot-sdk-python リリースノート](https://github.com/line/line-bot-sdk-python/releases)
