import sqlite3
from contextlib import contextmanager
import os
import json

DB_PATH = os.getenv("DB_PATH", "vapeshop.db")

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            price INTEGER NOT NULL,
            old_price INTEGER DEFAULT 0,
            stock INTEGER DEFAULT 0,
            img TEXT,
            images TEXT DEFAULT '[]',
            cat TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            items TEXT,
            total INTEGER,
            discount INTEGER DEFAULT 0,
            promo TEXT,
            delivery TEXT DEFAULT 'pickup',
            address TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            comment TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            product_id INTEGER,
            PRIMARY KEY (user_id, product_id)
        );

        CREATE TABLE IF NOT EXISTS carts (
            user_id INTEGER PRIMARY KEY,
            items TEXT DEFAULT '[]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS promos (
            code TEXT PRIMARY KEY,
            discount INTEGER NOT NULL,
            uses_left INTEGER DEFAULT 100,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            text TEXT,
            from_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)

        cur = db.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO categories (id, name) VALUES (?, ?)",
                [("pods", "Одноразки"), ("liq", "Жидкости"),
                 ("dev", "Устройства"), ("acc", "Аксессуары")]
            )

# === Категории ===
def list_categories():
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM categories").fetchall()]

def add_category(cat_id, name):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO categories (id, name) VALUES (?, ?)", (cat_id, name))

def delete_category(cat_id):
    with get_db() as db:
        db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        db.execute("DELETE FROM products WHERE cat=?", (cat_id,))

# === Товары ===
def list_products(cat=None, search=None, sort=None):
    with get_db() as db:
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        if cat and cat != "all":
            query += " AND cat=?"
            params.append(cat)
        if search:
            query += " AND (name LIKE ? OR description LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        if sort == "price_asc":
            query += " ORDER BY price ASC"
        elif sort == "price_desc":
            query += " ORDER BY price DESC"
        else:
            query += " ORDER BY id DESC"
        rows = [dict(r) for r in db.execute(query, params).fetchall()]
        # Парсим images JSON
        for r in rows:
            try:
                r["images"] = json.loads(r.get("images") or "[]")
            except:
                r["images"] = []
        return rows

def get_product(pid):
    with get_db() as db:
        row = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not row:
            return None
        p = dict(row)
        try:
            p["images"] = json.loads(p.get("images") or "[]")
        except:
            p["images"] = []
        return p

def add_product(name, price, img, cat, description="", old_price=0, stock=0, images=None):
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO products (name, price, img, cat, description, old_price, stock, images)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, price, img, cat, description, old_price, stock,
             json.dumps(images or []))
        )
        return cur.lastrowid

def update_product(pid, **fields):
    with get_db() as db:
        allowed = ["name", "price", "img", "cat", "description", "old_price", "stock", "images"]
        sets, params = [], []
        for k, v in fields.items():
            if k in allowed:
                if k == "images":
                    v = json.dumps(v)
                sets.append(f"{k}=?")
                params.append(v)
        if sets:
            params.append(pid)
            db.execute(f"UPDATE products SET {', '.join(sets)} WHERE id=?", params)

def delete_product(pid):
    with get_db() as db:
        db.execute("DELETE FROM products WHERE id=?", (pid,))

def decrement_stock(items):
    """Уменьшает остатки после заказа. items = [{id, qty}]"""
    with get_db() as db:
        for i in items:
            db.execute(
                "UPDATE products SET stock = MAX(0, stock - ?) WHERE id=?",
                (i.get("qty", 1), i["id"])
            )

# === Заказы ===
def add_order(user_id, username, items, total, **extra):
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO orders 
               (user_id, username, items, total, discount, promo, delivery, address, phone, comment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, items, total,
             extra.get("discount", 0), extra.get("promo", ""),
             extra.get("delivery", "pickup"), extra.get("address", ""),
             extra.get("phone", ""), extra.get("comment", ""))
        )
        return cur.lastrowid

def list_orders(limit=50, status=None, user_id=None):
    with get_db() as db:
        query = "SELECT * FROM orders WHERE 1=1"
        params = []
        if status and status != "all":
            query += " AND status=?"
            params.append(status)
        if user_id:
            query += " AND user_id=?"
            params.append(user_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in db.execute(query, params).fetchall()]

def get_order(order_id):
    with get_db() as db:
        row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return dict(row) if row else None

def update_order_status(order_id, status):
    with get_db() as db:
        db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))

# === Избранное (сервер) ===
def get_favorites(user_id):
    with get_db() as db:
        rows = db.execute(
            "SELECT product_id FROM favorites WHERE user_id=?", (user_id,)
        ).fetchall()
        return [r[0] for r in rows]

def toggle_favorite(user_id, product_id):
    with get_db() as db:
        exists = db.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND product_id=?",
            (user_id, product_id)
        ).fetchone()
        if exists:
            db.execute(
                "DELETE FROM favorites WHERE user_id=? AND product_id=?",
                (user_id, product_id)
            )
            return False
        db.execute(
            "INSERT INTO favorites (user_id, product_id) VALUES (?, ?)",
            (user_id, product_id)
        )
        return True

# === Корзина (сервер) ===
def get_cart(user_id):
    with get_db() as db:
        row = db.execute("SELECT items FROM carts WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return []
        try:
            return json.loads(row[0] or "[]")
        except:
            return []

def save_cart(user_id, items):
    with get_db() as db:
        db.execute(
            """INSERT OR REPLACE INTO carts (user_id, items, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)""",
            (user_id, json.dumps(items))
        )

def clear_cart(user_id):
    with get_db() as db:
        db.execute("DELETE FROM carts WHERE user_id=?", (user_id,))

# === Промокоды ===
def list_promos():
    with get_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM promos").fetchall()]

def get_promo(code):
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM promos WHERE code=? AND active=1 AND uses_left>0",
            (code.upper(),)
        ).fetchone()
        return dict(row) if row else None

def add_promo(code, discount, uses=100):
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO promos (code, discount, uses_left, active) VALUES (?, ?, ?, 1)",
            (code.upper(), discount, uses)
        )

def delete_promo(code):
    with get_db() as db:
        db.execute("DELETE FROM promos WHERE code=?", (code.upper(),))

def use_promo(code):
    with get_db() as db:
        db.execute(
            "UPDATE promos SET uses_left = uses_left - 1 WHERE code=?",
            (code.upper(),)
        )

# === История поиска ===
def save_search(user_id, query):
    if not query.strip():
        return
    with get_db() as db:
        db.execute(
            "INSERT INTO search_history (user_id, query) VALUES (?, ?)",
            (user_id, query.strip())
        )

def get_search_history(user_id, limit=10):
    with get_db() as db:
        rows = db.execute(
            """SELECT DISTINCT query FROM search_history 
               WHERE user_id=? ORDER BY id DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        return [r[0] for r in rows]

# === Сообщения (чат) ===
def add_message(user_id, username, text, from_admin=0):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO messages (user_id, username, text, from_admin) VALUES (?, ?, ?, ?)",
            (user_id, username, text, from_admin)
        )
        return cur.lastrowid

def list_messages(user_id=None, limit=50):
    with get_db() as db:
        if user_id:
            rows = db.execute(
                """SELECT * FROM messages WHERE user_id=? 
                   ORDER BY id DESC LIMIT ?""",
                (user_id, limit)
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT DISTINCT user_id, username, MAX(id) as last_id 
                   FROM messages GROUP BY user_id ORDER BY last_id DESC LIMIT ?""",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

# === Статистика + Графики ===
def get_stats():
    with get_db() as db:
        total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        total_revenue = db.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
        today_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE DATE(created_at)=DATE('now')"
        ).fetchone()[0]
        today_revenue = db.execute(
            "SELECT COALESCE(SUM(total),0) FROM orders WHERE DATE(created_at)=DATE('now')"
        ).fetchone()[0]
        new_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0]
        done_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status='delivered'").fetchone()[0]
        products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        users_count = db.execute("SELECT COUNT(DISTINCT user_id) FROM orders").fetchone()[0]
        avg_order = total_revenue // max(total_orders, 1)

        # График за 7 дней
        chart = db.execute("""
            SELECT DATE(created_at) as d, COUNT(*) as cnt, COALESCE(SUM(total),0) as sum
            FROM orders
            WHERE created_at >= DATE('now', '-7 days')
            GROUP BY DATE(created_at)
            ORDER BY d
        """).fetchall()
        chart_data = [{"date": r[0], "count": r[1], "sum": r[2]} for r in chart]

        # Топ-5 товаров
        top = db.execute("""
            SELECT items FROM orders ORDER BY id DESC LIMIT 100
        """).fetchall()
        # Парсим и считаем
        counter = {}
        for row in top:
            for part in (row[0] or "").split("; "):
                if not part:
                    continue
                name = part.split(" x")[0].strip()
                counter[name] = counter.get(name, 0) + 1
        top_products = sorted(counter.items(), key=lambda x: -x[1])[:5]

        return {
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "today_orders": today_orders,
            "today_revenue": today_revenue,
            "new_orders": new_orders,
            "done_orders": done_orders,
            "products_count": products_count,
            "users_count": users_count,
            "avg_order": avg_order,
            "chart": chart_data,
            "top_products": top_products,
        }
