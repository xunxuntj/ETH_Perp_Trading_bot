import os

def find_tp_in_strategy():
    filepath = "strategy.py"
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    print("=== INSPECTING STRATEGY.PY ENTRY & TP LOGIC ===")
    for idx, line in enumerate(lines):
        if "tp =" in line or "take_profit" in line or "tp_ratio" in line or "tp_mult" in line:
            print(f"Line {idx+1}: {line.strip()}")

if __name__ == "__main__":
    find_tp_in_strategy()
