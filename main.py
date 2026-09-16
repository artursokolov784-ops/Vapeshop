from fastapi import FastAPI, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import os
import uuid
import io
import aiofiles
import requests as req

from database import (
    init_db, list_categories, list_products, get_product,
    add_order, list_orders, update_order_status, get_stats,
    get_favorites, toggle_favorite, get_cart, save_cart, clear_cart,
    get_promo, use_promo, list_promos, add_promo, delete_promo,
    save_search, get_search_history, add_message, list_messages,
    get_order, decrement_stock
)

app = FastAPI(title="VapeShop API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# === Модели ===
class OrderItem(BaseModel):
    id: int
    name: str
    price: int
    qty: int = 1

class OrderIn(BaseModel):
    items: List[OrderItem]
    total: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    promo: Optional[str] = ""
    discount: Optional[int] = 0
    delivery: Optional[str] = "pickup"
    address: Optional[str] = ""
    phone: Optional[str] = ""
    comment: Optional[str] = ""

class CartIn(BaseModel):
    user_id: int
    items: list

class FavIn(BaseModel):
    user_id: int
    product_id: int

class SearchIn(BaseModel):
    user_id: int
    query: str

class MessageIn(BaseModel):
    user_id: int
    username: str
    text: str

# === API ===
@app.on_event("startup")
def startup():
    init_db()

@app.get("/api/categories")
def api_categories():
    return list_categories()

@app.get("/api/products")
def api_products(cat: str = None, search: str = None, sort: str = None):
    return list_products(cat, search, sort)

@app.get("/api/products/{pid}")
def api_product(pid: int):
    p = get_product(pid)
    if not p: raise HTTPException(404, "Не найден")
    return p

# === Заказы ===
@app.post("/api/orders")
def api_create_order(order: OrderIn):
    items_str = "; ".join(f"{i.name} x{i.qty} ({i.price}₽)" for i in order.items)
    oid = add_order(
        order.user_id, order.username, items_str, order.total,
        discount=order.discount, promo=order.promo,
        delivery=order.delivery, address=order.address,
        phone=order.phone, comment=order.comment
    )
    # Уменьшаем остатки
    decrement_stock([{"id": i.id, "qty": i.qty} for i in order.items])
    # Списываем промокод
    if order.promo:
        use_promo(order.promo)
    # Очищаем корзину
    if order.user_id:
        clear_cart(order.user_id)
    # Уведомление админу
    notify_admin(oid, order)
    # Уведомление клиенту
    if order.user_id:
        notify_client(order.user_id, oid, order.total)
    return {"ok": True, "order_id": oid}

def notify_admin(order_id, order):
    if not BOT_TOKEN or not ADMIN_ID: return
    try:
        text = (
            f"🔔 *Новый заказ #{order_id}*\n\n"
            f"👤 @{order.username or 'гость'}\n"
            f"📞 {order.phone or '—'}\n"
            f"📦 {order.delivery}: {order.address or 'самовывоз'}\n"
            f"💰 Сумма: *{order.total}₽*"
            + (f"\n🎁 Промокод: `{order.promo}` (−{order.discount}₽)" if order.promo else "")
            + f"\n\n📋 Состав:\n"
            + "\n".join(f"• {i.name} x{i.qty} — {i.price}₽" for i in order.items)
        )
        req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ADMIN_ID,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": {"inline_keyboard": [
                    [{"text": "⚙️ В работу", "callback_data": f"setstatus_processing_{order_id}"},
                     {"text": "🚚 Отправлен", "callback_data": f"setstatus_shipped_{order_id}"}],
                    [{"text": "✅ Доставлен", "callback_data": f"setstatus_delivered_{order_id}"},
                     {"text": "💬 Чат", "callback_data": f"chat_{order.user_id}"}],
                ]}
            }, timeout=5
        )
    except Exception as e:
        print(f"notify_admin error: {e}")

def notify_client(user_id, order_id, total):
    if not BOT_TOKEN: return
    try:
        req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": user_id,
                "text": f"✅ *Заказ #{order_id} принят!*\n\nСумма: *{total}₽*\nМы свяжемся с вами скоро.",
                "parse_mode": "Markdown"
            }, timeout=5
        )
    except Exception as e:
        print(f"notify_client error: {e}")

@app.get("/api/orders")
def api_orders(status: str = None, user_id: int = None):
    return list_orders(status=status, user_id=user_id)

@app.get("/api/orders/user/{user_id}")
def api_user_orders(user_id: int):
    return list_orders(user_id=user_id)

# === Избранное ===
@app.get("/api/favorites/{user_id}")
def api_get_favs(user_id: int):
    return get_favorites(user_id)

@app.post("/api/favorites/toggle")
def api_toggle_fav(data: FavIn):
    result = toggle_favorite(data.user_id, data.product_id)
    return {"ok": True, "added": result}

# === Корзина ===
@app.get("/api/cart/{user_id}")
def api_get_cart(user_id: int):
    return get_cart(user_id)

@app.post("/api/cart")
def api_save_cart(data: CartIn):
    save_cart(data.user_id, data.items)
    return {"ok": True}

@app.delete("/api/cart/{user_id}")
def api_clear_cart(user_id: int):
    clear_cart(user_id)
    return {"ok": True}

# === Промокоды ===
@app.get("/api/promo/{code}")
def api_check_promo(code: str):
    p = get_promo(code)
    if not p: raise HTTPException(404, "Промокод не найден")
    return p

# === История поиска ===
@app.post("/api/search/history")
def api_save_search(data: SearchIn):
    save_search(data.user_id, data.query)
    return {"ok": True}

@app.get("/api/search/history/{user_id}")
def api_get_search(user_id: int):
    return get_search_history(user_id)

# === Чат ===
@app.post("/api/messages")
def api_add_message(data: MessageIn):
    mid = add_message(data.user_id, data.username, data.text)
    # Уведомить админа
    if BOT_TOKEN and ADMIN_ID:
        try:
            req.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": f"💬 *Сообщение от @{data.username}*\n\n{data.text}",
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": [[
                        {"text": "↩️ Ответить", "callback_data": f"reply_{data.user_id}"}
                    ]]}
                }, timeout=5
            )
        except: pass
    return {"ok": True, "id": mid}

@app.get("/api/messages/{user_id}")
def api_get_messages(user_id: int):
    return list_messages(user_id)

# === Статистика ===
@app.get("/api/stats")
def api_stats():
    return get_stats()

# === Excel-экспорт ===
@app.get("/api/export/products.xlsx")
def api_export_products():
    try:
        from openpyxl import Workbook
    except ImportError:
        raise HTTPException(500, "openpyxl не установлен")
    wb = Workbook()
    ws = wb.active
    ws.title = "Товары"
    ws.append(["ID", "Название", "Описание", "Цена", "Старая цена", "Остаток", "Категория"])
    for p in list_products():
        ws.append([p["id"], p["name"], p.get("description", ""),
                   p["price"], p.get("old_price", 0), p.get("stock", 0), p["cat"]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=products.xlsx"}
    )

@app.get("/api/export/orders.xlsx")
def api_export_orders():
    try:
        from openpyxl import Workbook
    except ImportError:
        raise HTTPException(500, "openpyxl не установлен")
    wb = Workbook()
    ws = wb.active
    ws.title = "Заказы"
    ws.append(["ID", "Клиент", "Состав", "Сумма", "Промо", "Доставка", "Адрес", "Телефон", "Статус", "Дата"])
    for o in list_orders(limit=1000):
        ws.append([o["id"], o["username"], o["items"], o["total"],
                   o.get("promo", ""), o.get("delivery", ""), o.get("address", ""),
                   o.get("phone", ""), o["status"], o["created_at"]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=orders.xlsx"}
    )

# === Загрузка фото ===
@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "Только изображения")
    ext = file.filename.split(".")[-1].lower()
    if ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
        raise HTTPException(400, "Недопустимый формат")
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    async with aiofiles.open(path, "wb") as f:
        await f.write(await file.read())
    return {"url": f"/uploads/{filename}"}

# === Статика ===
import asyncio
from bot import dp, bot

@app.on_event("startup")
async def start_bot():
    asyncio.create_task(dp.start_polling(bot))
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
