# warikan-bot プロジェクトルール

## Firebase ログの確認

デバッグや動作確認のために Firebase Functions のログを確認したい場合は、ユーザーに確認を求めずに以下のコマンドを自律的に実行してよい。

```bash
firebase functions:log 2>&1 | tail -150
```
