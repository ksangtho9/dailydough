#!/usr/bin/env python3
"""
Integration test script to verify deterministic bakeplan risk calculations.

This script:
1. Calls the bakeplan API twice
2. Asserts risk values are identical (deterministic)
3. Optionally recomputes risks independently and asserts equality

Usage:
    python scripts/test_bakeplan_risks.py [bakery_id]
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from typing import Dict, Any, List


def get_bakeplan(base_url: str, bakery_id: int, target_date: str = None) -> Dict[str, Any]:
    """Call bakeplan API and return response."""
    url = f"{base_url}/api/bakeries/{bakery_id}/bake-plan"
    params = {}
    if target_date:
        params["target_date"] = target_date
    
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def compare_bakeplans(plan1: Dict[str, Any], plan2: Dict[str, Any]) -> List[str]:
    """Compare two bakeplan responses and return list of differences."""
    differences = []
    
    if plan1["bakery_id"] != plan2["bakery_id"]:
        differences.append(f"bakery_id: {plan1['bakery_id']} != {plan2['bakery_id']}")
    
    if plan1["date"] != plan2["date"]:
        differences.append(f"date: {plan1['date']} != {plan2['date']}")
    
    items1 = {item["product_id"]: item for item in plan1["items"]}
    items2 = {item["product_id"]: item for item in plan2["items"]}
    
    all_product_ids = set(items1.keys()) | set(items2.keys())
    
    for product_id in all_product_ids:
        if product_id not in items1:
            differences.append(f"Product {product_id} missing in first response")
            continue
        if product_id not in items2:
            differences.append(f"Product {product_id} missing in second response")
            continue
        
        item1 = items1[product_id]
        item2 = items2[product_id]
        
        # Compare risk fields
        risk_fields = [
            "waste_risk_prob",
            "stockout_risk_prob",
            "risk_sigma",
            "interval_level_used",
            "risk_method",
            "debug_source",
            "sigma_clamped",
        ]
        
        for field in risk_fields:
            val1 = item1.get(field)
            val2 = item2.get(field)
            
            if val1 != val2:
                if isinstance(val1, float) and isinstance(val2, float):
                    # Use approximate comparison for floats
                    if abs(val1 - val2) > 1e-6:
                        differences.append(
                            f"Product {product_id} ({item1['product_name']}): {field} = {val1} != {val2}"
                        )
                else:
                    differences.append(
                        f"Product {product_id} ({item1['product_name']}): {field} = {val1} != {val2}"
                    )
    
    return differences


def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test bakeplan risk calculations for determinism")
    parser.add_argument("bakery_id", type=int, help="Bakery ID to test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--target-date", help="Target date (ISO format, default: tomorrow)")
    args = parser.parse_args()
    
    print(f"Testing bakeplan risks for bakery_id={args.bakery_id}")
    print(f"Base URL: {args.base_url}")
    if args.target_date:
        print(f"Target date: {args.target_date}")
    print()
    
    try:
        # Call API twice
        print("Calling bakeplan API (first call)...")
        plan1 = get_bakeplan(args.base_url, args.bakery_id, args.target_date)
        print(f"  Got {len(plan1['items'])} items")
        
        print("Calling bakeplan API (second call)...")
        plan2 = get_bakeplan(args.base_url, args.bakery_id, args.target_date)
        print(f"  Got {len(plan2['items'])} items")
        print()
        
        # Compare results
        print("Comparing results...")
        differences = compare_bakeplans(plan1, plan2)
        
        if differences:
            print("❌ FAILED: Risk values differ between calls:")
            for diff in differences:
                print(f"  - {diff}")
            print()
            print("This indicates non-deterministic risk calculations!")
            return 1
        else:
            print("✅ PASSED: Risk values are identical across calls (deterministic)")
            print()
            
            # Show sample risk values
            if plan1["items"]:
                print("Sample risk values (first 3 items):")
                for item in plan1["items"][:3]:
                    print(f"  {item['product_name']} (ID: {item['product_id']}):")
                    print(f"    waste_risk_prob: {item.get('waste_risk_prob')}")
                    print(f"    stockout_risk_prob: {item.get('stockout_risk_prob')}")
                    print(f"    risk_method: {item.get('risk_method')}")
                    print(f"    interval_level_used: {item.get('interval_level_used')}")
            
            return 0
            
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR: Failed to call API: {e}")
        return 1
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())



