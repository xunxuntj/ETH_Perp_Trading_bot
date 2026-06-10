import os

def search_strategy_exits():
    filepath = "strategy.py"
    if not os.path.exists(filepath):
        print("strategy.py not found")
        return
        
    keywords = ["stop_loss", "sl", "profit", "close_position", "exit", "tp"]
    
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    print("=== SEARCHING STRATEGY.PY FOR EXITS ===")
    count = 0
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if any(kw in line_lower for kw in keywords):
            # Only print lines that look like logic
            if "=" in line or "if " in line or "return " in line or "def " in line:
                print(f"Line {idx+1}: {line.strip()}")
                count += 1
                if count > 50:
                    print("... too many matches, truncated")
                    break

if __name__ == "__main__":
    search_strategy_exits()
