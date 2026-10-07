# ✈️ Agentic AI Travel Planner

An **AI-powered multi-agent travel planning system** that creates verified, optimized, day-by-day travel itineraries for Indian destinations.

It combines **Agentic AI reasoning with deterministic engineering** to handle real-world travel challenges such as railway station discovery, hotel date alignment, sightseeing optimization, weather, and fact verification.

## 🚀 What It Does

The user provides:

- 📍 Origin & destination
- 📅 Travel dates
- 👥 Number of travelers
- 🚆 Transport preference
- 💰 Budget
- 🎯 Travel preferences

The system then generates:

- 🚆 Verified transport options
- 🏨 Curated hotel recommendations
- 📍 Tourist attractions
- 🌦️ Destination weather
- 🗺️ Optimized day-by-day itinerary
- 🔎 Online fact verification

## 🤖 Multi-Agent Architecture

The system uses **LangGraph** to orchestrate specialized agents:

```text
User
  ↓
FastAPI
  ↓
LangGraph Travel Orchestrator
  ├── Transport Agent
  ├── Hotel Agent
  ├── Places Agent
  ├── Weather Agent
  ├── Verification Agent
  └── Itinerary Builder
```

### Two-Phase Planning

**Phase 1**
- Dynamic station discovery
- Train search & validation
- Road transfer calculation
- Hotel search
- User receives hotel options

**Phase 2**
- User selects a hotel
- Attractions are discovered and ranked
- Weather is retrieved
- Places are fact-checked
- Attractions are geographically clustered
- Routes are optimized
- Final itinerary is generated

## 🧠 Key Technical Features

- **6×6 Dynamic Station Discovery** for up to 36 station combinations
- **RailRadar & RailCore** train search with fallback handling
- **Circuit breakers** for API failures and rate limits
- **Hotel arrival-date reconstruction** for multi-day journeys
- **Geoapify** attraction discovery
- **LLM-based semantic ranking**
- **8 km Agglomerative Geographic Clustering**
- **2-Opt route optimization**
- **Tavily Online Fact Verification Layer (OFVL)**
- **Open-Meteo weather integration**
- **PostgreSQL state persistence**
- **JWT authentication**
- **Request / planning / trip correlation tracking**

## 🛠️ Tech Stack

**Backend**
- Python
- FastAPI
- LangGraph
- Pydantic
- SQLAlchemy
- PostgreSQL

**AI**
- Groq / LLM
- Agent-based orchestration
- Semantic ranking

**External Services**
- RailRadar
- RailCore
- LiteAPI
- SerpAPI
- Geoapify
- Open-Meteo
- Tavily

**Frontend**
- React
- Vite

## 🏗️ Project Structure

```text
Agentic_AI_Travel_Planner/
│
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   ├── aggregation/
│   │   ├── api/
│   │   ├── auth/
│   │   ├── core/
│   │   ├── engines/
│   │   ├── itinerary/
│   │   ├── models/
│   │   ├── observability/
│   │   ├── orchestrator/
│   │   ├── resolvers/
│   │   ├── services/
│   │   ├── state/
│   │   └── validation/
│   ├── requirements.txt
│   └── .env
│
└── frontend/
    ├── services/
    ├── utils/
    └── app.py
```

## 🔥 Why Hybrid AI?

The system does **not** use an LLM for everything.

```text
DETERMINISTIC ENGINEERING
├── Train validation
├── Station discovery
├── Date calculations
├── Distance calculations
├── Geographic clustering
└── Route optimization

AGENTIC AI
├── Task planning
├── Hotel preference analysis
├── Attraction ranking
├── Fact verification
└── Itinerary reasoning
```

This separation helps reduce hallucinations while still using AI where reasoning adds value.

## 🎯 Key Differentiators

- Dynamic railway station discovery for destinations such as **Manali, Darjeeling and Ooty**
- Accurate hotel check-in dates based on actual transport arrival
- Geographic clustering to reduce unnecessary travel
- Multi-provider fallback architecture
- Online verification of travel recommendations
- AI reasoning combined with deterministic travel logic

## 🔮 Future Improvements

- Redis-based distributed caching
- Complete live flight search integration
- Real-time traffic-based transfer estimation
- Distributed background agent execution

## 👨‍💻 Project

**Agentic AI Travel Planner**

Built as an end-to-end AI engineering project demonstrating:

**Multi-Agent Systems • FastAPI • LangGraph • LLM Integration • APIs • PostgreSQL • Geospatial Optimization • Fault Tolerance • Observability**