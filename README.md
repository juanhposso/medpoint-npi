# medpoint-npi — Physician Verification Engine
## Project Context & Build Guide

---

## 👤 About the Developer

- **Name:** Juan David Hernandez
- **Location:** Medellin, Colombia
- **Stack:** Python, FastAPI, PostgreSQL, Redis, Kafka, Docker
- **Goal:** Build a production-grade physician verification system that practices real-world engineering concepts including load balancing, caching, async messaging, error handling, and observability
- **Learning objectives:** Hands-on experience with Nginx, Redis, Kafka, DLQ, exponential backoff, and load testing

---

## 🎯 Project Goal

Build a **Physician Verification Engine** that verifies US-based physicians using:
- NPI Registry API (National Provider Identifier)
- California DCA License Database
- Fuzzy matching for name disambiguation

This is intentionally over-engineered for learning purposes — simulating how a real healthcare platform at scale would handle 20,000+ physician lookups per day.

---

## 🏗️ Full System Architecture

```
Client Request (verify physician)
        ↓
   Nginx (Load Balancer)
        ↓
   FastAPI Servers (multiple instances)
        ↓
   Redis (check if NPI already verified)
   Cache Hit?  → Return cached result instantly
   Cache Miss? → Continue pipeline
        ↓
   Kafka (publish verification_requested event)
        ↓
   Worker Services (Kafka consumers)
   ├── NPI Fetcher Worker
   ├── DCA License Worker
   └── Fuzzy Matcher Worker (RapidFuzz)
        ↓
   PostgreSQL (store verified physician)
        ↓
   Kafka (publish verification_complete event)
        ↓
   Notification Worker
   └── Webhook / Email notification
        ↓
   Dead Letter Queue
   (failed verifications after retries)
```

---

## 📁 Project Structure

```
medpoint-npi/
├── docker-compose.yml          # Full local infrastructure
├── nginx/
│   └── nginx.conf              # Load balancer config
├── api/
│   ├── main.py                 # FastAPI app
│   ├── routes/
│   │   └── verify.py           # POST /verify endpoint
│   ├── services/
│   │   ├── cache.py            # Redis cache logic
│   │   └── producer.py         # Kafka producer
│   └── models/
│       └── physician.py        # Pydantic models
├── workers/
│   ├── npi_fetcher.py          # NPI Registry API worker
│   ├── dca_reader.py           # California DCA license worker
│   ├── fuzzy_matcher.py        # RapidFuzz matching worker
│   └── notification_worker.py  # Send results back to client
├── db/
│   └── schema.sql              # PostgreSQL table definitions
├── tests/
│   └── test_verify.py          # pytest suite
└── requirements.txt
```

---

## 🐳 Infrastructure Stack

| Service | Purpose | Port |
|---|---|---|
| Nginx | Load balancer | 80 |
| FastAPI (x2) | API servers | 8001, 8002 |
| Redis | Cache + deduplication | 6379 |
| Kafka | Message queue | 9092 |
| Zookeeper | Kafka coordinator | 2181 |
| PostgreSQL | Persistent storage | 5432 |

---

## 📋 Kafka Topics

| Topic | Purpose |
|---|---|
| `verification_requested` | New physician lookup request |
| `npi_fetched` | NPI data retrieved successfully |
| `dca_checked` | DCA license verification complete |
| `verification_complete` | Full verification done, notify client |
| `verification_dlq` | Dead Letter Queue — failed verifications |

---

## 🗄️ PostgreSQL Schema

```sql
CREATE TABLE physicians (
    id              SERIAL PRIMARY KEY,
    npi             VARCHAR(10) UNIQUE NOT NULL,
    full_name       VARCHAR(255),
    specialty       VARCHAR(255),
    taxonomy_code   VARCHAR(50),
    dca_license     VARCHAR(100),
    address         TEXT,
    is_active       BOOLEAN DEFAULT TRUE,
    verified_at     TIMESTAMP DEFAULT NOW(),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_physicians_npi ON physicians(npi);
CREATE INDEX idx_physicians_name ON physicians(full_name);
```

---

## 🔄 Request Flow — Step by Step

### Flow 1: Cache Miss (first time lookup)
```
1. Client sends POST /verify { "npi": "1234567890" }
2. Nginx load balances to one of the FastAPI instances
3. FastAPI checks Redis — cache miss
4. FastAPI publishes to Kafka topic: verification_requested
5. NPI Fetcher Worker consumes event → hits NPI Registry API
6. DCA Reader Worker → checks California DCA license database
7. Fuzzy Matcher Worker → validates name consistency with RapidFuzz
8. Results stored in PostgreSQL
9. Redis cache updated with TTL (24 hours)
10. Kafka publishes to verification_complete
11. Notification Worker sends result to client webhook
```

### Flow 2: Cache Hit (previously verified)
```
1. Client sends POST /verify { "npi": "1234567890" }
2. Nginx load balances to FastAPI
3. FastAPI checks Redis — cache hit
4. Returns cached result immediately (< 10ms)
5. Kafka never touched — zero API calls
```

---

## ⚠️ Error Handling Strategy

### Exponential Backoff
```python
import time

def fetch_with_backoff(url, max_retries=4):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            wait_time = 2 ** attempt  # 1s, 2s, 4s, 8s
            if attempt < max_retries - 1:
                time.sleep(wait_time)
            else:
                raise  # Send to DLQ after all retries exhausted
```

### Dead Letter Queue
- After all retries exhausted → publish to `verification_dlq` topic
- DLQ consumer logs the failure with full context
- Manual review + reprocessing possible from DLQ

### Redis Deduplication
- Before sending notification, check Redis for duplicate
- Key: `notif:{npi}:{timestamp_minute}`
- TTL: 60 seconds — prevents duplicate notifications

---

## 🔧 Key Technical Concepts Implemented

| Concept | Where Used |
|---|---|
| Load Balancer | Nginx → multiple FastAPI instances |
| Caching | Redis for NPI lookup results |
| Message Queue | Kafka for async worker pipeline |
| Publisher/Subscriber | Kafka topics decouple services |
| Dead Letter Queue | Failed verifications after retries |
| Exponential Backoff | API retry logic in workers |
| Deduplication | Redis prevents duplicate notifications |
| Database Indexing | PostgreSQL index on NPI column |
| Horizontal Scaling | Multiple FastAPI + worker instances |
| Data Validation | Pydantic models + schema enforcement |

---

## 🏗️ Build Phases

### ✅ Phase 1 — Completed (before this guide)
- Project scaffolding
- NPI fetcher basic implementation
- Pydantic models
- pytest suite foundation

### 🔲 Phase 2 — Current Target
- `dca_reader.py` — California DCA license lookup
- `fuzzy_matcher.py` — RapidFuzz name matching
- Basic pytest coverage for both

### 🔲 Phase 3 — Docker Infrastructure
```yaml
# docker-compose.yml target
services:
  postgres, redis, kafka, zookeeper, 
  fastapi-1, fastapi-2, nginx, workers
```

### 🔲 Phase 4 — FastAPI + Kafka Integration
- `POST /verify` endpoint
- Redis cache check
- Kafka producer on cache miss

### 🔲 Phase 5 — Worker Services
- NPI Fetcher Worker (Kafka consumer)
- DCA Reader Worker
- Fuzzy Matcher Worker
- Notification Worker

### 🔲 Phase 6 — Error Handling
- Exponential backoff in all workers
- DLQ implementation
- Logging and observability

### 🔲 Phase 7 — Load Testing
- Locust for concurrent request simulation
- Monitor Redis cache hit rate
- Run EXPLAIN ANALYZE on PostgreSQL
- Validate Kafka partition distribution

---

## 🧪 Load Testing Target

```python
# locustfile.py
from locust import HttpUser, task

class PhysicianVerification(HttpUser):
    @task
    def verify_physician(self):
        self.client.post("/verify", json={"npi": "1234567890"})
```

Target: Handle **1,000 concurrent requests** with:
- Redis cache hit rate > 80%
- P95 latency < 200ms for cache hits
- Zero message loss in Kafka

---

## 📦 Dependencies

```txt
# requirements.txt
fastapi
uvicorn
redis
kafka-python
psycopg2-binary
pydantic
rapidfuzz
requests
pytest
locust
python-dotenv
```

---

## 🎯 How to Use This Guide

**Start every session by:**
1. Reading this file fully
2. Identifying the current phase
3. Asking Claude to guide you through the next component

**Simulated real work scenario:**
- Treat every feature as a ticket
- Write tests before or alongside implementation
- Document technical decisions and tradeoffs
- Use EXPLAIN ANALYZE after every significant DB query
- Commit to GitHub after each phase

---

## 💬 Conversation Style Preferences

- Juan speaks English and Spanish — either is fine
- Prefers practical, step-by-step guidance
- Wants to understand the **why** behind every decision
- Learning goal: be able to explain every component confidently in a technical interview
- Mentor should push for precision — specific metrics, tradeoffs, and justifications over vague answers

---

*Generated as a project continuity document — paste this into a new conversation window to resume the build with full context.*