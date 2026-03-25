# ============================================================
#   CAPSTONE PROJECT: Personal Expense Tracker
#   Platform : Google Colab
#   Features : CRUD + Search + Analytics + CSV Export
#   Author   : [Yash Patil]
# ============================================================

# ── 1. INSTALL / IMPORT ─────────────────────────────────────
import sqlite3, os, csv, json, textwrap
from datetime import datetime, date
from typing import Optional

try:
    import pandas as pd
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from IPython.display import display, clear_output
    import ipywidgets as widgets
    IN_COLAB = True
except ImportError:
    IN_COLAB = False
    print("Run this in Google Colab for the full interactive experience.")

# ── 2. CONFIG ───────────────────────────────────────────────
DB_PATH      = "/tmp/expenses.db"
EXPORT_PATH  = "/tmp/expenses_export.csv"
CATEGORIES   = ["Food", "Transport", "Health", "Shopping",
                 "Entertainment", "Utilities", "Education", "Other"]
DATE_FMT     = "%Y-%m-%d"

# ── 3. DATABASE LAYER ────────────────────────────────────────
class Database:
    """Thin wrapper around sqlite3 – handles schema creation."""

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init_schema()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self):
        with self.connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    title       TEXT    NOT NULL,
                    amount      REAL    NOT NULL CHECK(amount > 0),
                    category    TEXT    NOT NULL,
                    date        TEXT    NOT NULL,
                    note        TEXT    DEFAULT '',
                    created_at  TEXT    DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

db = Database()

# ── 4. CRUD OPERATIONS ───────────────────────────────────────
class ExpenseManager:
    """All Create / Read / Update / Delete operations."""

    # ── CREATE ───────────────────────────────────────────────
    @staticmethod
    def create(title: str, amount: float, category: str,
               expense_date: str = None, note: str = "") -> int:
        """Insert a new expense. Returns the new row id."""
        expense_date = expense_date or date.today().strftime(DATE_FMT)
        if category not in CATEGORIES:
            raise ValueError(f"Category must be one of: {CATEGORIES}")
        with db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO expenses (title, amount, category, date, note)
                   VALUES (?, ?, ?, ?, ?)""",
                (title.strip(), float(amount), category, expense_date, note.strip())
            )
            conn.commit()
            return cur.lastrowid

    # ── READ (all) ───────────────────────────────────────────
    @staticmethod
    def read_all(order_by: str = "date DESC") -> list[dict]:
        """Return all expenses as a list of dicts."""
        with db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM expenses ORDER BY {order_by}"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── READ (single) ────────────────────────────────────────
    @staticmethod
    def read_one(expense_id: int) -> Optional[dict]:
        """Return a single expense by ID, or None."""
        with db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM expenses WHERE id = ?", (expense_id,)
            ).fetchone()
        return dict(row) if row else None

    # ── UPDATE ───────────────────────────────────────────────
    @staticmethod
    def update(expense_id: int, **kwargs) -> bool:
        """Update any subset of fields. Returns True if a row was changed."""
        allowed = {"title", "amount", "category", "date", "note"}
        changes = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not changes:
            return False
        if "category" in changes and changes["category"] not in CATEGORIES:
            raise ValueError(f"Category must be one of: {CATEGORIES}")
        if "amount" in changes:
            changes["amount"] = float(changes["amount"])
            if changes["amount"] <= 0:
                raise ValueError("Amount must be positive.")
        set_clause = ", ".join(f"{k} = ?" for k in changes)
        values = list(changes.values()) + [expense_id]
        with db.connect() as conn:
            cur = conn.execute(
                f"UPDATE expenses SET {set_clause} WHERE id = ?", values
            )
            conn.commit()
            return cur.rowcount > 0

    # ── DELETE ───────────────────────────────────────────────
    @staticmethod
    def delete(expense_id: int) -> bool:
        """Delete expense by ID. Returns True if deleted."""
        with db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM expenses WHERE id = ?", (expense_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    # ── SEARCH / FILTER ──────────────────────────────────────
    @staticmethod
    def search(keyword: str = "", category: str = "",
               date_from: str = "", date_to: str = "") -> list[dict]:
        """Flexible search: keyword in title/note, optional category + date range."""
        query  = "SELECT * FROM expenses WHERE 1=1"
        params = []
        if keyword:
            query += " AND (title LIKE ? OR note LIKE ?)"
            params += [f"%{keyword}%", f"%{keyword}%"]
        if category and category != "All":
            query += " AND category = ?"
            params.append(category)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        query += " ORDER BY date DESC"
        with db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── ANALYTICS ────────────────────────────────────────────
    @staticmethod
    def summary() -> dict:
        """Return aggregate statistics."""
        with db.connect() as conn:
            total   = conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses").fetchone()[0]
            count   = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
            by_cat  = conn.execute(
                "SELECT category, SUM(amount) as s FROM expenses GROUP BY category ORDER BY s DESC"
            ).fetchall()
            by_month = conn.execute(
                """SELECT strftime('%Y-%m', date) as month, SUM(amount) as s
                   FROM expenses GROUP BY month ORDER BY month"""
            ).fetchall()
        return {
            "total"   : round(total, 2),
            "count"   : count,
            "average" : round(total / count, 2) if count else 0,
            "by_cat"  : [(r["category"], round(r["s"], 2)) for r in by_cat],
            "by_month": [(r["month"], round(r["s"], 2)) for r in by_month],
        }

    # ── EXPORT ───────────────────────────────────────────────
    @staticmethod
    def export_csv(path: str = EXPORT_PATH) -> str:
        """Export all expenses to CSV. Returns the file path."""
        rows = ExpenseManager.read_all()
        if not rows:
            return ""
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return path

    # ── IMPORT JSON ──────────────────────────────────────────
    @staticmethod
    def import_json(path: str) -> int:
        """Bulk-insert from a JSON file. Returns number of rows inserted."""
        with open(path) as f:
            records = json.load(f)
        inserted = 0
        for r in records:
            try:
                ExpenseManager.create(
                    r["title"], r["amount"], r["category"],
                    r.get("date"), r.get("note", "")
                )
                inserted += 1
            except Exception:
                pass
        return inserted

em = ExpenseManager()

# ── 5. SEED DATA (runs once if table is empty) ───────────────
def seed_demo_data():
    """Populate the DB with realistic demo records if it's empty."""
    if ExpenseManager.read_all():
        return  # already has data
    samples = [
        ("Grocery run",        2500, "Food",          "2024-06-01", "Monthly stock"),
        ("Bus pass",            800, "Transport",      "2024-06-02", "Monthly"),
        ("Doctor visit",       1200, "Health",         "2024-06-05", "General checkup"),
        ("New headphones",     3499, "Shopping",       "2024-06-07", "Sony WH-1000XM4"),
        ("Netflix",             649, "Entertainment",  "2024-06-10", ""),
        ("Electricity bill",   1100, "Utilities",      "2024-06-12", "June bill"),
        ("Udemy course",        799, "Education",      "2024-06-15", "Python course"),
        ("Restaurant lunch",    420, "Food",           "2024-06-18", ""),
        ("Gym membership",      700, "Health",         "2024-06-20", ""),
        ("Auto fuel",           550, "Transport",      "2024-06-22", ""),
        ("Grocery run",        2200, "Food",           "2024-07-02", ""),
        ("Movie tickets",       400, "Entertainment",  "2024-07-04", ""),
        ("Water bill",          350, "Utilities",      "2024-07-08", ""),
        ("Book purchase",       299, "Education",      "2024-07-11", "Clean Code"),
        ("Taxi",                180, "Transport",      "2024-07-15", ""),
        ("Pharmacy",            650, "Health",         "2024-07-18", ""),
        ("Street food",         120, "Food",           "2024-07-20", ""),
        ("Amazon order",       1800, "Shopping",       "2024-07-22", "Kitchen items"),
    ]
    for s in samples:
        ExpenseManager.create(*s)
    print("✅ Demo data loaded (18 records).")

seed_demo_data()

# ── 6. CHARTS ────────────────────────────────────────────────
def plot_category_pie():
    stats = ExpenseManager.summary()
    if not stats["by_cat"]:
        print("No data to plot.")
        return
    cats, vals = zip(*stats["by_cat"])
    colors = plt.cm.Pastel1.colors[:len(cats)]
    fig, ax = plt.subplots(figsize=(6, 4))
    wedges, texts, autotexts = ax.pie(
        vals, labels=cats, autopct="%1.1f%%",
        colors=colors, startangle=140,
        wedgeprops={"edgecolor": "white", "linewidth": 1.2}
    )
    for at in autotexts:
        at.set_fontsize(8)
    ax.set_title("Spending by Category", fontsize=13, pad=12)
    plt.tight_layout()
    plt.show()

def plot_monthly_bar():
    stats = ExpenseManager.summary()
    if not stats["by_month"]:
        print("No data to plot.")
        return
    months, totals = zip(*stats["by_month"])
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(months, totals, color="#7F77DD", edgecolor="white", linewidth=0.8)
    ax.bar_label(bars, fmt="₹%.0f", padding=4, fontsize=8)
    ax.set_title("Monthly Spending Trend", fontsize=13)
    ax.set_xlabel("Month")
    ax.set_ylabel("Total (₹)")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"₹{x:,.0f}"))
    ax.set_ylim(0, max(totals) * 1.2)
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.show()

# ── 7. DISPLAY HELPERS ───────────────────────────────────────
def print_table(rows: list[dict], title: str = ""):
    """Pretty-print a list of expense dicts."""
    if title:
        print(f"\n{'─'*60}")
        print(f"  {title}")
        print(f"{'─'*60}")
    if not rows:
        print("  (no records found)")
        return
    print(f"  {'ID':<4} {'Date':<12} {'Category':<14} {'Amount':>10}  Title")
    print(f"  {'─'*4} {'─'*10} {'─'*12} {'─'*10}  {'─'*22}")
    for r in rows:
        title_short = textwrap.shorten(r["title"], width=22)
        print(f"  {r['id']:<4} {r['date']:<12} {r['category']:<14} ₹{r['amount']:>9,.2f}  {title_short}")
    total = sum(r["amount"] for r in rows)
    print(f"  {'─'*60}")
    print(f"  {'Total':>34} ₹{total:>9,.2f}  ({len(rows)} records)")

def print_summary():
    """Print a summary dashboard."""
    s = ExpenseManager.summary()
    print(f"""
╔══════════════════════════════════════╗
║       EXPENSE SUMMARY DASHBOARD      ║
╠══════════════════════════════════════╣
║  Total spent   : ₹{s['total']:>14,.2f}      ║
║  No. of records: {s['count']:>14}      ║
║  Average/record: ₹{s['average']:>14,.2f}      ║
╠══════════════════════════════════════╣
║  Top categories:                     ║""")
    for cat, amt in s["by_cat"][:5]:
        bar_len = int(amt / max(v for _, v in s["by_cat"]) * 15)
        bar = "█" * bar_len
        print(f"║  {cat:<14} ₹{amt:>8,.0f}  {bar:<15} ║")
    print("╚══════════════════════════════════════╝")

# ── 8. INTERACTIVE COLAB UI ──────────────────────────────────
def launch_ui():
    """ipywidgets-based interactive menu for Google Colab."""

    # ── Shared output area ───────────────────────────────────
    out = widgets.Output()

    # ── Tab: ADD ─────────────────────────────────────────────
    w_title    = widgets.Text(description="Title*",    placeholder="e.g. Grocery run")
    w_amount   = widgets.FloatText(description="Amount*", value=0.0, min=0.01, step=10)
    w_category = widgets.Dropdown(description="Category*", options=CATEGORIES)
    w_date     = widgets.Text(description="Date",      value=date.today().strftime(DATE_FMT),
                              placeholder="YYYY-MM-DD")
    w_note     = widgets.Textarea(description="Note", rows=2)
    btn_add    = widgets.Button(description="Add Expense", button_style="success",
                                icon="plus")

    def on_add(_):
        with out:
            clear_output()
            try:
                if not w_title.value.strip():
                    raise ValueError("Title cannot be empty.")
                if w_amount.value <= 0:
                    raise ValueError("Amount must be greater than zero.")
                new_id = em.create(w_title.value, w_amount.value,
                                   w_category.value, w_date.value, w_note.value)
                print(f"✅ Expense #{new_id} added successfully!")
                w_title.value = ""; w_amount.value = 0; w_note.value = ""
            except Exception as e:
                print(f"❌ Error: {e}")

    btn_add.on_click(on_add)
    tab_add = widgets.VBox([w_title, w_amount, w_category, w_date, w_note, btn_add])

    # ── Tab: VIEW ────────────────────────────────────────────
    w_filter_cat = widgets.Dropdown(description="Category",
                                    options=["All"] + CATEGORIES, value="All")
    w_filter_kw  = widgets.Text(description="Keyword", placeholder="Search title/note")
    btn_view     = widgets.Button(description="Show Expenses", button_style="info")

    def on_view(_):
        with out:
            clear_output()
            rows = em.search(keyword=w_filter_kw.value, category=w_filter_cat.value)
            print_table(rows, "Filtered Results")

    btn_view.on_click(on_view)
    tab_view = widgets.VBox([w_filter_cat, w_filter_kw, btn_view])

    # ── Tab: EDIT ────────────────────────────────────────────
    w_edit_id     = widgets.IntText(description="Expense ID")
    w_edit_title  = widgets.Text(description="New Title",   placeholder="(leave blank to keep)")
    w_edit_amount = widgets.FloatText(description="New Amount", value=0)
    w_edit_cat    = widgets.Dropdown(description="New Category",
                                     options=["(keep)"] + CATEGORIES, value="(keep)")
    w_edit_note   = widgets.Textarea(description="New Note", rows=2)
    btn_edit      = widgets.Button(description="Update", button_style="warning", icon="pencil")

    def on_edit(_):
        with out:
            clear_output()
            kwargs = {}
            if w_edit_title.value.strip():
                kwargs["title"] = w_edit_title.value
            if w_edit_amount.value > 0:
                kwargs["amount"] = w_edit_amount.value
            if w_edit_cat.value != "(keep)":
                kwargs["category"] = w_edit_cat.value
            if w_edit_note.value.strip():
                kwargs["note"] = w_edit_note.value
            if not kwargs:
                print("ℹ️  Nothing to update — fill in at least one field.")
                return
            try:
                ok = em.update(w_edit_id.value, **kwargs)
                print(f"✅ Updated!" if ok else f"❌ ID {w_edit_id.value} not found.")
            except Exception as e:
                print(f"❌ Error: {e}")

    btn_edit.on_click(on_edit)
    tab_edit = widgets.VBox([w_edit_id, w_edit_title, w_edit_amount,
                              w_edit_cat, w_edit_note, btn_edit])

    # ── Tab: DELETE ──────────────────────────────────────────
    w_del_id  = widgets.IntText(description="Expense ID")
    btn_del   = widgets.Button(description="Delete", button_style="danger", icon="trash")
    lbl_conf  = widgets.Label("⚠️  This action is permanent.")

    def on_delete(_):
        with out:
            clear_output()
            ok = em.delete(w_del_id.value)
            print(f"✅ Deleted #{w_del_id.value}." if ok else f"❌ ID {w_del_id.value} not found.")

    btn_del.on_click(on_delete)
    tab_del = widgets.VBox([w_del_id, lbl_conf, btn_del])

    # ── Tab: ANALYTICS ───────────────────────────────────────
    btn_summary    = widgets.Button(description="Text Summary", button_style="primary")
    btn_pie        = widgets.Button(description="Category Pie",  button_style="primary")
    btn_bar        = widgets.Button(description="Monthly Trend", button_style="primary")

    def on_summary(_):
        with out:
            clear_output()
            print_summary()

    def on_pie(_):
        with out:
            clear_output()
            plot_category_pie()

    def on_bar(_):
        with out:
            clear_output()
            plot_monthly_bar()

    btn_summary.on_click(on_summary)
    btn_pie.on_click(on_pie)
    btn_bar.on_click(on_bar)
    tab_analytics = widgets.HBox([btn_summary, btn_pie, btn_bar])

    # ── Tab: EXPORT ──────────────────────────────────────────
    btn_export = widgets.Button(description="Export CSV", button_style="success", icon="download")

    def on_export(_):
        with out:
            clear_output()
            path = em.export_csv()
            if path:
                print(f"✅ Exported to: {path}")
                print("   To download: Files panel (left sidebar) → navigate to /tmp → right-click → Download")
            else:
                print("ℹ️  No data to export.")

    btn_export.on_click(on_export)
    tab_export = widgets.VBox([btn_export])

    # ── Assemble tabs ────────────────────────────────────────
    tabs = widgets.Tab(children=[tab_add, tab_view, tab_edit, tab_del,
                                  tab_analytics, tab_export])
    for i, name in enumerate(["➕ Add", "📋 View", "✏️ Edit", "🗑️ Delete", "📊 Analytics", "💾 Export"]):
        tabs.set_title(i, name)

    header = widgets.HTML("<h2 style='color:#4A4A9A;margin:0 0 8px'>💰 Personal Expense Tracker</h2>")
    display(widgets.VBox([header, tabs, out]))

# ── 9. ENTRY POINT ───────────────────────────────────────────
# Shows the interactive UI in Colab; falls back to a text demo otherwise.
if IN_COLAB:
    launch_ui()
else:
    # ── Fallback: quick functional demo ─────────────────────
    print("=" * 55)
    print("  EXPENSE TRACKER — Quick Demo (non-Colab mode)")
    print("=" * 55)

    print("\n[CREATE] Adding 3 expenses...")
    id1 = em.create("Dinner", 450,  "Food",      "2024-08-01", "Restaurant")
    id2 = em.create("Uber",   180,  "Transport", "2024-08-02")
    id3 = em.create("Book",   299,  "Education", "2024-08-03", "Python cookbook")
    print(f"  Created IDs: {id1}, {id2}, {id3}")

    print("\n[READ] All records:")
    print_table(em.read_all())

    print("\n[UPDATE] Changing 'Dinner' amount to ₹500...")
    em.update(id1, amount=500, note="Updated — split the bill")
    print(f"  Updated record: {em.read_one(id1)}")

    print("\n[DELETE] Removing Uber entry...")
    em.delete(id2)
    print("  Deleted. Remaining records:")
    print_table(em.read_all())

    print("\n[SEARCH] Keyword='book':")
    print_table(em.search(keyword="book"))

    print_summary()

    path = em.export_csv()
    print(f"\n[EXPORT] CSV written to: {path}")
    print("\nAll CRUD operations completed successfully ✅")
