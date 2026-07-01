from google import genai
from google.genai import types

client = genai.Client(
  enterprise=True, project="nxt-create-deb", location="global",
)

model = "gemini-3.5-flash"

# Create a chat session that automatically tracks the conversation history.
chat = client.chats.create(model=model)

print(f"Chatting with '{model}'. Type 'exit' or 'quit' to end.\n")

while True:
  try:
    user_input = input("You: ").strip()
  except (EOFError, KeyboardInterrupt):
    print("\nGoodbye!")
    break

  if not user_input:
    continue
  if user_input.lower() in ("exit", "quit"):
    print("Goodbye!")
    break

  try:
    response = chat.send_message(user_input)
    print(f"\nGemini: {response.text}\n")
  except Exception as e:
    print(f"An error occurred: {e}\n")
