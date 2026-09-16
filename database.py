  import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

# Читаем URL базы данных из переменной окружения
DATABASE_URL = os.getenv("DATABASE_URL")

@contextmanager
def get_db():
    # Render требует SSL для подключения к PostgreSQL
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            # Создаём таблицы. SQL почти такой же, но с типом SERIAL для ID.
            cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(255) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT DEFAULT '',
                price INTEGER NOT NULL,
                old_price INTEGER DEFAULT 0,
                stock INTEGER DEFAULT 0,
                img VARCHAR(500),
                images TEXT DEFAULT '[]',
                cat VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username VARCHAR(255),
                items TEXT,
                total INTEGER,
                discount INTEGER DEFAULT 0,
                promo VARCHAR(50),
                delivery VARCHAR(50) DEFAULT 'pickup',
                address TEXT DEFAULT '',
                phone VARCHAR(50) DEFAULT '',
                status VARCHAR(50) DEFAULT 'new',
                comment TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS favorites (
                user_id BIGINT,
                product_id INTEGER,
                PRIMARY KEY (user_id, product_id)
            );

            CREATE TABLE IF NOT EXISTS carts (
                user_id BIGINT PRIMARY KEY,
                items TEXT DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS promos (
                code VARCHAR(50) PRIMARY KEY,
                discount INTEGER NOT NULL,
                uses_left INTEGER DEFAULT 100,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS search_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                query TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                username VARCHAR(255),
                text TEXT,
                from_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Проверяем, пустая ли таблица категорий
            cur.execute("SELECT COUNT(*) FROM categories")
            if cur.fetchone()[0] == 0:
                cur.executemany(
                    "INSERT INTO categories (id, name) VALUES (%s, %s)",
                    [("pods", "Одноразки"), ("liq", "Жидкости"),
                     ("dev", "Устройства"), ("acc", "Аксессуары")]
                )

# === Категории ===
def list_categories():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM categories")
            return [dict(r) for r in cur.fetchall()]

def add_category(cat_id, name):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO categories (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name", (cat_id, name))

def delete_category(cat_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM categories WHERE id=%s", (cat_id,))
            cur.execute("DELETE FROM products WHERE cat=%s", (cat_id,))

# === Товары ===
def list_products(cat=None, search=None, sort=None):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT * FROM products WHERE 1=1"
            params = []
            if cat and cat != "all":
                query += " AND cat=%s"
                params.append(cat)
            if search:
                query += " AND (name ILIKE %s OR description ILIKE %s)"
                params.extend([f"%{search}%", f"%{search}%"])
            if sort == "price_asc":
                query += " ORDER BY price ASC"
            elif sort == "price_desc":
                query += " ORDER BY price DESC"
            else:
                query += " ORDER BY id DESC"
            cur.execute(query, params)
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                try:
                    r["images"] = json.loads(r.get("images") or "[]")
                except:
                    r["images"] = []
            return rows

def get_product(pid):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM products WHERE id=%s", (pid,))
            row = cur.fetchone()
            if not row:
                return None
            p = dict(row)
            try:
                p["images"] = json.loads(p.get("images") or "[]")
            except:
                p["images"] = []
            return p

def add_product(name, price, img, cat, description="", old_price=0, stock=0, images=None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO products (name, price, img, cat, description, old_price, stock, images)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (name, price, img, cat, description, old_price, stock, json.dumps(images or []))
            )
            return cur.fetchone()[0]

def update_product(pid, **fields):
    with get_db() as conn:
        with conn.cursor() as cur:
            allowed = ["name", "price", "img", "cat", "description", "old_price", "stock", "images"]
            sets, params = [], []
            for k, v in fields.items():
                if k in allowed:
                    if k == "images":
                        v = json.dumps(v)
                    sets.append(f"{k}=%s")
                    params.append(v)
            if sets:
                params.append(pid)
                cur.execute(f"UPDATE products SET {', '.join(sets)} WHERE id=%s", params)

def delete_product(pid):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM products WHERE id=%s", (pid,))

def decrement_stock(items):
    with get_db() as conn:
        with conn.cursor() as cur:
            for i in items:
                cur.execute(
                    "UPDATE products SET stock = GREATEST(0, stock - %s) WHERE id=%s",
                    (i.get("qty", 1), i["id"])
                )

# === Заказы ===
def add_order(user_id, username, items, total, **extra):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO orders 
                   (user_id, username, items, total, discount, promo, delivery, address, phone, comment)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (user_id, username, items, total,
                 extra.get("discount", 0), extra.get("promo", ""),
                 extra.get("delivery", "pickup"), extra.get("address", ""),
                 extra.get("phone", ""), extra.get("comment", ""))
            )
            return cur.fetchone()[0]

def list_orders(limit=50, status=None, user_id=None):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = "SELECT * FROM orders WHERE 1=1"
            params = []
            if status and status != "all":
                query += " AND status=%s"
                params.append(status)
            if user_id:
                query += " AND user_id=%s"
                params.append(user_id)
            query += " ORDER BY id DESC LIMIT %s"
            params.append(limit)
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

def get_order(order_id):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
            row = cur.fetchone()
            return dict(row) if row else None

def update_order_status(order_id, status):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET status=%s WHERE id=%s", (status, order_id))

# === Избранное ===
def get_favorites(user_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT product_id FROM favorites WHERE user_id=%s", (user_id,))
            return [r[0] for r in cur.fetchall()]

def toggle_favorite(user_id, product_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM favorites WHERE user_id=%s AND product_id=%s", (user_id, product_id))
            if cur.fetchone():
                cur.execute("DELETE FROM favorites WHERE user_id=%s AND product_id=%s", (user_id, product_id))
                return False
            cur.execute("INSERT INTO favorites (user_id, product_id) VALUES (%s, %s)", (user_id, product_id))
            return True

# === Корзина ===
def get_cart(user_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT items FROM carts WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            if not row:
                return []
            try:
                return json.loads(row[0] or "[]")
            except:
                return []

def save_cart(user_id, items):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO carts (user_id, items, updated_at) VALUES (%s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (user_id) DO UPDATE SET items = EXCLUDED.items, updated_at = CURRENT_TIMESTAMP""",
                (user_id, json.dumps(items))
            )

def clear_cart(user_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM carts WHERE user_id=%s", (user_id,))

# === Промокоды ===
def list_promos():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM promos")
            return [dict(r) for r in cur.fetchall()]

def get_promo(code):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM promos WHERE code=%s AND active=1 AND uses_left>0", (code.upper(),))
            row = cur.fetchone()
            return dict(row) if row else None

def add_promo(code, discount, uses=100):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO promos (code, discount, uses_left, active) VALUES (%s, %s, %s, 1) ON CONFLICT (code) DO UPDATE SET discount=EXCLUDED.discount, uses_left=EXCLUDED.uses_left",
                (code.upper(), discount, uses)
            )

def delete_promo(code):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM promos WHERE code=%s", (code.upper(),))

def use_promo(code):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code=%s", (code.upper(),))

# === История поиска ===
def save_search(user_id, query):
    if not query.strip():
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO search_history (user_id, query) VALUES (%s, %s)", (user_id, query.strip()))

def get_search_history(user_id, limit=10):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT query FROM search_history 
                   WHERE user_id=%s ORDER BY query LIMIT %s""",
                (user_id, limit)
            )
            return [r[0] for r in cur.fetchall()]

# === Сообщения (чат) ===
def add_message(user_id, username, text, from_admin=0):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO messages (user_id, username, text, from_admin) VALUES (%s, %s, %s, %s) RETURNING id", (user_id, username, text, from_admin))
            return cur.fetchone()[0]

def list_messages(user_id=None, limit=50):
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if user_id:
                cur.execute("SELECT * FROM messages WHERE user_id=%s ORDER BY id DESC LIMIT %s", (user_id, limit))
            else:
                cur.execute("SELECT DISTINCT ON (user_id) user_id, username FROM messages ORDER BY user_id, id DESC LIMIT %s", (limit,))
            return [dict(r) for r in cur.fetchall()]

# === Статистика ===
def get_stats():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orders")
            total_orders = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(total),0) FROM orders")
            total_revenue = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM orders WHERE DATE(created_at)=CURRENT_DATE")
            today_orders = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE DATE(created_at)=CURRENT_DATE")
            today_revenue = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM orders WHERE status='new'")
            new_orders = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM orders WHERE status='delivered'")
            done_orders = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM products")
            products_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT user_id) FROM orders")
            users_count = cur.fetchone()[0]
            cur.execute("SELECT COALESCE(AVG(total),0) FROM orders")
            avg_order = int(cur.fetchone()[0])

            cur.execute("""SELECT DATE(created_at) as d, COUNT(*) as cnt, COALESCE(SUM(total),0) as sum
                           FROM orders WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
                           GROUP BY DATE(created_at) ORDER BY d""")
            chart_data = [{"date": str(r[0]), "count": r[1], "sum": r[2]} for r in cur.fetchall()]

            cur.execute("SELECT items FROM orders ORDER BY id DESC LIMIT 100")
            counter = {}
            for row in cur.fetchall():
                for part in (row[0] or "").split("; "):
                    if not part:
                        continue
                    name = part.split(" x")[0].strip()
                    counter[name] = counter.get(name, 0) + 1
            top_products = sorted(counter.items(), key=lambda x: -x[1])[:5]

            return {
                "total_orders": total_orders, "total_revenue": total_revenue,
                "today_orders": today_orders, "today_revenue": today_revenue,
                "new_orders": new_orders, "done_orders": done_orders,
                "products_count": products_count, "users_count": users_count,
                "avg_order": avg_order, "chart": chart_data, "top_products": top_products,
            }                      
