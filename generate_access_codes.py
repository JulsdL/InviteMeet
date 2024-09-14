import sqlite3
import uuid

def generate_access_codes(n):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    for _ in range(n):
        code = str(uuid.uuid4())
        try:
            cursor.execute('INSERT INTO access_codes (code) VALUES (?)', (code,))
        except sqlite3.IntegrityError:
            pass  # Skip duplicates

    conn.commit()
    conn.close()
    print(f"Generated {n} access codes.")

if __name__ == "__main__":
    generate_access_codes(5)  # Generates 5 access codes
