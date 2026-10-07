# ✈️ Agentic AI Travel Planner — Backend

> **Autonomous Multi-Agent Travel Planning & Itinerary Generation System**  
> Powered by **FastAPI**, **LangGraph StateGraph**, **Groq LLM**, and Real-Time Multi-Provider APIs.

---

## 📌 Overview

The **Agentic AI Travel Planner** is an enterprise-grade agentic backend that automates travel planning, transport booking discovery, hotel accommodation search, attraction recommendations, destination weather forecasting, online entity verification, constraint optimization, and day-by-day itinerary generation.

It utilizes an orchestration architecture built with **LangGraph** where specialized autonomous agents collaborate across a **Two-Phase Interactive Planning Lifecycle** with strict deterministic validations and online fact checking.

---

## 🚀 Key Architectural Features

- **Multi-Agent Orchestration**: Built on LangGraph with state machine transitions (`TripState`).
- **Two-Phase Interactive Planning**:
  - **Phase 1 (Option Generation)**: Discovers transport candidates and generates 3 curated hotel options (Budget-Friendly, Best Value, Best Rated).
  - **Phase 2 (Deep Planning & Verification)**: User selects their preferred hotel, triggering attraction discovery, weather forecasting, online fact verification via Tavily (OFVL), agglomerative 8.0 km spatial clustering, 2-opt TSP route optimization, constraint validation, and day-by-day scheduling.
- **Dynamic Station Discovery (6×6 Matrix)**:
  - Discovers candidate railway stations for both origin and destination without hardcoding city-station maps.
  - Seamlessly handles mountain and non-rail destinations (e.g. Manali $\to$ Chandigarh, Darjeeling $\to$ New Jalpaiguri, Ooty $\to$ Coimbatore/Mettupalayam).
  - Evaluates station quality using a deterministic formula that rewards major broad-gauge junctions and penalizes toy train stations.
  - Employs destination-first adaptive search halting on the first valid live train.
- **Fault-Tolerant Multi-Tier Train Search**:
  - **Primary**: RailRadar (`/trains/between`).
  - **Secondary Fallback**: RailCore (`/trains/between`).
  - **Offline Fallback**: `ExactTransportCache` (In-memory validated cache).
  - **Circuit Breaker Pattern**: Automatically trips on HTTP 429 rate limits to prevent cascading timeouts.
  - **Timetable & Stop Sequence Validation**: Enforces that boarding stop index < alighting stop index and filters out trains not running on the requested day.
- **Terrain-Aware Transfer Resolution**:
  - Automatically generates first-mile and last-mile road transfers with Haversine distance, road winding multipliers ($1.25\times$ plain, $1.45\times$ hill), and terrain speed models ($50\text{ km/h}$ vs $30\text{ km/h}$).
- **Hotel Intelligence & Date Alignment**:
  - **City Aliases**: Automatically checks provider-friendly legacy aliases (e.g., `mysuru` $\to$ `Mysore`, `bengaluru` $\to$ `Bangalore`) without altering user state.
  - **Arrival Date Reconstruction**: Derives check-in dates from transport arrival timestamps, preventing users from being billed for nights spent on overnight trains.
  - **Providers**: LiteAPI primary integration with SerpAPI fallback.
- **Places Discovery & Spatial Clustering**:
  - **Geoapify POI Search**: Ingests attractions within 30km radius with agent-level deduplication.
  - **LLM Ranking**: Evaluates attraction relevance against user preferences (with deterministic heuristic fallback).
  - **Agglomerative 8.0 km Clustering**: Groups nearby attractions into single-day clusters using centroid-merge and 2-opt local search.
  - **Intra-Day TSP Optimization**: Solves visit sequence as an open-path Traveling Salesperson Problem to eliminate backtracking.
- **Online Fact Verification Layer (OFVL)**:
  - Real-time Tavily search agent verifying candidate hotels, places, and transit routes against live web data within bounded call budgets.
- **Destination Weather Forecasting**:
  - Open-Meteo integration providing multi-day temperature ranges, rain probability, and WMO weather descriptions attached directly to daily itinerary cards.
- **Production Observability & Telemetry**:
  - Single source of truth metrics tracking `request_id`, `planning_id`, and `trip_id` context.
  - Standardized single-line agent lifecycle logs.
  - Real-time aggregated summary box with API calls, cache hits/misses, LLM token counts, latencies, and zero hallucinated monetary costs.
- **Enterprise Security & Database Lifecycle**:
  - JWT Bearer authentication, PBKDF2/bcrypt password hashing.
  - PostgreSQL persistence with SQLAlchemy models (`Trip`: `DRAFT` $\to$ `PLANNING` $\to$ `READY`, `PlanningSession` state JSON persistence).

---

## 🏗️ Two-Phase Planning Workflow

```mermaid
graph TD
    subgraph "Phase 1: Transport & Hotel Discovery"
        A[User Request: POST /api/trips/plan] --> B[Location Resolver]
        B --> C[TransportAccessResolver: 6x6 Matrix]
        C --> D[TrainService: RailRadar / RailCore / Cache]
        D --> E[TransferResolver: First & Last Mile Transfers]
        E --> F[HotelAgent: LiteAPI + Date Reconstruction]
        F --> G[Save PlanningSession: AWAITING_HOTEL_SELECTION]
    end

    subgraph "User Selection"
        G --> H[User Selects Hotel Tier: POST /select-hotel]
    end

    subgraph "Phase 2: Execution, Clustering & Itinerary Generation"
        H --> I1[PlacesAgent: Geoapify 30km + LLM Rank]
        H --> I2[WeatherAgent: Open-Meteo Forecast]
        I1 --> J[VerificationAgent: OFVL Tavily Search]
        I2 --> J
        J --> K[ResultAggregator & ConstraintEngine]
        K --> L[ItineraryBuilder: Agglomerative 8km Clustering + 2-Opt TSP]
        L --> M[ItineraryValidator: Completeness Check]
        M --> N[Final Trip Status: READY]
    end
```

---

## 📂 Project Structure

```
backend/
├── app/
│   ├── agents/                     # Specialized Domain Agents
│   │   ├── supervisor_agent.py     # Graph supervisor & execution planner
│   │   ├── transport_agent.py      # Transport search & validation agent
│   │   ├── hotel_agent.py          # Hotel discovery, arrival date resolution & ranking
│   │   ├── places_agent.py         # Attractions discovery, deduplication & ranking
│   │   ├── weather_agent.py        # Weather forecasting & date alignment agent
│   │   └── verification_agent.py   # Online fact verification agent (OFVL)
│   ├── aggregation/                # State consolidation & verification
│   │   ├── ofvl.py                 # Online Fact Verification Layer (Tavily)
│   │   └── result_aggregator.py    # Merges verified agent outputs into recommendations
│   ├── api/routes/                 # FastAPI REST Endpoints
│   │   ├── auth_routes.py          # Register, login, user info
│   │   ├── trip_routes.py          # /plan, /search-transport, /select-hotel, /preview-budget
│   │   ├── train_routes.py         # Dedicated direct train queries
│   │   ├── hotel_routes.py         # Dedicated hotel queries
│   │   ├── places_routes.py        # Dedicated places queries
│   │   └── flight_routes.py        # Dedicated flight queries
│   ├── auth/                       # Security & JWT handling
│   │   ├── jwt_handler.py          # Token creation and decoding
│   │   ├── password_handler.py     # Password hashing & verification
│   │   └── auth_dependencies.py    # Depends(get_current_user)
│   ├── core/                       # Core system configuration
│   │   ├── config.py               # Pydantic Settings (.env configuration)
│   │   └── database.py             # SQLAlchemy engine & session factory
│   ├── engines/                    # Deterministic Processing Engines
│   │   ├── constraint_engine.py    # Budget, date, and availability constraint validator
│   │   └── optimization_engine.py  # Score-based sorting & selection optimization
│   ├── input/                      # Input Pydantic Request Schemas
│   │   ├── plan_schema.py          # PlanTripRequest, BudgetPreviewApiRequest
│   │   ├── transport_schema.py     # TransportSearchApiRequest
│   │   └── trip_schema.py          # TripCreate, TripResponse
│   ├── itinerary/                  # Itinerary Generation & Optimization
│   │   └── itinerary_builder.py    # Agglomerative clustering, 2-opt TSP, schedule builder
│   ├── models/                     # PostgreSQL SQLAlchemy Models
│   │   ├── user.py                 # User table
│   │   ├── trip_models.py          # Trip table (DRAFT -> PLANNING -> READY)
│   │   └── planning_session.py     # PlanningSession table (State persistence)
│   ├── observability/              # Logging, Telemetry & Console Metrics
│   │   ├── logger.py               # Root logger & ContextVars (request/planning/trip IDs)
│   │   ├── metrics.py              # ObservabilityMetrics collector & CTO console summary
│   │   ├── agent_logger.py         # Agent execution lifecycle timing helpers
│   │   └── audit_logger.py         # Database audit logging
│   ├── orchestrator/               # LangGraph Workflow Orchestrator
│   │   └── travel_orchestrator.py  # LangGraph StateGraph, Phase 1 & Phase 2 coordinators
│   ├── resolvers/                  # India Transport & Transfer Intelligence
│   │   ├── transport_access_resolver.py # 6x6 candidate station discoverer & ranker
│   │   ├── india_locations.py      # Indian stations/airports geospatial registry
│   │   ├── transfer_resolver.py    # First/last-mile road distance & duration calculator
│   │   ├── station_resolver.py     # Station code canonicalization
│   │   └── airport_resolver.py     # Airport route resolver
│   ├── services/                   # External API Clients & Normalizers
│   │   ├── train/                  # RailRadar & RailCore clients, normalizers, caches
│   │   ├── hotel/                  # LiteAPI & SerpAPI clients, normalizers, location aliases
│   │   ├── places/                 # Geoapify POI service & normalizer
│   │   ├── weather/                # Open-Meteo forecast service
│   │   ├── tavily/                 # Tavily search client for fact verification
│   │   └── llm/                    # Groq/OpenAI client with token telemetry
│   ├── state/                      # Unified Application State
│   │   └── trip_state.py           # TripState Pydantic model with validation
│   └── validation/                 # Post-Generation Verification
│       └── itinerary_validator.py  # Checks itinerary completeness & non-empty days
├── tests/
│   └── test_observability.py       # Observability & telemetry test suite (0 external API calls)
├── .env                            # Environment configuration
├── requirements.txt                # Python dependencies
└── main.py                         # FastAPI Application Entrypoint
```

---

## ⚙️ Setup & Installation

### 1. Environment Configuration
Create a `.env` file in `backend/` with the following variables:

```env
# Application
SECRET_KEY=your_super_secret_jwt_key
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/travel_planner

# LLM Configuration
GROQ_API_KEY=your_groq_api_key
LLM_MODEL=llama-3.1-8b-instant

# External APIs
GEOAPIFY_API_KEY=your_geoapify_key
TAVILY_API_KEY=your_tavily_api_key
LITEAPI_API_KEY=your_liteapi_key
SERPAPI_API_KEY=your_serpapi_key
RAILRADAR_API_KEY=your_railradar_key
RAILCORE_API_KEY=your_railcore_key
```

### 2. Install Dependencies
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Start Application
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

---

## 🧪 Testing

Run backend unit tests (strictly 0 external API calls, offline deterministic testing):

```bash
python -m unittest tests/test_observability.py
```

---

## 📊 Example Observability Output

When planning a trip, the backend terminal prints a standardized console summary:

```text
============================================================
              TRIP PLANNING OBSERVABILITY
============================================================
Request     : req-9645adfb
Planning    : bd21fb8c-34ae-4b01-901a-848f321901a2
Trip        : 34
Route       : Mumbai → Manali
Dates       : 20 Sep 2026 → 27 Sep 2026
------------------------------------------------------------
AGENTS
✓ Transport       0 ms
✓ Hotel        4585 ms
✓ Places       2649 ms
✓ Weather       623 ms
⚠ Verification 42319 ms
------------------------------------------------------------
EXTERNAL APIs
Calls        : 22
Cache        : 0 hit / 22 miss
Rate Limited : NO
------------------------------------------------------------
LLM
Calls        : 3
Input Tokens : 4430
Output Tokens: 678
Total Tokens : 5108
Avg Latency  : 831 ms
------------------------------------------------------------
RESULT
Transport    : 2 option(s)
Hotels       : 1 option(s)
Places       : 15 places
Weather      : Available
Itinerary    : VALID
------------------------------------------------------------
FINAL STATUS : READY
TOTAL TIME   : 73.1 sec
============================================================
```
