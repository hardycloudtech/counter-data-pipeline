import os
import platform
import getpass
import psycopg2
from psycopg2 import sql, extras
from datetime import datetime

# Determine platform and DB credentials
dbuser = 'eghohar'
dbhost_windows = '192.168.0.105'
dbhost_default_non_windows = 'localhost'

if platform.system() == 'Windows':
    dbhost = dbhost_windows
else:
    dbuser = getpass.getuser()
    dbhost = dbhost_default_non_windows

print(f"Database User: {dbuser}")
print(f"Database Host: {dbhost}")

# Connect to PostgreSQL
def connect_postgres(dbname, use_password=False):
    try:
        if use_password:
            password = getpass.getpass(f"Enter password for PostgreSQL user '{dbuser}': ")
            return psycopg2.connect(dbname=dbname, user=dbuser, password=password, host=dbhost)
        else:
            return psycopg2.connect(dbname=dbname, user=dbuser, host=dbhost)
    except psycopg2.OperationalError:
        print("Peer authentication failed or password is required. Trying with password...")
        password = getpass.getpass(f"Enter password for PostgreSQL user '{dbuser}': ")
        return psycopg2.connect(dbname=dbname, user=dbuser, password=password, host=dbhost)

# Check if a database exists
def database_exists(conn, dbname):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
    exists = cur.fetchone() is not None
    cur.close()
    return exists

# Parse counter files and load deltas to DB
def parse_and_insert_deltas(conn, data_folder):
    cur = conn.cursor()

    # Create target table
    cur.execute("""
        DROP TABLE IF EXISTS counters;
        CREATE TABLE counters (
            timestamp TIMESTAMP,
            node TEXT,
            server TEXT,
            command_id TEXT,
            protocol TEXT,
            metric TEXT,
            value NUMERIC,
            delta NUMERIC
        )
    """)
    conn.commit()

    last_seen = dict()
    batch = []
    batch_size = 5000

    for fname in sorted(os.listdir(data_folder)):
        if not fname.endswith(".log"):
            continue

        full_path = os.path.join(data_folder, fname)
        with open(full_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = [x.strip() for x in line.strip().split(',')]
                if len(parts) != 7:
                    continue  # skip malformed lines

                try:
                    ts = datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
                    value = float(parts[6])
                except Exception:
                    continue

                node, server, cmd_id, proto, metric = parts[1:6]
                signature = (node, server, cmd_id, proto, metric)

                delta = None
                if signature in last_seen:
                    delta = value - last_seen[signature]
                last_seen[signature] = value

                batch.append((ts, node, server, cmd_id, proto, metric, value, delta))

                if len(batch) >= batch_size:
                    extras.execute_batch(cur, """
                        INSERT INTO counters (timestamp, node, server, command_id, protocol, metric, value, delta)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, batch)
                    conn.commit()
                    batch.clear()

    # Insert remaining batch
    if batch:
        extras.execute_batch(cur, """
            INSERT INTO counters (timestamp, node, server, command_id, protocol, metric, value, delta)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, batch)
        conn.commit()

    cur.close()
    print("All counter files parsed, deltas calculated, and data inserted.")

# Main
if __name__ == "__main__":
    db_name = input("Enter PostgreSQL database name to create/use: ")

    conn = connect_postgres("postgres")
    conn.autocommit = True
    if not database_exists(conn, db_name):
        cur = conn.cursor()
        cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(db_name)))
        cur.close()
        print(f"Database {db_name} created successfully.")
    else:
        print(f"Database {db_name} already exists. Using existing database.")
    conn.close()

    # Connect to the target DB
    conn = connect_postgres(db_name, use_password=True)

    # Load counter files and compute deltas
    base_folder = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(base_folder, "data")
    parse_and_insert_deltas(conn, data_folder)

    conn.close()
    print("Done.")
