#!/usr/bin/env python3
"""
测试 LOCKED→HOURLY 的逻辑
场景：空仓，entry=2813, qty=27, locked_stop=2341.21, last_1h_st=2385.21
"""

from strategy import is_1h_tighter, calculate_lock_threshold, Phase, Position

def test_locked_to_hourly_short_no_trigger():
    """空仓：1H ST 2385.21 不比 locked_stop 2341.21 更紧，不应转换"""
    entry_price = 2813.0
    qty = 27
    is_long = False
    last_1h_st = 2385.21
    locked_stop = 2341.21
    
    # 判断 1H ST 是否比 locked_stop 更紧
    should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long)
    print(f"[Test] SHORT LOCKED phase:")
    print(f"  entry: {entry_price}, qty: {qty}, is_long: {is_long}")
    print(f"  last_1h_st: {last_1h_st}, locked_stop: {locked_stop}")
    print(f"  is_1h_tighter(last_1h_st={last_1h_st}, locked_stop={locked_stop}, is_long={is_long}): {should_switch}")
    print(f"  Expected: False (2385.21 < 2341.21? NO, so NOT tighter)")
    assert should_switch == False, "Should NOT trigger HOURLY"
    print("  ✅ PASS\n")

def test_locked_to_hourly_short_yes_trigger():
    """空仓：1H ST 2300.0 比 locked_stop 2341.21 更紧，应转换"""
    entry_price = 2813.0
    qty = 27
    is_long = False
    last_1h_st = 2300.0
    locked_stop = 2341.21
    
    # 判断 1H ST 是否比 locked_stop 更紧
    should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long)
    print(f"[Test] SHORT LOCKED phase with tighter 1H ST:")
    print(f"  entry: {entry_price}, qty: {qty}, is_long: {is_long}")
    print(f"  last_1h_st: {last_1h_st}, locked_stop: {locked_stop}")
    print(f"  is_1h_tighter(last_1h_st={last_1h_st}, locked_stop={locked_stop}, is_long={is_long}): {should_switch}")
    print(f"  Expected: True (2300.0 < 2341.21? YES, so IS tighter)")
    assert should_switch == True, "Should trigger HOURLY"
    print("  ✅ PASS\n")

def test_locked_to_hourly_long_no_trigger():
    """多仓：1H ST 2330.0 不比 locked_stop 2350.0 更紧，不应转换"""
    entry_price = 2300.0
    qty = 27
    is_long = True
    last_1h_st = 2330.0
    locked_stop = 2350.0
    
    should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long)
    print(f"[Test] LONG LOCKED phase:")
    print(f"  entry: {entry_price}, qty: {qty}, is_long: {is_long}")
    print(f"  last_1h_st: {last_1h_st}, locked_stop: {locked_stop}")
    print(f"  is_1h_tighter(last_1h_st={last_1h_st}, locked_stop={locked_stop}, is_long={is_long}): {should_switch}")
    print(f"  Expected: False (2330.0 > 2350.0? NO, so NOT tighter)")
    assert should_switch == False, "Should NOT trigger HOURLY"
    print("  ✅ PASS\n")

def test_locked_to_hourly_long_yes_trigger():
    """多仓：1H ST 2360.0 比 locked_stop 2350.0 更紧，应转换"""
    entry_price = 2300.0
    qty = 27
    is_long = True
    last_1h_st = 2360.0
    locked_stop = 2350.0
    
    should_switch = is_1h_tighter(last_1h_st, locked_stop, is_long)
    print(f"[Test] LONG LOCKED phase with tighter 1H ST:")
    print(f"  entry: {entry_price}, qty: {qty}, is_long: {is_long}")
    print(f"  last_1h_st: {last_1h_st}, locked_stop: {locked_stop}")
    print(f"  is_1h_tighter(last_1h_st={last_1h_st}, locked_stop={locked_stop}, is_long={is_long}): {should_switch}")
    print(f"  Expected: True (2360.0 > 2350.0? YES, so IS tighter)")
    assert should_switch == True, "Should trigger HOURLY"
    print("  ✅ PASS\n")

if __name__ == "__main__":
    print("=" * 60)
    print("Testing LOCKED→HOURLY conversion logic")
    print("=" * 60 + "\n")
    
    test_locked_to_hourly_short_no_trigger()
    test_locked_to_hourly_short_yes_trigger()
    test_locked_to_hourly_long_no_trigger()
    test_locked_to_hourly_long_yes_trigger()
    
    print("=" * 60)
    print("All tests PASSED ✅")
    print("=" * 60)
