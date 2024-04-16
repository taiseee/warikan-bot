from __future__ import annotations
from firebase_admin import firestore


class PaymentService:

    def __init__(self):
        self._db = firestore.client()

    def add(self, group_id: str, payment: dict[str, str | None]) -> dict:
        error = {
            "status": "error",
            "code": 500,
            "message": "Failed due to missing arguments.",
            "details": {},
        }
        required_args = ["payer_name", "item", "amount"]
        missing_args = [arg for arg in required_args if payment.get(arg) is None]

        if missing_args:
            error["details"]["missing_args"] = missing_args
            return error

        # 支払いの登録
        payer_doc = self._get_payer_doc(group_id, payment)

        # 支払いの項目を追加する
        statement_collection = payer_doc.collection("statements")
        statement_collection.add({"item": payment["item"], "amount": payment["amount"]})

        success = {
            "status": "success",
            "code": 200,
            "message": "Payment has been recorded successfully.",
            "details": {
                "payer_name": payment["payer_name"],
                "item": payment["item"],
                "amount": payment["amount"],
            },
        }

        return success

    def _get_payer_doc(self, group_id: str, payment: dict[str, str | None]):
        payer_collection = (
            self._db.collection("groups").document(group_id).collection("payers")
        )
        payer = payer_collection.where("name", "==", payment["payer_name"]).get()
        if len(payer) > 0:
            return payer_collection.document(payer[0].id)

        _, payer = payer_collection.add({"name": payment["payer_name"]})
        return payer_collection.document(payer.id)

    def settle(self, group_id: str, args: dict[str, str | None]) -> dict:
        error = {"status": "error", "code": 500}
        if args.get("div_num") is None:
            error["message"] = "Failed due to missing arguments."
            error["details"] = {"missing_args": ["div_num"]}
            return error

        div_num = int(args["div_num"])

        # グループ内での支払いを管理するドキュメントの有無を確認する
        payer_collection = (
            self._db.collection("groups").document(group_id).collection("payers")
        )
        payers = payer_collection.get()
        if len(payers) == 0:
            error["message"] = "No payment records found."
            return error

        if len(payers) > div_num:
            error["message"] = (
                "Set the number of people to be divided higher than the number of payers."
            )
            return error

        # 支払いを支払い者ごとに集計する
        paid = []
        for payer in payers:
            statement_collection = self._db.collection("groups").document(group_id).collection("payers").document(payer.id).collection("statements")
            statements = statement_collection.get()
            print(statements)
            paid.append(
                {
                    "name": payer.get("name"),
                    "amount": sum(
                        [statement.get("amount") for statement in statements]
                    ),
                }
            )
            # 集計し終わった支払い内容、支払い者を削除する
            for statement in statements:
                statement_collection.document(statement.id).delete()
            payer_collection.document(payer.id).delete()

        # 一度も支払っていない人を追加する
        if len(paid) < div_num:
            add = div_num - len(paid)
            for i in range(add):
                paid.append({"name": f"未登録{i}", "amount": 0})

        total_paid = sum([item.get("amount") for item in paid])
        average = total_paid / div_num

        payment_balance = []
        for i in range(div_num):
            payment_balance.append(
                {"name": paid[i]["name"], "amount": paid[i]["amount"] - average}
            )

        settlement = self.settle_calc(payment_balance, [])

        return {
            "status": "success",
            "code": 200,
            "message": "Settlement has been calculated successfully.",
            "details": settlement,
        }

    def settle_calc(
        self, payment: list[dict], settlement: list[dict]
    ) -> list[dict] | str:
        # 支払いの多い順に並び替える
        payment.sort(key=lambda x: x["amount"], reverse=True)
        # 現在の最大債権者と最大債務者を取得
        creditor = payment[0]
        debtor = payment[-1]

        amount: float = min(creditor["amount"], abs(debtor["amount"]))

        # 清算金額が0円の場合は終了
        if amount == 0:
            return "精算結果は以下の通りです\n" + "\n".join(
                [
                    f"{item['debtor']}さんが{item['creditor']}さんに{item['amount']}円のお支払い"
                    for item in settlement
                ]
            )

        # 債権者と債務者で清算を行い、再帰呼び出しを行う
        creditor["amount"] -= amount
        debtor["amount"] += amount
        settlement.append(
            {
                "debtor": debtor["name"],
                "creditor": creditor["name"],
                "amount": round(amount),
            }
        )

        return self.settle_calc(payment, settlement)
