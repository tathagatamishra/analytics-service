# aianalytics-service

FastAPI analytics service — port **8084**

Reads `ai_usage_snapshots` (written every 6h by `aitools-service`) and exposes:
- KPI summary cards
- Daily usage timeseries
- Model & provider cost breakdown
- 30-day cost forecast (linear regression)
- Budget burn rate
- Cost anomaly detection (z-score)
- GitHub Copilot seat utilisation

---

## Local Setup

### 1. AWS SSM tunnel (same pattern as other services)

```bash
# Port 3311 — dedicated to aianalytics-service
aws ssm start-session \
  --target i-0a69e43bdf9fbe227 \
  --region ap-southeast-2 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"cr-dev-db.cfm0eagueep6.ap-southeast-2.rds.amazonaws.com\"],\"portNumber\":[\"3306\"],\"localPortNumber\":[\"3311\"]}"
```

### 2. Python environment

```bash
cd aianalytics-service
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Environment

```bash
cp .env.example .env
# Edit .env if your DB credentials differ
```

### 4. Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8084 --reload
```

Swagger UI: http://localhost:8084/docs  
Health: http://localhost:8084/health

---

## API Overview

All endpoints require a valid Cognito Bearer token (same pool as other services).  
The `org_id` is extracted automatically from `custom:org_id` in the JWT.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/analytics/summary` | KPI cards (cost, requests, tokens) |
| GET | `/api/analytics/daily` | Daily usage timeseries |
| GET | `/api/analytics/breakdown/models` | Cost by model |
| GET | `/api/analytics/breakdown/providers` | Cost by provider |
| GET | `/api/analytics/forecast` | 30-day cost forecast |
| GET | `/api/analytics/burn-rate` | Budget burn rate + overage projection |
| GET | `/api/analytics/anomalies` | Cost anomaly detection |
| GET | `/api/analytics/copilot/seats` | GitHub Copilot seat utilisation |

### Common query parameters

| Param | Default | Description |
|-------|---------|-------------|
| `start` | today − 29d | Period start date (YYYY-MM-DD) |
| `end` | today | Period end date (YYYY-MM-DD) |
| `provider` | *(all)* | `openai` \| `claude` \| `gemini` \| `github_copilot` |

---

## Architecture Notes

- **Read-only** — never writes to the database. All data is produced by `aitools-service`.
- **BINARY(16) UUIDs** — stored as raw bytes in MySQL; converted to UUID strings in responses.
- **Forecasting models** selected automatically based on data availability:
  - ≥ 14 days → Linear Regression
  - 7–13 days → Exponential Weighted Mean
  - < 7 days → Simple Daily Average
- **Anomaly detection** uses a rolling 7-day z-score window. Thresholds configurable per request.
- **No writes** → CORS allows only GET methods.

---

## Port Map (full stack)

| Service | Port | DB tunnel port |
|---------|------|----------------|
| auth-service | 8081 | 3309 |
| org-service | 8082 | 3308 |
| aitools-service | 8083 | 3310 |
| **aianalytics-service** | **8084** | **3311** |
