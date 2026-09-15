import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

from database import (
    init_db, list_products, add_product, update_product, delete_product,
    list_categories, add_category, delete_category,
    list_orders, get_order, update_order_status, get_stats, get_product,
    list_promos, add_promo, delete_promo,
    list_messages, add_message
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# === FSM ===
class AddProduct(StatesGroup):
    name = State(); description = State(); price = State(); old_price = State()
    stock = State(); photo = State(); more_photos = State(); cat = State()

class EditProduct(StatesGroup):
    pid = State(); name = State(); description = State(); price = State()
    old_price = State(); stock = State(); photo = State(); cat = State()

class AddPromo(StatesGroup):
    code = State(); discount = State(); uses = State()

class Reply(StatesGroup):
    user_id = State(); text = State()

# === Клавиатуры ===
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Товары", callback_data="list_products")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton(text="🏷 Категории", callback_data="list_cats")],
        [InlineKeyboardButton(text="🛒 Заказы", callback_data="orders_menu")],
        [InlineKeyboardButton(text="🎁 Промокоды", callback_data="promos_menu")],
        [InlineKeyboardButton(text="💬 Сообщения", callback_data="chats_menu")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="📤 Экспорт", callback_data="export_menu")],
    ])

def orders_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Новые", callback_data="orders_new")],
        [InlineKeyboardButton(text="⚙️ В работе", callback_data="orders_processing")],
        [InlineKeyboardButton(text="🚚 Отправлены", callback_data="orders_shipped")],
        [InlineKeyboardButton(text="✅ Доставлены", callback_data="orders_delivered")],
        [InlineKeyboardButton(text="📋 Все", callback_data="orders_all")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
    ])

def promos_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список", callback_data="promos_list")],
        [InlineKeyboardButton(text="➕ Добавить", callback_data="promo_add")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
    ])

def export_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Товары (.xlsx)", callback_data="export_products")],
        [InlineKeyboardButton(text="🛒 Заказы (.xlsx)", callback_data="export_orders")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")],
    ])

def product_actions(pid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ред.", callback_data=f"edit_{pid}"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del_{pid}")],
        [InlineKeyboardButton(text="⬅️ К товарам", callback_data="list_products")],
    ])

def order_actions(oid, status="new"):
    rows = []
    statuses = [("processing", "⚙️ В работу"), ("shipped", "🚚 Отправлен"),
                ("delivered", "✅ Доставлен"), ("cancelled", "❌ Отменён")]
    row = []
    for code, label in statuses:
        if code != status:
            row.append(InlineKeyboardButton(text=label, callback_data=f"setstatus_{code}_{oid}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ К заказам", callback_data="orders_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# === Старт ===
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        await msg.answer("Привет! Открой магазин через меню 👇")
        return
    await msg.answer("👋 *Админ-панель VapeShop*", reply_markup=main_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "back_menu")
async def back_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("👋 *Админ-панель*", reply_markup=main_menu(), parse_mode="Markdown")

# === СТАТИСТИКА ===
@dp.callback_query(F.data == "stats")
async def cb_stats(cb: CallbackQuery):
    s = get_stats()
    text = (
        "📊 *Статистика*\n\n"
        f"🛒 Заказов: *{s['total_orders']}*\n"
        f"💰 Выручка: *{s['total_revenue']}₽*\n"
        f"📈 Средний чек: *{s['avg_order']}₽*\n"
        f"👥 Клиентов: *{s['users_count']}*\n\n"
        f"📅 *Сегодня:*\n"
        f"• Заказов: *{s['today_orders']}*\n"
        f"• Выручка: *{s['today_revenue']}₽*\n\n"
        f"🆕 Новых: *{s['new_orders']}*\n"
        f"✅ Доставлено: *{s['done_orders']}*\n"
        f"📦 Товаров: *{s['products_count']}*"
    )
    # График 7 дней
    chart = s.get("chart", [])
    if chart:
        text += "\n\n📈 *График 7 дней:*\n"
        max_c = max((c["count"] for c in chart), default=1)
        for c in chart:
            bars = "█" * int(c["count"] / max_c * 10)
            text += f"`{c['date'][-5:]}` {bars} {c['count']} шт\n"
    # Топ-5
    top = s.get("top_products", [])
    if top:
        text += "\n🏆 *Топ-5 товаров:*\n"
        for i, (name, cnt) in enumerate(top, 1):
            text += f"{i}. {name} — {cnt} шт\n"
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())

# === ТОВАРЫ ===
@dp.callback_query(F.data == "list_products")
async def cb_list_products(cb: CallbackQuery):
    products = list_products()
    if not products:
        await cb.message.edit_text("📦 Товаров нет", reply_markup=main_menu())
        return
    rows = []
    for p in products[:20]:
        stock_info = f" ({p['stock']}шт)" if p.get("stock") else ""
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} — {p['price']}₽{stock_info}",
            callback_data=f"product_{p['id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    await cb.message.edit_text(
        f"📦 *Товары ({len(products)}):*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@dp.callback_query(F.data.startswith("product_"))
async def cb_product(cb: CallbackQuery):
    pid = int(cb.data.replace("product_", ""))
    p = get_product(pid)
    if not p: return await cb.answer("Не найден")
    text = (
        f"📦 *{p['name']}*\n\n"
        f"💰 Цена: *{p['price']}₽*"
        + (f" ~~{p['old_price']}₽~~\n" if p.get("old_price") else "\n")
        + f"📊 Остаток: *{p.get('stock', 0)} шт*\n"
        + f"🏷 Категория: `{p['cat']}`\n"
        + (f"\n📝 {p.get('description', '')}" if p.get("description") else "")
    )
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=product_actions(pid))

# === ДОБАВЛЕНИЕ ТОВАРА ===
@dp.callback_query(F.data == "add_product")
async def cb_add_product(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📝 Введите *название*:", parse_mode="Markdown")
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def add_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await msg.answer("📝 Введите *описание* (или `-`):", parse_mode="Markdown")
    await state.set_state(AddProduct.description)

@dp.message(AddProduct.description)
async def add_desc(msg: Message, state: FSMContext):
    await state.update_data(description="" if msg.text == "-" else msg.text)
    await msg.answer("💰 Введите *цену*:")
    await state.set_state(AddProduct.price)

@dp.message(AddProduct.price)
async def add_price(msg: Message, state: FSMContext):
    try: price = int(msg.text)
    except: return await msg.answer("❌ Число!")
    await state.update_data(price=price)
    await msg.answer("🏷 *Старая цена* (для скидки, или `0`):")
    await state.set_state(AddProduct.old_price)

@dp.message(AddProduct.old_price)
async def add_old(msg: Message, state: FSMContext):
    try: old = int(msg.text)
    except: old = 0
    await state.update_data(old_price=old)
    await msg.answer("📊 *Остаток* на складе (число, или `0`):")
    await state.set_state(AddProduct.stock)

@dp.message(AddProduct.stock)
async def add_stock(msg: Message, state: FSMContext):
    try: stock = int(msg.text)
    except: stock = 0
    await state.update_data(stock=stock, images=[])
    await msg.answer("📸 Отправьте *фото* (или `-`):", parse_mode="Markdown")
    await state.set_state(AddProduct.photo)

@dp.message(AddProduct.photo, F.photo)
async def add_photo(msg: Message, state: FSMContext):
    photo = msg.photo[-1]
    file = await bot.get_file(photo.file_id)
    os.makedirs("uploads", exist_ok=True)
    path = f"uploads/{photo.file_id}.jpg"
    await bot.download_file(file.file_path, path)
    await state.update_data(img=f"/uploads/{photo.file_id}.jpg")
    await ask_more_photos(msg, state)

@dp.message(AddProduct.photo, F.text)
async def add_photo_text(msg: Message, state: FSMContext):
    img = f"https://picsum.photos/seed/{msg.message_id}/300" if msg.text == "-" else msg.text
    await state.update_data(img=img)
    await ask_more_photos(msg, state)

async def ask_more_photos(msg: Message, state: FSMContext):
    await msg.answer("📸 *Ещё фото?* Отправьте или `-` чтобы закончить.", parse_mode="Markdown")
    await state.set_state(AddProduct.more_photos)

@dp.message(AddProduct.more_photos, F.photo)
async def add_more(msg: Message, state: FSMContext):
    photo = msg.photo[-1]
    file = await bot.get_file(photo.file_id)
    path = f"uploads/{photo.file_id}.jpg"
    await bot.download_file(file.file_path, path)
    data = await state.get_data()
    images = data.get("images", [])
    images.append(f"/uploads/{photo.file_id}.jpg")
    await state.update_data(images=images)
    await msg.answer(f"✅ Добавлено ({len(images)}). Ещё? Или `-`.", parse_mode="Markdown")

@dp.message(AddProduct.more_photos, F.text)
async def add_more_done(msg: Message, state: FSMContext):
    cats = list_categories()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=c["name"], callback_data=f"pickcat_{c['id']}")] for c in cats
    ])
    await msg.answer("🏷 Категория:", reply_markup=kb)
    await state.set_state(AddProduct.cat)

@dp.callback_query(AddProduct.cat, F.data.startswith("pickcat_"))
async def add_cat(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.replace("pickcat_", "")
    d = await state.get_data()
    pid = add_product(
        d["name"], d["price"], d["img"], cat,
        description=d.get("description", ""),
        old_price=d.get("old_price", 0),
        stock=d.get("stock", 0),
        images=d.get("images", [])
    )
    await cb.message.edit_text(f"✅ Товар добавлен! ID: `{pid}`", parse_mode="Markdown", reply_markup=main_menu())
    await state.clear()

# === РЕДАКТИРОВАНИЕ (упрощено — редактируем основные поля) ===
@dp.callback_query(F.data.startswith("edit_"))
async def cb_edit(cb: CallbackQuery, state: FSMContext):
    pid = int(cb.data.replace("edit_", ""))
    p = get_product(pid)
    if not p: return await cb.answer("Не найден")
    await state.update_data(pid=pid, orig=p)
    await cb.message.edit_text(
        f"✏️ *{p['name']}*\n\nЧто меняем?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Название", callback_data="ef_name")],
            [InlineKeyboardButton(text="Описание", callback_data="ef_desc")],
            [InlineKeyboardButton(text="Цену", callback_data="ef_price")],
            [InlineKeyboardButton(text="Старую цену", callback_data="ef_old")],
            [InlineKeyboardButton(text="Остаток", callback_data="ef_stock")],
            [InlineKeyboardButton(text="Фото", callback_data="ef_photo")],
            [InlineKeyboardButton(text="Категорию", callback_data="ef_cat")],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="list_products")],
        ])
    )

@dp.callback_query(F.data.startswith("ef_"))
async def cb_edit_field(cb: CallbackQuery, state: FSMContext):
    field = cb.data.replace("ef_", "")
    prompts = {
        "name": "Введите новое название:",
        "desc": "Введите описание:",
        "price": "Введите новую цену:",
        "old": "Введите старую цену (0 = убрать):",
        "stock": "Введите остаток:",
        "photo": "Отправьте новое фото:",
        "cat": "Выберите категорию:"
    }
    if field == "cat":
        cats = list_categories()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=c["name"], callback_data=f"escat_{c['id']}")] for c in cats
        ])
        await cb.message.edit_text("Категория:", reply_markup=kb)
        return
    await cb.message.edit_text(prompts[field])
    await state.update_data(edit_field=field)
    await state.set_state(EditProduct.name)  # используем любое состояние для ввода

@dp.message(EditProduct.name)
async def edit_value(msg: Message, state: FSMContext):
    d = await state.get_data()
    field = d.get("edit_field")
    pid = d["pid"]
    val = msg.text

    if field == "name":
        update_product(pid, name=val)
    elif field == "desc":
        update_product(pid, description=val)
    elif field == "price":
        try: update_product(pid, price=int(val))
        except: return await msg.answer("❌ Число!")
    elif field == "old":
        try: update_product(pid, old_price=int(val))
        except: return await msg.answer("❌ Число!")
    elif field == "stock":
        try: update_product(pid, stock=int(val))
        except: return await msg.answer("❌ Число!")
    elif field == "photo":
        if msg.photo:
            photo = msg.photo[-1]
            file = await bot.get_file(photo.file_id)
            path = f"uploads/{photo.file_id}.jpg"
            await bot.download_file(file.file_path, path)
            update_product(pid, img=f"/uploads/{photo.file_id}.jpg")
        elif msg.text and msg.text != "-":
            update_product(pid, img=msg.text)
    await msg.answer("✅ Обновлено", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data.startswith("escat_"))
async def edit_cat(cb: CallbackQuery, state: FSMContext):
    cat = cb.data.replace("escat_", "")
    d = await state.get_data()
    update_product(d["pid"], cat=cat)
    await cb.message.edit_text("✅ Категория обновлена", reply_markup=main_menu())
    await state.clear()

@dp.callback_query(F.data.startswith("del_"))
async def cb_del(cb: CallbackQuery):
    pid = int(cb.data.replace("del_", ""))
    delete_product(pid)
    await cb.answer("Удалено")
    await cb_list_products(cb)

# === КАТЕГОРИИ ===
@dp.callback_query(F.data == "list_cats")
async def cb_list_cats(cb: CallbackQuery):
    cats = list_categories()
    text = "🏷 *Категории:*\n\n" + "\n".join(f"• `{c['id']}` — {c['name']}" for c in cats)
    text += "\n\n/addcat ID Название\n/delcat ID"
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu())

@dp.message(Command("addcat"))
async def cmd_addcat(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3: return await msg.answer("Формат: `/addcat pods Одноразки`", parse_mode="Markdown")
    add_category(parts[1], parts[2])
    await msg.answer(f"✅ Добавлено")

@dp.message(Command("delcat"))
async def cmd_delcat(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    parts = msg.text.split()
    if len(parts) < 2: return
    delete_category(parts[1])
    await msg.answer("🗑 Удалено")

# === ЗАКАЗЫ ===
@dp.callback_query(F.data == "orders_menu")
async def cb_orders_menu(cb: CallbackQuery):
    await cb.message.edit_text("🛒 *Заказы*", parse_mode="Markdown", reply_markup=orders_menu())

@dp.callback_query(F.data.startswith("orders_"))
async def cb_orders_filter(cb: CallbackQuery):
    f = cb.data.replace("orders_", "")
    orders = list_orders(status=None if f == "all" else f)
    if not orders:
        return await cb.message.edit_text("Нет заказов", reply_markup=orders_menu())
    rows = []
    for o in orders[:15]:
        rows.append([InlineKeyboardButton(
            text=f"#{o['id']} · {o['total']}₽ · {o['status']}",
            callback_data=f"order_{o['id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="orders_menu")])
    await cb.message.edit_text(
        f"🛒 Заказы ({f}): {len(orders)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@dp.callback_query(F.data.startswith("order_") & ~F.data.startswith("orders_"))
async def cb_order(cb: CallbackQuery):
    oid = int(cb.data.replace("order_", ""))
    o = get_order(oid)
    if not o: return await cb.answer("Не найден")
    text = (
        f"🛒 *Заказ #{o['id']}*\n\n"
        f"👤 @{o['username'] or 'гость'}\n"
        f"📞 {o.get('phone') or '—'}\n"
        f"📦 {o.get('delivery', 'pickup')}: {o.get('address') or '—'}\n"
        f"💰 {o['total']}₽"
        + (f" (промо: −{o.get('discount',0)}₽)" if o.get("promo") else "")
        + f"\n📋 {o['items']}"
    )
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=order_actions(oid, o['status']))

@dp.callback_query(F.data.startswith("setstatus_"))
async def cb_setstatus(cb: CallbackQuery):
    parts = cb.data.replace("setstatus_", "").split("_")
    status = parts[0]
    oid = int(parts[1])
    update_order_status(oid, status)
    await cb.answer(f"Статус: {status}")
    o = get_order(oid)
    text = (
        f"🛒 *Заказ #{o['id']}*\n\n"
        f"👤 @{o['username'] or 'гость'}\n"
        f"💰 {o['total']}₽\n📋 {o['items']}"
    )
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=order_actions(oid, o['status']))
    # Уведомить клиента
    if o.get("user_id"):
        try:
            await bot.send_message(o["user_id"], f"🔔 Ваш заказ #{oid}: статус — *{status}*", parse_mode="Markdown")
        except: pass

# === ПРОМОКОДЫ ===
@dp.callback_query(F.data == "promos_menu")
async def cb_promos_menu(cb: CallbackQuery):
    await cb.message.edit_text("🎁 *Промокоды*", parse_mode="Markdown", reply_markup=promos_menu())

@dp.callback_query(F.data == "promos_list")
async def cb_promos_list(cb: CallbackQuery):
    promos = list_promos()
    if not promos:
        return await cb.message.edit_text("Нет промокодов", reply_markup=promos_menu())
    text = "🎁 *Промокоды:*\n\n"
    for p in promos:
        text += f"`{p['code']}` — {p['discount']}% (осталось: {p['uses_left']})\n"
    text += "\n/delpromo CODE — удалить"
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=promos_menu())

@dp.callback_query(F.data == "promo_add")
async def cb_promo_add(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите *код* промокода (например, SALE10):", parse_mode="Markdown")
    await state.set_state(AddPromo.code)

@dp.message(AddPromo.code)
async def promo_code(msg: Message, state: FSMContext):
    await state.update_data(code=msg.text.upper())
    await msg.answer("Скидка в *%* (число):", parse_mode="Markdown")
    await state.set_state(AddPromo.discount)

@dp.message(AddPromo.discount)
async def promo_disc(msg: Message, state: FSMContext):
    try: d = int(msg.text)
    except: return await msg.answer("❌ Число!")
    await state.update_data(discount=d)
    await msg.answer("Сколько *использований*? (число):")
    await state.set_state(AddPromo.uses)

@dp.message(AddPromo.uses)
async def promo_uses(msg: Message, state: FSMContext):
    try: u = int(msg.text)
    except: u = 100
    d = await state.get_data()
    add_promo(d["code"], d["discount"], u)
    await msg.answer(f"✅ Промокод `{d['code']}` создан", parse_mode="Markdown", reply_markup=main_menu())
    await state.clear()

@dp.message(Command("delpromo"))
async def cmd_delpromo(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    parts = msg.text.split()
    if len(parts) < 2: return
    delete_promo(parts[1])
    await msg.answer("🗑 Удалён")

# === СООБЩЕНИЯ ===
@dp.callback_query(F.data == "chats_menu")
async def cb_chats(cb: CallbackQuery):
    msgs = list_messages()
    if not msgs:
        return await cb.message.edit_text("💬 Сообщений нет", reply_markup=main_menu())
    rows = [[InlineKeyboardButton(
        text=f"@{m['username'] or m['user_id']}",
        callback_data=f"chat_{m['user_id']}"
    )] for m in msgs[:20]]
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_menu")])
    await cb.message.edit_text("💬 *Чаты:*", parse_mode="Markdown",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("chat_"))
async def cb_chat(cb: CallbackQuery, state: FSMContext):
    uid = int(cb.data.replace("chat_", ""))
    msgs = list_messages(uid)
    text = f"💬 *Чат с {uid}*\n\n"
    for m in reversed(msgs[:20]):
        prefix = "👤" if not m["from_admin"] else "👨‍💼"
        text += f"{prefix} {m['text']}\n"
    await cb.message.edit_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↩️ Ответить", callback_data=f"reply_{uid}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="chats_menu")],
        ]))

@dp.callback_query(F.data.startswith("reply_"))
async def cb_reply(cb: CallbackQuery, state: FSMContext):
    uid = int(cb.data.replace("reply_", ""))
    await state.update_data(reply_to=uid)
    await cb.message.edit_text(f"Введите ответ для {uid}:")
    await state.set_state(Reply.text)

@dp.message(Reply.text)
async def send_reply(msg: Message, state: FSMContext):
    d = await state.get_data()
    uid = d["reply_to"]
    add_message(uid, f"admin", msg.text, from_admin=1)
    try:
        await bot.send_message(uid, f"💬 *Ответ магазина:*\n\n{msg.text}", parse_mode="Markdown")
        await msg.answer("✅ Отправлено")
    except:
        await msg.answer("❌ Не удалось отправить")
    await state.clear()

@dp.message(Command("reply"))
async def cmd_reply(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3: return await msg.answer("Формат: `/reply USER_ID текст`", parse_mode="Markdown")
    try:
        uid = int(parts[1])
        add_message(uid, "admin", parts[2], from_admin=1)
        await bot.send_message(uid, f"💬 *Ответ:*\n\n{parts[2]}", parse_mode="Markdown")
        await msg.answer("✅ Отправлено")
    except Exception as e:
        await msg.answer(f"❌ {e}")

# === ЭКСПОРТ ===
@dp.callback_query(F.data == "export_menu")
async def cb_export(cb: CallbackQuery):
    await cb.message.edit_text("📤 *Экспорт данных*", parse_mode="Markdown", reply_markup=export_menu())

@dp.callback_query(F.data == "export_products")
async def cb_export_products(cb: CallbackQuery):
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Название", "Описание", "Цена", "Старая", "Остаток", "Категория"])
    for p in list_products():
        ws.append([p["id"], p["name"], p.get("description", ""), p["price"],
                   p.get("old_price", 0), p.get("stock", 0), p["cat"]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    await cb.message.answer_document(
        BufferedInputFile(buf.read(), filename="products.xlsx"),
        caption="📦 Товары"
    )

@dp.callback_query(F.data == "export_orders")
async def cb_export_orders(cb: CallbackQuery):
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Клиент", "Состав", "Сумма", "Промо", "Доставка", "Адрес", "Телефон", "Статус", "Дата"])
    for o in list_orders(limit=1000):
        ws.append([o["id"], o["username"], o["items"], o["total"],
                   o.get("promo", ""), o.get("delivery", ""),
                   o.get("address", ""), o.get("phone", ""),
                   o["status"], o["created_at"]])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    await cb.message.answer_document(
        BufferedInputFile(buf.read(), filename="orders.xlsx"),
        caption="🛒 Заказы"
    )

# === Запуск ===
async def main():
    init_db()
    os.makedirs("uploads", exist_ok=True)
    print("🤖 Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
