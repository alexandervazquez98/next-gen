
import requests
import sys
from database import get_db, close_db

def inspect_admin():
    print("Checking 'admin' user in DB...")
    driver = get_db()
    with driver.session() as session:
        res = session.run("MATCH (u:User {username: 'admin'}) RETURN u")
        record = res.single()
        if record:
            user = record["u"]
            print(f"'admin' user FOUND.")
            print(f"Props: {dict(user)}")
        else:
            print("'admin' user NOT FOUND.")
    close_db()

def try_login():
    print("\n Attempting Login (admin/admin)...")
    url = "http://localhost:8000/api/auth/token"
    try:
        # FastAPI OAuth2PasswordRequestForm needs 'username', 'password' as form data
        resp = requests.post(url, data={"username": "admin", "password": "admin"})
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            print("Login OK")
        else:
            print(f"Login Failed (Status {resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    inspect_admin()
    try_login()
