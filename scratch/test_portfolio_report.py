import sys
import os
import datetime
import pandas as pd

# Add the main project directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_portfolio_report

# Mock position close retrieval
def mock_fetch_all_position_closes(client, contract, start_dt, end_dt):
    print(f"[MOCK] fetch_all_position_closes called for {contract}")
    now_t = int(datetime.datetime.now().timestamp())
    
    if contract == "BTC_USDT":
        data = [
            {
                'time': now_t - 3600 * 24 * 3,
                'datetime': '2026-06-07 12:00',
                'side': 'long',
                'pnl': 15.5,
                'pnl_pnl': 16.0,
                'pnl_fee': -0.5,
                'funding_fee': 0.0,
                'text': 't-btc-v1',
                'entry_price': 60000.0,
                'close_price': 61000.0,
                'duration_sec': 7200,
                'open_slippage': 5.0,
                'close_slippage': 5.0,
                'total_slippage': 10.0,
                'size': 0.1,
                'symbol': 'BTC_USDT'
            },
            {
                'time': now_t - 3600 * 24 * 2,
                'datetime': '2026-06-08 15:00',
                'side': 'short',
                'pnl': -5.5,
                'pnl_pnl': -5.0,
                'pnl_fee': -0.5,
                'funding_fee': 0.0,
                'text': 't-btc-v1',
                'entry_price': 61000.0,
                'close_price': 61500.0,
                'duration_sec': 3600,
                'open_slippage': 2.0,
                'close_slippage': 3.0,
                'total_slippage': 5.0,
                'size': 0.1,
                'symbol': 'BTC_USDT'
            }
        ]
    elif contract == "ETH_USDT":
        data = [
            {
                'time': now_t - 3600 * 24 * 4,
                'datetime': '2026-06-06 10:00',
                'side': 'long',
                'pnl': -8.2,
                'pnl_pnl': -7.5,
                'pnl_fee': -0.7,
                'funding_fee': 0.0,
                'text': 't-eth-v1',
                'entry_price': 3000.0,
                'close_price': 2950.0,
                'duration_sec': 14400,
                'open_slippage': 0.5,
                'close_slippage': 0.5,
                'total_slippage': 1.0,
                'size': 1.0,
                'symbol': 'ETH_USDT'
            },
            {
                'time': now_t - 3600 * 24 * 1,
                'datetime': '2026-06-09 18:00',
                'side': 'long',
                'pnl': 24.5,
                'pnl_pnl': 25.5,
                'pnl_fee': -1.0,
                'funding_fee': 0.0,
                'text': 't-eth-v1',
                'entry_price': 2950.0,
                'close_price': 3100.0,
                'duration_sec': 21600,
                'open_slippage': 1.0,
                'close_slippage': 1.0,
                'total_slippage': 2.0,
                'size': 1.0,
                'symbol': 'ETH_USDT'
            }
        ]
    else:
        data = []
        
    return pd.DataFrame(data)

def mock_get_account(self):
    print("[MOCK] get_account called")
    return {"total": 1026.3, "available": 500.0, "unrealised_pnl": 0.0}

def run_test():
    # Monkey-patching
    generate_portfolio_report.fetch_all_position_closes = mock_fetch_all_position_closes
    generate_portfolio_report.GateClient.get_account = mock_get_account
    
    # Mock credentials in environment
    os.environ["GATE_API_KEY"] = "mock_key"
    os.environ["GATE_API_SECRET"] = "mock_secret"
    # Make sure Telegram doesn't send requests or throws cleanly
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    os.environ["TELEGRAM_CHAT_ID"] = ""
    
    # Run main report flow
    print("🎬 Starting report generation execution...")
    try:
        generate_portfolio_report.main()
        print("🎉 Script executed successfully!")
    except Exception as e:
        print(f"❌ Script failed with exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
