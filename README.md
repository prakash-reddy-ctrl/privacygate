# PrivacyGateAI

Privacy middleware that sits between your app and AI models.
Detects PII → masks it → calls AI → restores values → returns safe result.

## Quick Start

```bash
pip install fastapi uvicorn httpx python-dotenv
```

Set your AI provider key:
```bash
export ANTHROPIC_API_KEY=sk-...
# or
export OPENAI_API_KEY=sk-...
```

Start the server:
```bash
uvicorn api.server:app --reload --port 8000
```

## API Usage

### Full Pipeline (sanitize → AI → restore)
```bash
curl -X POST http://localhost:8000/v1/process \
  -H "x-api-key: YOUR_ANTHROPIC_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Summarize this contract for John Smith at john@acme.com, SSN 078-05-1120",
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514"
  }'
```

Response:
```json
{
  "session_id": "abc-123",
  "response": "Here is the summary for John Smith...",
  "entity_count": 3,
  "entity_types": ["EMAIL_ADDRESS", "US_SSN"],
  "model_used": "claude-sonnet-4-20250514",
  "provider": "anthropic"
}
```

### Sanitize Only
```bash
curl -X POST http://localhost:8000/v1/sanitize \
  -H "Content-Type: application/json" \
  -d '{"text": "Contact john@acme.com for details"}'
```

### Audit Log
```bash
curl http://localhost:8000/v1/audit/SESSION_ID
```

## Detected PII Types

| Type | Example |
|------|---------|
| EMAIL_ADDRESS | john@company.com |
| US_SSN | 078-05-1120 |
| CREDIT_CARD | 4532015112830366 |
| PHONE_NUMBER | +1 415-555-0172 |
| IP_ADDRESS | 192.168.1.1 |
| API_KEY | sk-abc123... |
| FINANCIAL_AMOUNT | $2.5 million |
| IBAN_CODE | GB29NWBK60161331926819 |
| URL_WITH_CREDS | https://user:pass@host |
| DATE_OF_BIRTH | DOB: 01/15/1990 |
| MEDICAL_ID | MRN: ABC123456 |

## Architecture

```
User/App
   │
   ▼
POST /v1/process
   │
   ├─ PrivacyEngine.sanitize(prompt)
   │     └─ Regex patterns detect + replace PII with [TYPE_N] tokens
   │
   ├─ AIGateway → Anthropic/OpenAI API (sees only sanitized text)
   │
   ├─ PrivacyEngine.restore(ai_response, entity_map)
   │     └─ Swap [TYPE_N] tokens back to original values
   │
   └─ Return restored response to user
```

## Project Structure

```
privacygate/
├── core/
│   ├── engine.py      # PII detection + masking engine
│   └── gateway.py     # AI provider gateway (Anthropic + OpenAI)
├── api/
│   └── server.py      # FastAPI REST server
├── tests/
│   └── test_engine.py # Core engine tests
└── README.md
```

## Roadmap

- [ ] spaCy NER integration for name/org detection
- [ ] Per-org custom policy rules
- [ ] Multi-turn session state (Redis)
- [ ] SOC 2 audit log export
- [ ] Dashboard UI
- [ ] Streaming response support
