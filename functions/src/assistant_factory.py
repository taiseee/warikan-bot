MODEL = "gpt-4.1"

TOOLS = [
    {
        "type": "function",
        "name": "start_session",
        "description": "新しい割り勘セッションを開始します。アクティブなセッションが既にある場合は先に精算が必要です。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "セッション名（例: '沖縄旅行'）。省略時は日付から自動生成。",
                }
            },
        },
    },
    {
        "type": "function",
        "name": "add_payment",
        "description": "アクティブなセッションに支払いを記録します。アクティブなセッションがない場合は自動で作成します。",
        "parameters": {
            "type": "object",
            "properties": {
                "payer_id": {
                    "type": "string",
                    "description": "支払いをした人のLINE user_id（グループメンバー一覧から取得）",
                },
                "amount": {"type": "integer", "description": "支払い金額（円）"},
                "item": {"type": "string", "description": "支払いの内容"},
            },
            "required": ["payer_id", "amount", "item"],
        },
    },
    {
        "type": "function",
        "name": "cancel_payment",
        "description": "記録済みの支払いを取り消します（物理削除）。精算済みセッションは不可。",
        "parameters": {
            "type": "object",
            "properties": {
                "payment_id": {
                    "type": "string",
                    "description": "取り消す支払いのID（list_payments で確認）",
                }
            },
            "required": ["payment_id"],
        },
    },
    {
        "type": "function",
        "name": "list_payments",
        "description": "現在のアクティブセッションの支払い一覧を取得します。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "settle",
        "description": "割り勘を精算します。結果を保存しセッションを完了にします。div_num を省略するとグループメンバー数で等分します。",
        "parameters": {
            "type": "object",
            "properties": {
                "div_num": {
                    "type": "integer",
                    "description": "割り勘人数。省略時はグループメンバー数を自動使用",
                }
            },
        },
    },
    {
        "type": "function",
        "name": "list_sessions",
        "description": "このグループの割り勘履歴一覧を取得します。",
        "parameters": {
            "type": "object",
            "properties": {
                "is_settled": {
                    "type": "boolean",
                    "description": "true=精算済みのみ、false=進行中のみ。省略時は全件",
                }
            },
        },
    },
    {
        "type": "function",
        "name": "get_session_detail",
        "description": "指定セッションの支払い一覧と精算結果を取得します。",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "セッションID（list_sessions で確認）",
                }
            },
            "required": ["session_id"],
        },
    },
]

INSTRUCTIONS = """
あなたはグループ内の支払いを管理するための優秀な会計士です。

### 基本フロー
- 支払いを記録: add_payment を呼ぶ（アクティブセッションがなければ自動作成）
- 支払い一覧確認: list_payments を呼ぶ
- 支払い取り消し: list_payments で payment_id を確認してから cancel_payment を呼ぶ
- 精算: settle を呼ぶ（div_num 不要、メンバー数で自動計算）
- 新しい割り勘を明示的に始める: start_session を呼ぶ（既存セッションがあれば先に精算を促す）
- 過去の履歴確認: list_sessions → get_session_detail の順で呼ぶ

### 支払い記録のフロー
1. ユーザーの発言から「支払った人」「項目」「金額」を読み取る
2. 情報が不足していればユーザーに質問する
3. グループメンバー一覧から payer_id を特定して add_payment を呼ぶ
4. 記録した内容をユーザーに伝える

### 精算フロー
1. 精算を求められたら、まず「X人で精算してよいですか？」と確認する（X = グループメンバー数）
2. ユーザーが人数を明示した場合、または確認に同意した場合のみ settle を呼ぶ
3. 結果をユーザーにわかりやすく伝える（誰が誰に何円払うか）

### 重要なルール
- add_payment の payer_id は必ずグループメンバー一覧の user_id を使用する
- 「誰が払ったか」が不明なときはユーザーに確認する。その場合、返答の末尾（改行後）に `[NEED_PAYER]` と追記すること（例: 「誰が払いましたか？\n[NEED_PAYER]」）
- start_session は「新しい割り勘を始めたい」と明示された時のみ呼ぶ（通常は add_payment が自動でセッションを作成する）
- エラーが返ってきた場合はユーザーにわかりやすく伝え、解決策を提案する
- 支払い一覧・精算結果・履歴など、データの正確性が求められる情報は会話の記憶に頼らず、必ず毎回ツールを呼び出して最新データを取得すること
"""
