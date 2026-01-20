"""
Test 1: Standalone Analyst

The Analyst agent working alone - no framework.
Can analyze data, but cannot receive requests from other agents.
"""


class Analyst:
    """
    Standalone Analyst agent.

    Capabilities:
    - Analyze data
    - Generate reports
    - Provide recommendations
    """

    def __init__(self):
        self.name = "analyst"
        self.analyses_count = 0

    def analyze(self, data: str) -> dict:
        """Analyze data and return insights."""
        self.analyses_count += 1
        return {
            "id": self.analyses_count,
            "input": data,
            "summary": f"Analysis of '{data}' shows positive trends",
            "confidence": 0.85,
            "recommendation": "Proceed with caution"
        }

    def generate_report(self, analysis: dict) -> str:
        """Generate a text report from analysis."""
        return (
            f"Report #{analysis['id']}\n"
            f"Summary: {analysis['summary']}\n"
            f"Confidence: {analysis['confidence']}\n"
            f"Recommendation: {analysis['recommendation']}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_analyst_init():
    """Analyst initializes correctly."""
    analyst = Analyst()
    assert analyst.name == "analyst"
    assert analyst.analyses_count == 0
    print("✓ Analyst initialized")


def test_analyst_analyze():
    """Analyst can analyze data."""
    analyst = Analyst()
    result = analyst.analyze("Q4 sales data")

    assert result["id"] == 1
    assert result["confidence"] == 0.85
    assert "Q4 sales data" in result["summary"]
    print(f"✓ Analysis: {result['summary']}")


def test_analyst_multiple_analyses():
    """Analyst tracks analysis count."""
    analyst = Analyst()

    analyst.analyze("data 1")
    analyst.analyze("data 2")
    result = analyst.analyze("data 3")

    assert analyst.analyses_count == 3
    assert result["id"] == 3
    print(f"✓ Multiple analyses: count = {analyst.analyses_count}")


def test_analyst_generate_report():
    """Analyst can generate reports."""
    analyst = Analyst()
    analysis = analyst.analyze("market trends")
    report = analyst.generate_report(analysis)

    assert "Report #1" in report
    assert "market trends" in report
    print(f"✓ Report generated:\n{report}")


def test_analyst_cannot_receive_requests():
    """Analyst has NO way to receive external requests."""
    analyst = Analyst()

    # No peers
    assert not hasattr(analyst, 'peers')

    # No receive method
    assert not hasattr(analyst, 'receive')

    # No way to listen for incoming messages
    assert not hasattr(analyst, 'run')

    print("✓ Analyst CANNOT receive external requests (limitation)")


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 1: STANDALONE ANALYST")
    print("="*60 + "\n")

    test_analyst_init()
    test_analyst_analyze()
    test_analyst_multiple_analyses()
    test_analyst_generate_report()
    test_analyst_cannot_receive_requests()

    print("\n" + "-"*60)
    print("Analyst works, but cannot receive requests from others.")
    print("-"*60 + "\n")
