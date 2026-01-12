"""
Performance Benchmarking Suite for JarvisCore

Tests code generation speed, sandbox execution, workflow orchestration,
and storage performance.
"""
import asyncio
import time
import statistics
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent
from jarviscore.execution import (
    create_sandbox_executor,
    create_code_generator,
    create_result_handler,
    create_code_registry,
    create_llm_client
)


# Define test agents as classes
class CalculatorAgent(AutoAgent):
    """Calculator agent for benchmarking."""
    role = "calculator"
    capabilities = ["math", "calculation"]
    system_prompt = "You are a math expert"


class ProcessorAgent(AutoAgent):
    """Data processor agent for benchmarking."""
    role = "processor"
    capabilities = ["data_processing"]
    system_prompt = "You are a data processor"


class PerformanceBenchmark:
    """Performance benchmarking suite."""

    def __init__(self):
        self.results = {}

    async def run_all(self):
        """Run all benchmarks."""
        print("=" * 70)
        print("JarvisCore Performance Benchmarking Suite")
        print("=" * 70)
        print()

        # Benchmark 1: Sandbox Execution Speed
        await self.benchmark_sandbox_execution()

        # Benchmark 2: Code Generation Speed
        await self.benchmark_code_generation()

        # Benchmark 3: Workflow Orchestration
        await self.benchmark_workflow()

        # Benchmark 4: End-to-End Agent Task
        await self.benchmark_end_to_end()

        # Benchmark 5: Storage Performance
        await self.benchmark_storage()

        # Print summary
        self.print_summary()

    async def benchmark_sandbox_execution(self):
        """Benchmark sandbox execution speed."""
        print("Benchmark 1: Sandbox Execution Speed")
        print("-" * 70)

        executor = create_sandbox_executor(timeout=30)

        # Test cases
        test_cases = [
            ("Simple arithmetic", "result = 2 + 2"),
            ("Factorial calculation", "import math\nresult = math.factorial(10)"),
            ("List comprehension", "result = [x**2 for x in range(100)]"),
            ("Dictionary operations", "result = {i: i**2 for i in range(50)}"),
            ("String processing", "result = ' '.join(['test'] * 100)")
        ]

        times = []

        for name, code in test_cases:
            start = time.time()
            result = await executor.execute(code, timeout=10)
            elapsed = time.time() - start

            times.append(elapsed * 1000)  # Convert to ms

            status = "✓" if result['status'] == 'success' else "✗"
            print(f"  {status} {name:<40} {elapsed*1000:>7.2f}ms")

        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)

        print(f"\n  Average: {avg_time:.2f}ms")
        print(f"  Min: {min_time:.2f}ms")
        print(f"  Max: {max_time:.2f}ms")
        print()

        self.results['sandbox'] = {
            'average': avg_time,
            'min': min_time,
            'max': max_time,
            'tests': len(test_cases)
        }

    async def benchmark_code_generation(self):
        """Benchmark code generation speed."""
        print("Benchmark 2: Code Generation Speed")
        print("-" * 70)

        llm = create_llm_client()
        codegen = create_code_generator(llm)

        # Test cases
        test_cases = [
            "Calculate the sum of numbers from 1 to 10",
            "Create a list of even numbers up to 20",
            "Count characters in a string"
        ]

        times = []

        for i, task in enumerate(test_cases, 1):
            try:
                start = time.time()
                code = await codegen.generate(
                    task={'task': task},
                    system_prompt="You are a Python expert",
                    enable_search=False
                )
                elapsed = time.time() - start

                times.append(elapsed * 1000)
                print(f"  ✓ Task {i}: {elapsed*1000:>7.2f}ms")
            except Exception as e:
                print(f"  ✗ Task {i}: Failed - {e}")

        if times:
            avg_time = statistics.mean(times)
            print(f"\n  Average: {avg_time:.2f}ms")
            print()

            self.results['code_generation'] = {
                'average': avg_time,
                'tests': len(times)
            }
        else:
            print("  No successful generations (LLM may not be configured)\n")
            self.results['code_generation'] = {'skipped': True}

    async def benchmark_workflow(self):
        """Benchmark workflow orchestration."""
        print("Benchmark 3: Workflow Orchestration")
        print("-" * 70)

        mesh = Mesh(mode="autonomous")

        mesh.add(CalculatorAgent)
        mesh.add(ProcessorAgent)

        try:
            await mesh.start()

            # Single agent task
            start = time.time()
            results = await mesh.workflow("benchmark", [
                {"agent": "calculator", "task": "Calculate 5!"}
            ])
            single_time = (time.time() - start) * 1000

            status = "✓" if results[0]['status'] == 'success' else "✗"
            print(f"  {status} Single agent task: {single_time:>7.2f}ms")

            # Multi-agent workflow with dependencies
            start = time.time()
            results = await mesh.workflow("benchmark", [
                {"id": "step1", "agent": "calculator", "task": "Generate numbers 1-10"},
                {"id": "step2", "agent": "processor", "task": "Calculate sum", "depends_on": ["step1"]}
            ])
            multi_time = (time.time() - start) * 1000

            status = "✓" if all(r['status'] == 'success' for r in results) else "✗"
            print(f"  {status} Multi-agent workflow (2 steps): {multi_time:>7.2f}ms")

            print()

            self.results['workflow'] = {
                'single_agent': single_time,
                'multi_agent': multi_time
            }

        except Exception as e:
            print(f"  ✗ Workflow failed: {e}\n")
            self.results['workflow'] = {'failed': str(e)}
        finally:
            await mesh.stop()

    async def benchmark_storage(self):
        """Benchmark storage performance."""
        print("Benchmark 5: Storage Performance")
        print("-" * 70)

        handler = create_result_handler()
        registry = create_code_registry()

        # Test ResultHandler write performance
        write_times = []
        for i in range(10):
            start = time.time()
            handler.process_result(
                agent_id=f"benchmark-agent-{i}",
                task=f"Benchmark task {i}",
                code="result = 42",
                output=42,
                status="success",
                execution_time=0.001,
                cost_usd=0.0
            )
            elapsed = (time.time() - start) * 1000
            write_times.append(elapsed)

        avg_write = statistics.mean(write_times)
        print(f"  ✓ ResultHandler writes (avg): {avg_write:>7.2f}ms")

        # Test ResultHandler read performance
        read_times = []
        for i in range(10):
            results = handler.get_agent_results(f"benchmark-agent-{i}", limit=1)
            if results:
                start = time.time()
                result = handler.get_result(results[0]['result_id'])
                elapsed = (time.time() - start) * 1000
                read_times.append(elapsed)

        if read_times:
            avg_read = statistics.mean(read_times)
            print(f"  ✓ ResultHandler reads (avg): {avg_read:>7.2f}ms")
        else:
            avg_read = 0

        # Test CodeRegistry write performance
        reg_write_times = []
        for i in range(10):
            start = time.time()
            registry.register(
                code=f"result = {i}",
                agent_id=f"benchmark-agent-{i}",
                task=f"Task {i}",
                capabilities=["benchmark"],
                output=i
            )
            elapsed = (time.time() - start) * 1000
            reg_write_times.append(elapsed)

        avg_reg_write = statistics.mean(reg_write_times)
        print(f"  ✓ CodeRegistry writes (avg): {avg_reg_write:>7.2f}ms")

        # Test CodeRegistry search performance
        start = time.time()
        matches = registry.search(capabilities=["benchmark"], task_pattern="benchmark", limit=5)
        search_time = (time.time() - start) * 1000
        print(f"  ✓ CodeRegistry search: {search_time:>7.2f}ms")

        print()

        self.results['storage'] = {
            'result_write': avg_write,
            'result_read': avg_read,
            'registry_write': avg_reg_write,
            'registry_search': search_time
        }

    async def benchmark_end_to_end(self):
        """Benchmark complete end-to-end agent task."""
        print("Benchmark 4: End-to-End Agent Task")
        print("-" * 70)

        mesh = Mesh(mode="autonomous")

        mesh.add(CalculatorAgent)

        try:
            await mesh.start()

            start = time.time()
            results = await mesh.workflow("benchmark", [
                {"agent": "calculator", "task": "Calculate the factorial of 8"}
            ])
            elapsed = (time.time() - start) * 1000

            if results[0]['status'] == 'success':
                output = results[0]['output']
                print(f"  ✓ Complete task execution: {elapsed:>7.2f}ms")
                print(f"    Result: {output}")
                print()

                self.results['end_to_end'] = {
                    'time': elapsed,
                    'success': True
                }
            else:
                print(f"  ✗ Task failed: {results[0].get('error')}\n")
                self.results['end_to_end'] = {
                    'success': False,
                    'error': results[0].get('error')
                }

        except Exception as e:
            print(f"  ✗ End-to-end failed: {e}\n")
            self.results['end_to_end'] = {
                'success': False,
                'error': str(e)
            }
        finally:
            await mesh.stop()

    def print_summary(self):
        """Print benchmark summary."""
        print("=" * 70)
        print("Benchmark Summary")
        print("=" * 70)
        print()

        # Sandbox
        if 'sandbox' in self.results:
            sb = self.results['sandbox']
            print(f"Sandbox Execution:")
            print(f"  Average: {sb['average']:.2f}ms")
            print(f"  Range: {sb['min']:.2f}ms - {sb['max']:.2f}ms")
            print()

        # Code Generation
        if 'code_generation' in self.results:
            cg = self.results['code_generation']
            if 'skipped' in cg:
                print(f"Code Generation: SKIPPED (no LLM configured)")
            else:
                print(f"Code Generation:")
                print(f"  Average: {cg['average']:.2f}ms")
            print()

        # Workflow
        if 'workflow' in self.results:
            wf = self.results['workflow']
            if 'failed' not in wf:
                print(f"Workflow Orchestration:")
                print(f"  Single agent: {wf['single_agent']:.2f}ms")
                print(f"  Multi-agent: {wf['multi_agent']:.2f}ms")
            else:
                print(f"Workflow: FAILED ({wf['failed']})")
            print()

        # Storage
        if 'storage' in self.results:
            st = self.results['storage']
            print(f"Storage Performance:")
            print(f"  Result write: {st['result_write']:.2f}ms")
            print(f"  Result read: {st['result_read']:.2f}ms")
            print(f"  Registry write: {st['registry_write']:.2f}ms")
            print(f"  Registry search: {st['registry_search']:.2f}ms")
            print()

        # End-to-End
        if 'end_to_end' in self.results:
            e2e = self.results['end_to_end']
            if e2e.get('success'):
                print(f"End-to-End Task: {e2e['time']:.2f}ms ✓")
            else:
                print(f"End-to-End Task: FAILED")
            print()

        print("=" * 70)
        print("Benchmarking Complete")
        print("=" * 70)


async def main():
    """Run all benchmarks."""
    benchmark = PerformanceBenchmark()
    await benchmark.run_all()


if __name__ == '__main__':
    asyncio.run(main())
