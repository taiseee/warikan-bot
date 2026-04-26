# warikan-bot プロジェクトルール

## 外部ライブラリ・SDK・API を使う際のルール

外部のライブラリ・SDK・API（LINE Messaging API、Firebase、OpenAI 等）を利用・調査・実装する際は、**必ず公式ドキュメントや SDK のソースコードを事前に確認してから**、計画・報告・実装を行うこと。

- 情報が古い・不正確な可能性があるため、記憶や推測で実装してはいけない
- 調査してから報告する（逆順にしない）

## Firebase ログの確認

デバッグや動作確認のために Firebase Functions のログを確認したい場合は、ユーザーに確認を求めずに以下のコマンドを自律的に実行してよい。

```bash
firebase functions:log 2>&1 | tail -150
```
