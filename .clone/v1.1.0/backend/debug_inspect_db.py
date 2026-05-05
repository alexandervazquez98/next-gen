
from database import get_db, close_db
import json

def inspect_users():
    print("Inspect Users in DB...")
    driver = get_db()
    
    query = "MATCH (u:User) RETURN u, elementId(u) as id"
    results, _, _ = driver.execute_query(query)
    
    print(f"Found {len(results)} user nodes.")
    
    for record in results:
        node = record["u"]
        node_id = record["id"]
        data = dict(node)
        print(f"Node ID: {node_id}")
        
        # Use simple print as data might have datetimes not serializable
        print(data)
        
        if "username" not in data:
            print("MISSING USERNAME!")
        else:
            print(f"Username: {data['username']}")
            
        print("-" * 20)

    close_db()

if __name__ == "__main__":
    inspect_users()
