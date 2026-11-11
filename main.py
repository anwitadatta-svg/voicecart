import json
import os
import re
import openai
import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from openai import OpenAI
from pydantic import BaseModel
from requests.auth import HTTPBasicAuth

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------
# 1. Configuration (put real values in your .env file)
# ------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
MODEL = os.getenv("MODEL", "gpt-4o-mini")
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET", "")
PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"
APP_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
app = FastAPI()

# ------------------------------------------------------------------
# 2. Catalog (loaded from catalog.json, with a built-in fallback)
# ------------------------------------------------------------------
DEFAULT_CATALOG = [
    {"id": 1, "name": "Black T-Shirt", "price": 18.0, "category": "clothing"},
    {"id": 2, "name": "White T-Shirt", "price": 16.0, "category": "clothing"},
    {"id": 3, "name": "Blue Jeans", "price": 39.0, "category": "clothing"},
    {"id": 4, "name": "White Sneakers", "price": 45.0, "category": "shoes"},
    {"id": 5, "name": "Running Shoes", "price": 60.0, "category": "shoes"},
    {"id": 6, "name": "Wireless Earbuds", "price": 29.0, "category": "electronics"},
    {"id": 7, "name": "Phone Charger", "price": 12.0, "category": "electronics"},
    {"id": 8, "name": "Water Bottle", "price": 10.0, "category": "home"},
    {"id": 9, "name": "Backpack", "price": 35.0, "category": "bags"},
]


def load_catalog():
    path = os.path.join(BASE_DIR, "catalog.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):  # allow {"products": [...]}
            data = data.get("products", [])
        if data:
            return data
    except Exception as e:
        print(f"[catalog] using built-in catalog ({e})")
    return DEFAULT_CATALOG


CATALOG = load_catalog()
CART = {}  # product_id -> quantity (single demo session)
HISTORY = []  # last few plain text turns


def find_product(product_id):
    for p in CATALOG:
        if str(p["id"]) == str(product_id):
            return p
    return None


def cart_summary():
    items = []
    total = 0.0
    for pid, qty in CART.items():
        p = find_product(pid)
        if p:
            line = p["price"] * qty
            total += line
            items.append({"id": p["id"], "name": p["name"], "qty": qty, "line_total": round(line, 2)})
    return {"items": items, "total": round(total, 2)}


# ------------------------------------------------------------------
# 3. Tools the AI agent can call
# ------------------------------------------------------------------
def search_products(query):
    q = str(query).lower().strip()
    words = [w for w in q.replace("-", " ").split() if w]
    results = []
    for p in CATALOG:
        text = f"{p['name']} {p.get('category', '')}".lower().replace("-", " ")
        if q in text or any(w in text for w in words):
            results.append(p)
    return {"results": results[:6]}


def add_to_cart(product_id, qty=1):
    p = find_product(product_id)
    if not p:
        return {"error": f"No product with id {product_id}"}
    qty = int(qty)
    if qty < 1:
        return {"error": "Quantity must be 1 or more"}
    CART[p["id"]] = CART.get(p["id"], 0) + qty
    return {"added": p["name"], "qty": qty, "cart": cart_summary()}


def remove_from_cart(product_id):
    p = find_product(product_id)
    if not p or p["id"] not in CART:
        return {"error": "That item is not in the cart"}
    del CART[p["id"]]
    return {"removed": p["name"], "cart": cart_summary()}


def view_cart():
    return cart_summary()


def get_paypal_token():
    r = requests.post(
        f"{PAYPAL_BASE_URL}/v1/oauth2/token",
        auth=HTTPBasicAuth(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def checkout():
    summary = cart_summary()
    if not summary["items"]:
        return {"error": "The cart is empty"}
    try:
        token = get_paypal_token()
        body = {
            "intent": "CAPTURE",
            "purchase_units": [
                {"amount": {"currency_code": "USD", "value": f"{summary['total']:.2f}"}}
            ],
            "application_context": {
                "return_url": f"{APP_URL}/paid",
                "cancel_url": f"{APP_URL}/",
                "user_action": "PAY_NOW",
            },
        }
        r = requests.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
        r.raise_for_status()
        order = r.json()
        link = next((l["href"] for l in order.get("links", []) if l["rel"] in ("approve", "payer-action")), None)
        if not link:
            return {"error": "PayPal did not return an approval link"}
        return {"status": "ready", "total": summary["total"], "approval_url": link}
    except Exception as e:
        print(f"[PayPal error] {e}")
        return {"error": "Could not create the PayPal order. Check the sandbox keys in .env"}


FUNCS = {
    "search_products": search_products,
    "add_to_cart": add_to_cart,
    "remove_from_cart": remove_from_cart,
    "view_cart": view_cart,
    "checkout": checkout,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the catalog by product name or category.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add a product to the cart using its numeric id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "integer"},
                    "qty": {"type": "integer", "description": "Quantity, default 1"},
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove a product from the cart using its numeric id.",
            "parameters": {
                "type": "object",
                "properties": {"product_id": {"type": "integer"}},
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_cart",
            "description": "Show what is currently in the cart and the total.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkout",
            "description": "Create the PayPal payment for the cart. Only call after the user confirms they want to pay.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

SYSTEM = """You are VoiceCart, a friendly voice shopping assistant. Keep replies short (one or two sentences) because they are read aloud.
You may ONLY call these tools: search_products, add_to_cart, remove_from_cart, view_cart, checkout. Never invent other tool names.
Use search_products to find the product id before add_to_cart or remove_from_cart.
Prices are in USD. Speech recognition can mishear words, so match the closest catalog item.
When the user wants to pay, confirm the total first, then call the checkout tool as soon as they say yes.
Never say you are starting a payment unless you actually called the checkout tool in that same turn."""
def clean_agent_reply(reply):
    import re

    reply = re.sub(
        r"<think>.*?</think>",
        "",
        reply,
        flags=re.IGNORECASE | re.DOTALL
    )

    reply = re.sub(r"</?think>", "", reply, flags=re.IGNORECASE)

    sentences = re.split(r'(?<=[.!?])\s+', reply.strip())

    cleaned = []
    for sentence in sentences:
        sentence = sentence.strip()
        if sentence and sentence.lower() not in [
            s.lower() for s in cleaned
        ]:
            cleaned.append(sentence)

    return " ".join(cleaned).strip()


# ------------------------------------------------------------------
# 4. Chat orchestration
# ------------------------------------------------------------------
class ChatIn(BaseModel):
    text: str


def run_agent(user_text):
    messages = (
        [{"role": "system", "content": SYSTEM}]
        + HISTORY[-10:]
        + [{"role": "user", "content": user_text}]
    )

    checkout_url = None

    for _ in range(6):
        resp = None

        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOLS,
                    temperature=0,
                )
                break
            except openai.BadRequestError as e:
                print(f"[LLM bad request, attempt {attempt + 1}] {e}")

        if resp is None:
            return "Sorry, I couldn't process that. Please try again.", None

        msg = resp.choices[0].message

        # If the AI has finished using tools, return its reply.
        if not msg.tool_calls:
            reply = clean_agent_reply(msg.content or "Done.")

            if checkout_url:
                reply = (
                    "Your PayPal checkout link is ready. "
                    "Please approve the payment on PayPal "
                    "to complete your order."
                )

            return reply, checkout_url

        # Save the assistant tool-call message.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ],
        })

        # Execute the requested tools.
        for tc in msg.tool_calls:
            fn = FUNCS.get(tc.function.name)

            if fn is None:
                result = {"error": f"Unknown tool {tc.function.name}"}
            else:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    result = fn(**args)
                except Exception as e:
                    result = {"error": str(e)}

            if isinstance(result, dict) and result.get("approval_url"):
                checkout_url = result["approval_url"]

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result),
            })

    return "Sorry, that took too many steps. Please try again.", checkout_url
@app.post("/chat")
def chat(body: ChatIn):
    try:
        reply, url = run_agent(body.text)
    except Exception as e:
        print(f"[chat error] {e}")
        reply, url = "Sorry, something went wrong on my side. Please try again.", None
    HISTORY.append({"role": "user", "content": body.text})
    HISTORY.append({"role": "assistant", "content": reply})
    return {"reply": reply, "cart": cart_summary(), "checkout_url": url}
@app.get("/cart")
def get_cart():
    return cart_summary()

@app.post("/checkout")
def checkout_now():
    """Direct button route: creates the PayPal order without needing the AI."""
    return checkout()


@app.post("/reset")
def reset():
    CART.clear()
    HISTORY.clear()
    return {"ok": True}


# ------------------------------------------------------------------
# 5. Pages
# ------------------------------------------------------------------
@app.get("/")
def home():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


@app.get("/paid", response_class=HTMLResponse)
def paid(token: str = ""):
    """PayPal sends the buyer back here after approval. Capture the payment."""
    try:
        access = get_paypal_token()
        r = requests.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders/{token}/capture",
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            timeout=20,
        )
        r.raise_for_status()
        CART.clear()
        status = r.json().get("status", "COMPLETED")
        return f"<h2>Payment {status} \u2705</h2><p>Thank you! <a href='/'>Back to VoiceCart</a></p>"
    except Exception as e:
        print(f"[capture error] {e}")
        return "<h2>Payment could not be completed</h2><p><a href='/'>Back to VoiceCart</a></p>"