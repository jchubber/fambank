"""Test that annualized interest rates are properly converted to daily rates."""

import math


def test_daily_rate_conversion():
    """Test that annual rates are correctly converted to daily rates."""
    # Example: 6% annual rate should convert to approximately 0.01596% daily rate
    annual_rate = 0.06  # 6%
    
    # Daily rate formula: ((1 + annual_rate)^(1/365)) - 1
    daily_rate = ((1 + annual_rate) ** (1/365)) - 1
    
    # Expected: approximately 0.0001596 (0.01596%)
    expected_daily_rate = 0.0001596
    tolerance = 0.000001
    
    assert abs(daily_rate - expected_daily_rate) < tolerance, \
        f"Expected daily rate ~{expected_daily_rate}, got {daily_rate}"
    
    # Verify that compounding daily for 365 days gives us back the annual rate
    # (1 + daily_rate)^365 should equal (1 + annual_rate)
    compounded_annual = (1 + daily_rate) ** 365
    expected_compounded = 1 + annual_rate
    
    assert abs(compounded_annual - expected_compounded) < 0.0001, \
        f"Daily rate should compound to annual rate. Got {compounded_annual}, expected {expected_compounded}"
    
    # Test with a $1000 balance and 365 days
    # Using daily rate: 1000 * ((1 + 0.06)^(1/365) - 1) * 365 should compound to ~$1060
    balance = 1000.0
    final_balance = balance * ((1 + daily_rate) ** 365)
    expected_final = balance * (1 + annual_rate)  # Should be $1060
    
    assert abs(final_balance - expected_final) < 0.01, \
        f"After 365 days, balance should be ${expected_final:.2f}, got ${final_balance:.2f}"
    
    print(f"✓ Daily rate conversion test passed")
    print(f"  Annual rate: {annual_rate*100:.2f}%")
    print(f"  Daily rate: {daily_rate*100:.4f}%")
    print(f"  $1000 after 365 days: ${final_balance:.2f}")


def test_specific_example():
    """Test the specific example from the user."""
    # T-bill: 4%, multiplier: 1.5x
    treasury_yield = 0.04  # 4%
    multiplier = 1.5
    annual_rate = treasury_yield * multiplier  # 6%
    
    # Convert to daily rate
    daily_rate = ((1 + annual_rate) ** (1/365)) - 1
    
    # Expected daily rate: ~0.01596%
    expected_daily_rate = 0.0001596
    
    assert abs(daily_rate - expected_daily_rate) < 0.00001, \
        f"Expected daily rate ~{expected_daily_rate}, got {daily_rate}"
    
    print(f"✓ Specific example test passed")
    print(f"  T-bill: {treasury_yield*100:.2f}%, Multiplier: {multiplier}x")
    print(f"  Annual rate: {annual_rate*100:.2f}%")
    print(f"  Daily rate: {daily_rate*100:.4f}%")


if __name__ == "__main__":
    test_daily_rate_conversion()
    test_specific_example()
    print("\nAll daily rate conversion tests passed!")

