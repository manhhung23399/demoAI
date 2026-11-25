import os
import json
import smtplib
import base64
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from rfq_graph import build_rfq_graph, initial_state

app = FastAPI(title="Digital Worker: Quote and Order")
graph_app = build_rfq_graph()


class EmailRequest(BaseModel):
    sender_email: str
    subject: str
    body: str


def send_reply(recipient: str, subject: str, body: str, attachment: str = "") -> dict:
    if os.getenv("EMAIL_MODE", "json").lower() == "json":
        out_dir = Path(os.getenv("REPLIES_OUT_DIR", "runtime/output/replies"))
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_recipient = "".join(c if c.isalnum() or c in "-_" else "_" for c in recipient)
        path = out_dir / f"reply_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_recipient}.json"
        reply = {"to": recipient, "subject": subject, "body": body,
                 "attachment_file": str(Path(attachment).resolve()) if attachment else ""}
        path.write_text(json.dumps(reply, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"email_sent": False, "reply_json_path": str(path.resolve())}
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    if not all([host, user, password]):
        return {"email_sent": False, "reply_json_path": ""}
    message = EmailMessage()
    message["From"] = os.getenv("SMTP_FROM", user)
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    if attachment:
        path = Path(attachment)
        message.add_attachment(path.read_bytes(), maintype="application",
                               subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               filename=path.name)
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        if os.getenv("SMTP_STARTTLS", "true").lower() == "true":
            smtp.starttls()
            smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(message)
    return {"email_sent": True, "reply_json_path": ""}


@app.get("/health")
def health():
    return {"status": "ok", "service": "digital-worker"}


@app.post("/start-flowable")
def start_flowable(payload: EmailRequest):
    """PAD submits the mock email here; this endpoint starts the Flowable BPMN instance."""
    endpoint = os.getenv(
        "FLOWABLE_PROCESS_API_URL",
        "http://localhost:8080/flowable-ui/process-api/runtime/process-instances",
    )
    process_body = {
        "processDefinitionKey": os.getenv("FLOWABLE_PROCESS_KEY", "emailDigitalWorker"),
        "businessKey": f"email-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        "variables": [{
            "name": "workerRequestBody",
            "type": "string",
            # Escaping non-ASCII characters keeps the Flowable HTTP task body ASCII;
            # the receiving JSON parser restores Vietnamese text from \uXXXX.
            "value": json.dumps({"sender_email": payload.sender_email,
                                 "subject": payload.subject,
                                 "body": payload.body}, ensure_ascii=True),
        }],
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    user, password = os.getenv("FLOWABLE_USER", "admin"), os.getenv("FLOWABLE_PASSWORD", "test")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(endpoint, data=json.dumps(process_body).encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return {"status": "STARTED", "process_instance_id": result.get("id"),
                    "business_key": process_body["businessKey"]}
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502,
                            detail=f"Flowable từ chối khởi chạy process ({exc.code}): {details}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Không gọi được Flowable REST: {exc}") from exc


@app.post("/process-email")
def process_email(payload: EmailRequest):
    result = graph_app.invoke(initial_state(str(payload.sender_email), payload.subject, payload.body))
    attachment_url = f"/quotes/{Path(result['excel_path']).name}" if result["excel_path"] else ""
    try:
        delivery = send_reply(str(payload.sender_email), f"Re: {payload.subject}",
                              result["reply_text"], result["excel_path"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Xử lý xong nhưng gửi email thất bại: {exc}") from exc
    return {
        "status": result["status"],
        "email_type": result["email_type"],
        "extracted_items": result["extracted_items"],
        "quoted_items": result["quoted_items"],
        "total_amount": result["total_amount"],
        "reply_text": result["reply_text"],
        **delivery,
        "excel_path": result["excel_path"],
        "attachment_url": attachment_url,
    }


@app.post("/process-rfq", include_in_schema=False)
def process_rfq(payload: EmailRequest):
    return process_email(payload)


@app.get("/quotes/{filename}")
def download_quote(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ")
    path = (Path(os.getenv("QUOTES_OUT_DIR", "runtime/output/quotes")) / filename).resolve()
    root = Path(os.getenv("QUOTES_OUT_DIR", "runtime/output/quotes")).resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy file báo giá")
    return FileResponse(path, filename=filename,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
