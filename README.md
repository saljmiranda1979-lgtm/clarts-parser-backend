# CLARTS Parser API

Backend parser for the CLARTS dashboard.

## Render settings

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

## Endpoint

```text
POST /api/parse-report
```

Upload the PDF with the multipart form field named `pdf`.
