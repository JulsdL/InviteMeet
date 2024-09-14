import sqlite3

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    # Create or update access_codes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_codes (
            code TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0
        )
    ''')

    # Create or update bookings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_code TEXT,
            name TEXT,
            email TEXT,
            slot TEXT,
            confirmed INTEGER DEFAULT 0,
            FOREIGN KEY(access_code) REFERENCES access_codes(code)
        )
    ''')

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
