import os

def inspect_strategy():
    filepath = "strategy.py"
    if not os.path.exists(filepath):
        print("strategy.py not found")
        return
        
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    print("=== INSPECTING STRATEGY.PY FOR TP/SL CONFIGS ===")
    for idx, line in enumerate(lines):
        if "tp_ratio" in line or "take_profit" in line or "tp" in line.lower():
            if "def " in line or "=" in line or "return" in line:
                print(f"Line {idx+1}: {line.strip()}")

if __name__ == "__main__":
    inspect_strategy()
