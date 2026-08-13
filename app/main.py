import os
from contextlib import asynccontextmanager

import redis.asyncio as redis
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

# Cargar variables de entorno desde .env ANTES de importar submodulos
load_dotenv()

from app.api.whatsapp import send_whatsapp_message  # noqa: E402
from app.scheduler import start_scheduler  # noqa: E402
from app.services.dispatcher import process_incoming_message  # noqa: E402

# Cliente Redis global
redis_client = None
REDIS_CONNECT_TIMEOUT_SECONDS = 3


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Inicializar el pool de conexiones de Redis
    redis_client = redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
    )

    # Prueba basica para verificar que la conexion funciona al arrancar
    try:
        await redis_client.ping()
        print("Conexion a Redis exitosa.")
    except Exception as e:
        # Redis no es necesario para servir el health check ni el webhook actual.
        # No bloquear el arranque si el servicio aun no esta disponible.
        print(f"Fallo al conectar con Redis tras {REDIS_CONNECT_TIMEOUT_SECONDS}s: {e}")

    start_scheduler()
    yield
    # Logica de apagado
    if redis_client:
        await redis_client.close()


app = FastAPI(title="Luka WhatsApp FinBot", lifespan=lifespan)

# En produccion, cargar esto de forma segura desde el entorno
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "fallback_token")


@app.get("/")
def read_root():
    return {"message": "Luka API is running"}


@app.get("/redis-test")
async def test_redis():
    """
    Endpoint de prueba basico para verificar la conectividad con Redis desde Render.
    """
    if not redis_client:
        raise HTTPException(status_code=500, detail="Redis client not initialized")
    try:
        await redis_client.set("test_key", "works", ex=60)
        value = await redis_client.get("test_key")
        return {"status": "ok", "redis_value": value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Redis connection error: {str(e)}")


@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Requerido para la verificacion del webhook de Meta WhatsApp.
    """
    query_params = request.query_params
    hub_mode = query_params.get("hub.mode") or query_params.get("hub_mode")
    hub_challenge = query_params.get("hub.challenge") or query_params.get("hub_challenge")
    hub_verify_token = query_params.get("hub.verify_token") or query_params.get("hub_verify_token")

    print(
        "[WEBHOOK VERIFY] ",
        f"path={request.url.path}",
        f"mode={hub_mode}",
        f"challenge={hub_challenge}",
        f"token={hub_verify_token}",
        f"expected={VERIFY_TOKEN}",
    )

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN and hub_challenge is not None:
        return PlainTextResponse(content=str(hub_challenge), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def handle_webhook(request: Request):
    """
    Maneja los mensajes entrantes de la API de Meta WhatsApp.
    """
    data = await request.json()
    print("Evento de webhook recibido")

    if data.get("object") == "whatsapp_business_account":
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                statuses = value.get("statuses", [])

                for status_event in statuses:
                    print(
                        "WhatsApp status update",
                        f"message_id={status_event.get('id')}",
                        f"status={status_event.get('status')}",
                    )

                for message in messages:
                    sender_phone = message.get("from")
                    message_type = message.get("type")

                    if message_type != "text":
                        continue

                    whatsapp_message_id = message.get("id")
                    text_body = message.get("text", {}).get("body", "")

                    result = await process_incoming_message(
                        sender_phone=sender_phone,
                        text_body=text_body,
                        whatsapp_message_id=whatsapp_message_id,
                    )

                    if result.reply_text:
                        await send_whatsapp_message(sender_phone, result.reply_text)

    return {"status": "ok"}
