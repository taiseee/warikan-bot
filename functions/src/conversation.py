"""OpenAI Conversation management -- thread creation, messaging, tool call loop."""

from __future__ import annotations

import json
from typing import Callable

from openai import OpenAI

from .secrets import OPENAI_API_KEY, OPENAI_ORGANIZATION
from .assistant_factory import MODEL, TOOLS, INSTRUCTIONS


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
        tool_executor: Callable[[str, dict], dict],
        extra_instructions: str = "",
    ) -> tuple:
        """ツール呼び出しを処理する。

        Args:
            response: OpenAI response object
            conversation_id: 会話スレッドID
            tool_executor: (name, args) -> dict のcallable。Controller側で注入。
            extra_instructions: 追加インストラクション

        Returns:
            (response, settled, tools_called, tool_outputs)
        """
        settled = False
        tools_called = []
        tool_outputs = {}

        for _ in range(10):  # 無限ループ防止
            tool_calls = [
                item for item in response.output if item.type == "function_call"
            ]

            if not tool_calls:
                print("[DEBUG] No tool calls in response.")
                break

            tool_results = []
            for tc in tool_calls:
                print(f"[DEBUG] Tool called: {tc.name}, args: {tc.arguments}")
                output = tool_executor(tc.name, json.loads(tc.arguments))
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
