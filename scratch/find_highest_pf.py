import os
import json

def find_highest_pf():
    backtest_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backtest")
    optimal_5y_file = os.path.join(backtest_dir, "results", "optimal_5y_portfolio.json")
    optimal_2y_file = os.path.join(backtest_dir, "results", "optimal_strategies_v2.json")
    
    print("=" * 80)
    print("🔍 SEARCHING FOR HIGH PROFIT FACTOR (PF) CONFIGURATIONS")
    print("=" * 80)
    
    if os.path.exists(optimal_5y_file):
        print("\n--- 5-YEAR CYCLES (HIGH PF) ---")
        with open(optimal_5y_file, "r") as f:
            data = json.load(f)
        single_configs = data.get("single_asset_top_configs", {})
        for asset, configs in single_configs.items():
            print(f"\nAsset: {asset}")
            # Sort by Profit Factor desc
            sorted_configs = sorted(configs, key=lambda x: x["metrics"].get("profit_factor", 0.0), reverse=True)
            for rank, cfg in enumerate(sorted_configs[:3]):
                m = cfg["metrics"]
                print(f"  Rank {rank+1}: PF = {m.get('profit_factor', 0.0):.2f} | CAGR = {m.get('cagr', 0.0)*100:+.2f}% | MaxDD = {m.get('max_dd', 0.0)*100:.2f}% | Trades = {m.get('total_trades', 0)}")
                print(f"    Config: Signal={cfg['entry_signal']}, Filter={cfg.get('trend_filter_1h', 'none')}, TP={cfg.get('tp_ratio')}, SL={cfg.get('sl_type')}")
                
    if os.path.exists(optimal_2y_file):
        print("\n--- 2-YEAR RECENT CYCLES (HIGH PF) ---")
        with open(optimal_2y_file, "r") as f:
            data = json.load(f)
        for asset, configs in data.items():
            print(f"\nAsset: {asset}")
            sorted_configs = sorted(configs, key=lambda x: x["metrics"].get("profit_factor", 0.0), reverse=True)
            for rank, cfg in enumerate(sorted_configs[:3]):
                m = cfg["metrics"]
                print(f"  Rank {rank+1}: PF = {m.get('profit_factor', 0.0):.2f} | CAGR = {m.get('cagr', 0.0)*100:+.2f}% | MaxDD = {m.get('max_dd', 0.0)*100:.2f}% | Trades = {m.get('total_trades', 0)}")
                print(f"    Config: Signal={cfg['entry_signal']}, Filter={cfg.get('trend_filter_1h', 'none')}, TP={cfg.get('tp_ratio')}, SL={cfg.get('sl_type')}")

if __name__ == "__main__":
    find_highest_pf()
