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
