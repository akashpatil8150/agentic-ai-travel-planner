import sys
import unittest
import io
import os

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.observability.metrics import ObservabilityMetrics, observability_metrics
from app.observability.logger import request_id_context, planning_id_context, trip_id_context
from app.observability.agent_logger import get_state_context, agent_start, agent_success, agent_failure
from app.state.trip_state import TripState, Location


class TestObservability(unittest.TestCase):
    """
    Test suite for terminal observability, metrics aggregation,
    correlation ID propagation, and formatting without making any external API calls.
    """

    def setUp(self):
        observability_metrics.reset()
        request_id_context.set(None)
        planning_id_context.set(None)
        trip_id_context.set(None)

    def tearDown(self):
        observability_metrics.reset()
        request_id_context.set(None)
        planning_id_context.set(None)
        trip_id_context.set(None)

    def _create_mock_state(self, planning_id="plan-12345", trip_id=42):
        return TripState(
            planning_id=planning_id,
            trip_id=trip_id,
            user_id="user-99",
            origin=Location(name="Mumbai", city="Mumbai", country="India"),
            destination=Location(name="Goa", city="Goa", country="India"),
            travel_dates={"start": "2026-10-01", "end": "2026-10-05"},
            travelers={"adults": 2, "children": 0},
            budget={"amount": 50000, "currency": "INR"},
        )

    # 1. planning_id propagation
    # 2. trip_id propagation
    def test_correlation_id_propagation_via_trip_state(self):
        state = self._create_mock_state(planning_id="plan-12345", trip_id=42)

        # Ensure get_state_context retrieves planning_id and trip_id
        p_id, t_id = get_state_context(state)
        self.assertEqual(p_id, "plan-12345")
        self.assertEqual(t_id, "42")
        self.assertNotEqual(p_id, "None")
        self.assertNotEqual(t_id, "None")

    def test_correlation_context_fallback(self):
        planning_id_context.set("plan-fallback-77")
        trip_id_context.set(88)
        state = TripState(
            user_id="user-99",
            origin=Location(name="Mumbai", city="Mumbai", country="India"),
            destination=Location(name="Goa", city="Goa", country="India"),
            travel_dates={"start": "2026-10-01", "end": "2026-10-05"},
            travelers={"adults": 1, "children": 0},
            budget={"amount": 20000, "currency": "INR"},
        )
        p_id, t_id = get_state_context(state)
        self.assertEqual(p_id, "plan-fallback-77")
        self.assertEqual(t_id, "88")

    # 3. agent start/complete
    # 4. agent duration tracking
    def test_agent_start_complete_and_duration_tracking(self):
        state = self._create_mock_state(planning_id="plan-agent-test", trip_id=55)

        start_time = agent_start("transport", state)
        self.assertIsInstance(start_time, float)

        agent_success("transport", state, start_time, status="success")

        agent_metrics = observability_metrics.get_agent_metrics("transport")
        self.assertIsNotNone(agent_metrics)
        self.assertEqual(agent_metrics["status"], "SUCCESS")
        self.assertGreaterEqual(agent_metrics["duration_ms"], 0.0)

    def test_agent_failure_recording(self):
        state = self._create_mock_state(planning_id="plan-fail-test", trip_id=66)
        start_time = agent_start("hotel", state)
        agent_failure("hotel", state, start_time, ValueError("Hotel provider unavailable"))
        agent_metrics = observability_metrics.get_agent_metrics("hotel")
        self.assertIsNotNone(agent_metrics)
        self.assertEqual(agent_metrics["status"], "FAILED")

    # 5. API metric recording
    def test_api_metric_recording(self):
        # API calls record counts and provider breakdowns quietly without spamming stdout at INFO
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            observability_metrics.record_api_call(
                provider="RailRadar",
                endpoint="/trains/between",
                route="DR→MYS",
                status=200,
                latency_ms=421.72,
                cache="MISS",
            )
            observability_metrics.record_api_call(
                provider="Tavily",
                operation="verification",
                target="place",
                status=200,
                latency_ms=120.5,
                cache="MISS",
            )
        finally:
            sys.stdout = sys.__stdout__

        out = captured_output.getvalue()
        # Should NOT spam stdout with multi-line blocks
        self.assertEqual(out.strip(), "")
        self.assertEqual(observability_metrics.get_api_count(), 2)
        self.assertEqual(observability_metrics.api_provider_calls.get("RailRadar"), 1)
        self.assertEqual(observability_metrics.api_provider_calls.get("Tavily"), 1)

    # 6. cache hit/miss recording
    def test_cache_hit_and_miss_recording(self):
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            observability_metrics.record_cache_event(
                provider="RailRadar",
                type="journey",
                route="DR→MYS",
                result="HIT",
            )
            observability_metrics.record_cache_event(
                provider="LiteAPI",
                type="hotel_search",
                city="Mysuru",
                result="MISS",
            )
            observability_metrics.record_llm_cache(
                model="llama-3.1-8b-instant",
                result="HIT",
            )
        finally:
            sys.stdout = sys.__stdout__

        out = captured_output.getvalue()
        # Cache events should not spam stdout
        self.assertEqual(out.strip(), "")

        # Cache HIT must NOT count as an external API call
        self.assertEqual(observability_metrics.get_api_count(), 0)
        self.assertEqual(observability_metrics.get_cache_hit_count(), 2) # 1 cache + 1 llm cache
        self.assertEqual(observability_metrics.get_cache_miss_count(), 1)

    # 7. LLM token aggregation
    # 10. no cost fields are generated
    def test_llm_token_aggregation_and_no_cost(self):
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            observability_metrics.record_llm_call(
                model="llama-3.1-8b-instant",
                input_tokens=1842,
                output_tokens=326,
                total_tokens=2168,
                latency_ms=834.21,
                status="success",
                planning_id="plan-llm-1",
                trip_id=33,
            )
            observability_metrics.record_llm_call(
                model="llama-3.1-8b-instant",
                input_tokens=1000,
                output_tokens=200,
                total_tokens=1200,
                latency_ms=400.0,
                status="success",
                planning_id="plan-llm-1",
                trip_id=33,
            )
        finally:
            sys.stdout = sys.__stdout__

        out = captured_output.getvalue()
        # Individual LLM calls do not spam stdout
        self.assertEqual(out.strip(), "")

        llm_summary = observability_metrics.get_llm_summary()
        self.assertEqual(llm_summary["calls"], 2)
        self.assertEqual(llm_summary["input_tokens"], 2842)
        self.assertEqual(llm_summary["output_tokens"], 526)
        self.assertEqual(llm_summary["total_tokens"], 3368)

    # 8. final summary rendering
    # 9. missing metric displays N/A
    def test_final_summary_rendering_and_na_fallback(self):
        metrics = ObservabilityMetrics()
        metrics.reset()
        metrics.set_correlation(
            request_id="req-999",
            planning_id="plan-999",
            trip_id=101,
            user_id="user-1",
            route="Dadar → Mysuru",
            dates="17 Sep 2026 → 27 Sep 2026",
            transport="TRAIN",
        )

        metrics.record_agent_complete("transport", 0.0, status="success")
        metrics.record_agent_complete("hotel", 0.0, status="success")

        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            metrics.print_final_observability_summary(
                final_status="READY",
                transport_result="2",
                hotel_result="1",
                places_result="15",
                weather_result="Available",
                itinerary_result="VALID",
            )
        finally:
            sys.stdout = sys.__stdout__

        out = captured_output.getvalue()
        # Verify Headers and Box borders
        self.assertIn("TRIP PLANNING OBSERVABILITY", out)
        self.assertIn("Request     : req-999", out)
        self.assertIn("Planning    : plan-999", out)
        self.assertIn("Trip        : 101", out)
        self.assertIn("Route       : Dadar → Mysuru", out)
        self.assertIn("AGENTS", out)
        self.assertIn("✓ Transport", out)
        self.assertIn("✓ Hotel", out)
        self.assertIn("- Places", out)
        self.assertIn("- Weather", out)
        self.assertIn("EXTERNAL APIs", out)
        self.assertIn("LLM", out)
        self.assertIn("RESULT", out)
        self.assertIn("Transport    : 2", out)
        self.assertIn("Hotels       : 1", out)
        self.assertIn("Places       : 15", out)
        self.assertIn("Weather      : Available", out)
        self.assertIn("Itinerary    : VALID", out)
        self.assertIn("FINAL STATUS : READY", out)

        # Verify no cost in final summary
        self.assertNotIn("cost", out.lower())
        self.assertNotIn("$", out)
        self.assertNotIn("usd", out.lower())


if __name__ == "__main__":
    unittest.main()
