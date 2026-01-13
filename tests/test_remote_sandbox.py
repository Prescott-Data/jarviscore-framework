"""
Quick test for remote sandbox execution
Tests connection to Azure Container Apps sandbox service
"""
import asyncio
import sys
from jarviscore.execution.sandbox import create_sandbox_executor


async def test_remote_sandbox():
    """Test remote sandbox with simple calculation."""
    print("=" * 60)
    print("Testing Remote Sandbox (Azure Container Apps)")
    print("=" * 60)

    # Create sandbox executor with remote mode
    config = {
        'sandbox_mode': 'remote',
        'sandbox_service_url': 'https://browser-task-executor.bravesea-3f5f7e75.eastus.azurecontainerapps.io'
    }

    executor = create_sandbox_executor(timeout=30, config=config)

    print(f"\nSandbox Mode: {executor.mode}")
    print(f"Sandbox URL: {executor.sandbox_url}")
    print("\n" + "-" * 60)

    # Test 1: Simple calculation
    print("\nTest 1: Simple Calculation (2 + 2)")
    print("-" * 60)

    code1 = "result = 2 + 2"
    result1 = await executor.execute(code1, timeout=10)

    print(f"Status: {result1['status']}")
    print(f"Output: {result1.get('output')}")
    print(f"Mode: {result1.get('mode')}")
    print(f"Execution Time: {result1.get('execution_time', 0):.3f}s")

    if result1.get('error'):
        print(f"Error: {result1['error']}")
        print(f"Error Type: {result1.get('error_type')}")

    # Test 2: Math calculation
    print("\n" + "-" * 60)
    print("\nTest 2: Math Calculation (factorial of 10)")
    print("-" * 60)

    code2 = """
import math
result = math.factorial(10)
"""

    result2 = await executor.execute(code2, timeout=10)

    print(f"Status: {result2['status']}")
    print(f"Output: {result2.get('output')}")
    print(f"Mode: {result2.get('mode')}")
    print(f"Execution Time: {result2.get('execution_time', 0):.3f}s")

    if result2.get('error'):
        print(f"Error: {result2['error']}")
        print(f"Error Type: {result2.get('error_type')}")

    # Test 3: Data processing
    print("\n" + "-" * 60)
    print("\nTest 3: Data Processing (statistics)")
    print("-" * 60)

    code3 = """
data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
result = {
    'mean': sum(data) / len(data),
    'min': min(data),
    'max': max(data),
    'count': len(data)
}
"""

    result3 = await executor.execute(code3, timeout=10)

    print(f"Status: {result3['status']}")
    print(f"Output: {result3.get('output')}")
    print(f"Mode: {result3.get('mode')}")
    print(f"Execution Time: {result3.get('execution_time', 0):.3f}s")

    if result3.get('error'):
        print(f"Error: {result3['error']}")
        print(f"Error Type: {result3.get('error_type')}")

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    tests_passed = sum([
        result1['status'] == 'success',
        result2['status'] == 'success',
        result3['status'] == 'success'
    ])

    print(f"Tests Passed: {tests_passed}/3")

    if tests_passed == 3:
        print("\n✅ All remote sandbox tests passed!")
        print("Remote execution working correctly.")
        return 0
    else:
        print(f"\n❌ {3 - tests_passed} test(s) failed")
        print("Check error messages above.")
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(test_remote_sandbox())
    sys.exit(exit_code)
