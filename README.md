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

## 📁 Project Structure (current state after Phase 2A)

```
medpoint-npi/
├── docker-compose.yml          # Full local infrastructure (Phase 3 target)
├── pytest.ini                  # pythonpath = . (required for imports)
├── nginx/
│   └── nginx.conf              # Load balancer config (Phase 3 target)
├── core/                       # ← NEW in Phase 2A: shared layer, no layer owns models
│   ├── __init__.py
│   ├── models.py               # NPIRecord, NPIAddress, NPITaxonomy, DCAResult + all exceptions
│   └── matching.py             # MatchVerdict (Enum), MatchResult (Pydantic)
├── api/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app (Phase 4 target)
│   ├── routes/
│   │   ├── __init__.py
│   │   └── verify.py           # POST /verify endpoint (Phase 4 target)
│   └── services/
│       ├── __init__.py
│       ├── cache.py            # Redis cache logic (Phase 4 target)
│       └── producer.py         # Kafka producer (Phase 4 target)
│   # NOTE: api/models/ does NOT exist — models live in core/ to avoid
│   # wrong dependency direction (workers importing from api/)
├── workers/
│   ├── __init__.py
│   ├── npi_fetcher.py          # NPI Registry API client — imports models from core/
│   ├── dca_reader.py           # DCA license lookup (Excel-backed, Phase 2A ✅)
│   ├── fuzzy_matcher.py        # RapidFuzz name matching (Phase 2A ✅)
│   └── notification_worker.py  # Send results back to client (Phase 5 target)
├── data/
│   └── medical_board.xlsx      # Local DCA snapshot — California Medical Board
│   # NOTE: original source file is .xls (HTML disguised as Excel, unreadable by pandas)
│   # Solution: open in Google Sheets → download as .xlsx → use openpyxl engine
├── db/
│   └── schema.sql              # PostgreSQL table definitions
├── tests/
│   ├── test_verify.py          # 23 tests — Phase 1 ✅ (NPI models + helpers)
│   ├── test_dca_reader.py      # 9 tests — Phase 2A ✅
│   └── test_fuzzy_matcher.py   # 3 tests — Phase 2A ✅
└── requirements.txt
```

**Total tests passing: 35**

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

## 🧠 Core Models (core/models.py)

### NPI Models (Phase 1)
- `NPIAddress` — validated practice/mailing address with phone/zip normalization
- `NPITaxonomy` — primary specialty/taxonomy block
- `NPIRecord` — canonical NPI record with `full_name` and `specialty` properties

### DCA Models (Phase 2A)
```python
class DCAResult(BaseModel):
    license_number: str
    last_name: str
    first_name: str
    middle_name: Optional[str] = None
    license_type: str
    license_status: str
    expiration_date: date
    original_issue_date: date
    is_valid: bool  # derived: status == "Current" and expiration_date >= today
```

### Custom Exceptions (core/models.py)
- `NPINotFoundError` — NPI returns zero results
- `NPIAPIError` — HTTP errors or unexpected API responses
- `NPIValidationError` — Pydantic validation failure

---

## 🧠 Matching Models (core/matching.py)

```python
class MatchVerdict(str, Enum):
    MATCH = "MATCH"
    REVIEW = "REVIEW"
    NO_MATCH = "NO_MATCH"

class MatchResult(BaseModel):
    npi_name: str
    dca_name: str
    score: float       # normalized to [0, 1]
    verdict: MatchVerdict
```

---

## 🔍 Fuzzy Matching Design (workers/fuzzy_matcher.py)

**Algorithm:** `fuzz.token_sort_ratio` from RapidFuzz
- Normalizes word order before scoring → `"JOHN SMITH"` vs `"SMITH JOHN"` = 1.0
- Safer than `token_set_ratio` which is too permissive for physician names

**Thresholds (calibrated with real measurements):**
| Score | Verdict | Meaning |
|---|---|---|
| ≥ 0.90 | `MATCH` | High confidence, proceed |
| 0.75–0.89 | `REVIEW` | Possible name variation, flag for human |
| < 0.75 | `NO_MATCH` | Reject |

**Real calibration examples:**
- `"JOHN A SMITH"` vs `"JOHN SMITH"` → 0.909 → `MATCH`
- `"ROBERT JOHNSON"` vs `"ROB JOHNSON"` → 0.88 → `REVIEW`
- `"KATHERINE ELIZABETH SMITH"` vs `"KATHY SMITH"` → 0.555 → `NO_MATCH`

**Public functions:**
- `fuzzy_match(npi_name, dca_name) → MatchResult`
- `batch_fuzzy_match(pairs) → list[MatchResult]`
- `build_full_name(first, middle, last) → str` — normalizes to uppercase, strips spaces per part

**Important design decision:** License numbers are NEVER fuzzy matched — exact lookup only via `query_by_license()`. Fuzzy matching license numbers is a patient safety risk.

---

## 📋 DCA Reader Design (workers/dca_reader.py)

**Data source:** `data/medical_board.xlsx` — California Medical Board snapshot
**Engine:** `openpyxl` (file is .xlsx format despite .xls origin)

**Pickle cache:** On first run, DataFrame is cached to `data/dca_data.pkl` to avoid reading Excel on every startup. Tech debt flag: corrupted `.pkl` serves bad data silently — acceptable for Phase 2A, replaced by PostgreSQL in Phase 3.

**Public functions:**
- `query_by_license(license_number: str) → DCAResult | None`
  - Handles non-numeric input gracefully (returns `None`)
  - Handles leading zeros (`"00012345"` → finds license `12345`)
- `query_by_name(last_name: str, first_name: str) → list[DCAResult]`
  - Case-insensitive matching on both fields

**Column mapping from Excel:**
| Excel Column | DCAResult Field |
|---|---|
| `License Number` | `license_number` |
| `Org/Last Name` | `last_name` |
| `First Name` | `first_name` |
| `Middle Name` | `middle_name` |
| `License Type` | `license_type` |
| `License Status` | `license_status` |
| `Expiration Date` | `expiration_date` |
| `Original Issue Date` | `original_issue_date` |
| derived | `is_valid` |

**Phase 2b (future):** When DCA API becomes available, replace only the internals of `dca_reader.py`. `DCAResult` interface stays identical — pipeline unchanged, tests still pass.

---

## 🔄 Request Flow — Step by Step

### Flow 1: Cache Miss (first time lookup)
```
1. Client sends POST /verify { "npi": "1234567890" }
2. Nginx load balances to one of the FastAPI instances
3. FastAPI checks Redis — cache miss
4. FastAPI publishes to Kafka topic: verification_requested
5. NPI Fetcher Worker consumes event → hits NPI Registry API
6. DCA Reader Worker → queries DCA data source (Excel in Phase 2A, PostgreSQL in Phase 3+)
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
| Swappable Data Sources | DCAResult interface abstracts Excel → API swap |
| Dependency Direction | core/ layer prevents workers importing from api/ |

---

## 🏗️ Build Phases

### ✅ Phase 1 — Completed
- Project scaffolding
- NPI fetcher implementation (`workers/npi_fetcher.py`)
- Pydantic models (`NPIRecord`, `NPIAddress`, `NPITaxonomy`)
- Custom exceptions (`NPINotFoundError`, `NPIAPIError`, `NPIValidationError`)
- 23-test pytest suite passing
- `pytest.ini` configured with `pythonpath = .`
- `workers/__init__.py` created

### ✅ Phase 2A — Completed
- Refactored models into `core/` layer (correct dependency direction)
- `core/models.py` — all shared Pydantic models + exceptions
- `core/matching.py` — `MatchVerdict`, `MatchResult`
- `workers/dca_reader.py` — Excel-backed DCA lookup with pickle cache
- `workers/fuzzy_matcher.py` — RapidFuzz name matching, calibrated thresholds
- `tests/test_dca_reader.py` — 9 tests (NaN handling, case insensitivity, edge cases)
- `tests/test_fuzzy_matcher.py` — 3 tests (match tiers, batch, name builder)
- **35 total tests passing**

### 🔲 Phase 2b — DCA API Integration (future, when API access is available)
- Replace internal logic of `dca_reader.py` only
- `DCAResult` return model stays identical — pipeline unchanged
- Add `responses` mock tests for HTTP layer

### 🔲 Phase 3 — Docker Infrastructure
```yaml
# docker-compose.yml target
services:
  postgres, redis, kafka, zookeeper,
  fastapi-1, fastapi-2, nginx, workers
```
- Load DCA data from Excel into PostgreSQL
- Swap `dca_reader.py` internals to query PostgreSQL instead of Excel
- `DCAResult` interface unchanged — proves abstraction works
- Performance difference: pandas O(n) scan → PostgreSQL O(log n) indexed query

### 🔲 Phase 4 — FastAPI + Kafka Integration
- `POST /verify` endpoint
- Redis cache check
- Kafka producer on cache miss

### 🔲 Phase 5 — Worker Services
- NPI Fetcher Worker (Kafka consumer)
- DCA Reader Worker
- Fuzzy Matcher Worker
- Notification Worker

**Phase 5 fuzzy matching usage pattern:**
```python
from workers.fuzzy_matcher import fuzzy_match, build_full_name

npi_name = build_full_name(npi_record.first_name, None, npi_record.last_name)
dca_name = build_full_name(dca_result.first_name, dca_result.middle_name, dca_result.last_name)
result = fuzzy_match(npi_name, dca_name)
```

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
responses
locust
python-dotenv
pandas
openpyxl
xlrd        # kept for reference — original .xls from DCA source is unreadable
            # (HTML table disguised as .xls), use .xlsx exported from Google Sheets
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
- Before writing any code, always review design decisions together first
- Never assume scores, thresholds, or behavior — measure first

---

*Generated as a project continuity document — paste this into a new conversation window to resume the build with full context.*