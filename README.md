# VoiceCart

A voice-activated shopping agent with PayPal checkout, built for the PayPal AI Hackathon 2026 (agentic commerce).

Speak to the agent to find products, add them to your cart, and pay. VoiceCart turns what you say into actions: it searches the catalog, updates the cart, and creates a PayPal order when you confirm.

## How it works

1. You press **Speak** and say something like "add a black t-shirt to my cart".
2. The browser turns your speech into text (Web Speech API) and sends it to the FastAPI backend.
3. An AI agent (Qwen, through Groq's OpenAI-compatible API) decides which tool to call: `search_products`, `add_to_cart`, `remove_from_cart`, `view_cart` or `checkout`.
4. On checkout, the backend creates a PayPal order (Orders API v2, sandbox) and the page shows a **Pay with PayPal** button.
5. After you approve the payment, PayPal sends you back and the order is captured.

The reply is shown on screen and read aloud.

## Tools used

- Python, FastAPI, Uvicorn
- PayPal Orders API v2 (sandbox)
- Qwen model via Groq (OpenAI-compatible API, `openai` Python SDK)
- Web Speech API (speech recognition and speech synthesis) in Chrome or Edge
- HTML and JavaScript frontend

## Setup

1. Clone the repo and create a virtual environment:
   ```
   git clone https://github.com/anwitadatta-svg/voicecart.git
   cd voicecart
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Create a `.env` file in the project folder:
   ```
   PAYPAL_CLIENT_ID=your-sandbox-client-id
   PAYPAL_SECRET=your-sandbox-secret
   LLM_API_KEY=your-llm-api-key
   LLM_BASE_URL=https://api.groq.com/openai/v1
   MODEL=your-model-name
   BASE_URL=http://localhost:8000
   ```
3. Start the server:
   ```
   uvicorn main:app --reload
   ```
4. Open http://127.0.0.1:8000 in Chrome, press **Speak**, and try "add a black t-shirt to my cart", then "checkout".

Use PayPal **sandbox** credentials and a sandbox buyer account (developer.paypal.com). No real money is used.

## Demo

Demo video: add your YouTube link here.

## License

MIT
