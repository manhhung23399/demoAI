# Digital Worker: Quote / Order

## Project layout

```text
BAXTesting/
├── api_server.py                 # FastAPI endpoints and Flowable bridge
├── rfq_graph.py                  # LangGraph classification, matching, Excel
├── .env                          # Local settings and API key (do not share)
├── .env.example                  # Safe configuration template
├── data/
│   └── products.xlsx             # Product catalog
├── flowable/
│   └── email_worker.bpmn20.xml   # Flowable process definition
├── samples/
│   └── emails/                   # Reusable Quote and Order JSON examples
├── runtime/
│   ├── inbox/                    # PAD watches this folder
│   ├── processed/                # Successfully handled emails
│   ├── failed/                   # Failed emails for inspection
│   ├── output/quotes/            # Generated Excel quotations
│   ├── output/replies/           # Mock email responses (JSON)
│   └── logs/                     # Optional local worker logs
└── scripts/
    └── create_email_samples.py   # Regenerates the sample JSON emails
```

Files created while running the demo belong under `runtime/`. The reusable inputs under `samples/emails/` are not watched by PAD.

## What each part does

- **Power Automate Desktop** reads new JSON files from the inbox and starts a Flowable process.
- **Flowable** runs the deployed `emailDigitalWorker` BPMN process and calls the Python worker.
- **Python + LangGraph + Gemini** classifies each email, extracts Quote items, matches them to the catalog, calculates totals, and creates a reply.
- **Email mode `json`** writes a JSON representation of the reply. It does not send a real email. Quote replies reference the generated Excel file.

## Email input

Each email file must be a UTF-8 JSON object with these fields:

```json
{
  "sender_email": "quote.demo@example.com",
  "subject": "Yêu cầu báo giá",
  "body": "Báo giá giúp tôi 5 màn hình Dell 24 inch và 10 chuột Logitech G102."
}
```

Ready-to-use examples:

- `samples/emails/quote_test.json`
- `samples/emails/order_test.json`

Copy a sample to `runtime/inbox/` using a new filename when testing PAD.

## Configure and run Python

Set the local values in `.env`. Keep the actual API key in `.env`, not in shared files. Important paths are:

```dotenv
PRODUCTS_PATH=data/products.xlsx
QUOTES_OUT_DIR=runtime/output/quotes
REPLIES_OUT_DIR=runtime/output/replies
EMAIL_MODE=json
FLOWABLE_PROCESS_KEY=emailDigitalWorker
FLOWABLE_PROCESS_API_URL=http://localhost:8080/flowable-ui/process-api/runtime/process-instances
```

From the project root, start the worker:

```powershell
uv run --python 3.12 --with fastapi --with uvicorn --with pandas --with openpyxl --with python-dotenv --with langchain-core --with langchain-google-genai --with langgraph --with pydantic --with rapidfuzz uvicorn api_server:app --host 0.0.0.0 --port 8000
```

Check `http://localhost:8000/health`; it should return `{"status":"ok","service":"digital-worker"}`.

## Configure Power Automate Desktop

The existing desktop flow must use these folder paths:

- **Get files in folder:** `D:\BAXTesting\runtime\inbox`, filter `*.json`
- **Successful files:** `D:\BAXTesting\runtime\processed`
- **Failed files:** `D:\BAXTesting\runtime\failed`

Structure the flow as:

```text
Loop condition: 1 = 1
    Get files in folder
    For each CurrentItem in Files
        Read text from file (CurrentItem) → FileContents
        Invoke web service
        If StatusCode = 200
            Move CurrentItem to runtime/processed
        Else
            Show WebServiceResponse
            Move CurrentItem to runtime/failed
        End
    End
    Wait 5 seconds
End
```

Configure **Invoke web service**:

- URL: `http://localhost:8000/start-flowable`
- Method: `POST`
- Accept: `application/json`
- Content type: `application/json`
- Request body: insert the **FileContents** variable with the variable picker. The request must contain the raw JSON object, not a quoted JSON string or an unexpanded placeholder.

The loop runs continuously while PAD is running. Stop it with PAD's Stop button.

## Flowable

The process definition is `flowable/email_worker.bpmn20.xml`, process key `emailDigitalWorker`. It is already deployed in the current Docker Flowable instance as version 1. The process HTTP task calls `http://host.docker.internal:8000/process-email` so the container can reach the Python worker on Windows.

For a new deployment, upload `flowable/email_worker.bpmn20.xml` to:

```text
POST http://localhost:8080/flowable-ui/process-api/repository/deployments
```

## Outputs and cleanup

- Quote Excel files: `runtime/output/quotes/`
- Mock reply JSON files: `runtime/output/replies/`
- Successfully handled input files: `runtime/processed/`
- Failed input files: `runtime/failed/`
- Reusable test inputs: `samples/emails/`

To reset a demo, clear the contents of `runtime/inbox`, `runtime/processed`, `runtime/failed`, and `runtime/output`. Keep `samples/emails`, `data/products.xlsx`, source code, and `.env`.
