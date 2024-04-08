from firebase_functions.params import SecretParam

# openai
OPENAI_API_KEY: str = SecretParam("OPENAI_API_KEY").value
OPENAI_ORGANIZATION: str = SecretParam("OPENAI_ORGANIZATION").value
ASSISTANT_ID: str = SecretParam("ASSISTANT_ID").value

# line
CHANNEL_SECRET: str = SecretParam("CHANNEL_SECRET").value
CHANNEL_ACCESS_TOKEN: str = SecretParam("CHANNEL_ACCESS_TOKEN").value