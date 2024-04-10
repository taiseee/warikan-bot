from firebase_functions.params import SecretParam
from openai import OpenAI
from .secrets import (
    OPENAI_API_KEY,
    OPENAI_ORGANIZATION,
)


class AssistantFactory:
    _OPENAI_API_KEY: str = OPENAI_API_KEY
    _OPENAI_ORGANIZATION: str = OPENAI_ORGANIZATION
    _TOOLS: list = [
        {
            "type": "function",
            "function": {
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
        },
        {
            "type": "function",
            "function": {
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
        },
    ]
    _MODEL = "gpt-4-1106-preview"
    _NAME = "割り勘会計士"
    _INSTRUCTIONS = """
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

    def __init__(self):
        self._client = OpenAI(
            api_key=self._OPENAI_API_KEY, organization=self._OPENAI_ORGANIZATION
        )

    def create(self):
        assistant = self._client.beta.assistants.create(
            name=self._NAME,
            instructions=self._INSTRUCTIONS,
            model=self._MODEL,
            tools=self._TOOLS,
        )

        return assistant
