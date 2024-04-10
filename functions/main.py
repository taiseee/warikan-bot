from firebase_functions import https_fn, options
from firebase_admin import initialize_app
from src.warikanbot import WebhookHandler
from src.assistant_factory import AssistantFactory

initialize_app()
options.set_global_options(region=options.SupportedRegion.ASIA_NORTHEAST1)


@https_fn.on_request(
    secrets=[
        "CHANNEL_ACCESS_TOKEN",
        "CHANNEL_SECRET",
        "OPENAI_API_KEY",
        "OPENAI_ORGANIZATION",
        "ASSISTANT_ID"
    ],
    timeout_sec=120
)
def webhook(req: https_fn.Request) -> https_fn.Response:
    body = req.get_data(as_text=True)
    signature = req.headers["X-Line-Signature"]
    handler = WebhookHandler()
    return handler.handle(body, signature)

@https_fn.on_request(
    secrets=[
        "OPENAI_API_KEY",
        "OPENAI_ORGANIZATION"
    ]
)
def create_assistant(req: https_fn.Request) -> https_fn.Response:
    assistant = AssistantFactory().create()
    print(assistant.id)
    return https_fn.Response({"message": "sucessfly created assistant id: " + assistant.id}, status=200)
