import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process

load_dotenv()


class ExtractedItem(BaseModel):
    name: str = Field(description="Tên sản phẩm khách yêu cầu")
    quantity: int = Field(ge=1, description="Số lượng sản phẩm")


class EmailExtractionResult(BaseModel):
    email_type: Literal["QUOTE", "ORDER", "OTHER"]
    items: list[ExtractedItem] = Field(default_factory=list)


class RFQState(TypedDict):
    sender_email: str
    subject: str
    body: str
    email_type: str
    extracted_items: list[dict]
    quoted_items: list[dict]
    total_amount: float
    excel_path: str
    reply_text: str
    status: str


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_items_node(state: RFQState) -> dict:
    model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    llm = ChatGoogleGenerativeAI(model=model_name, temperature=0)
    structured_llm = llm.with_structured_output(EmailExtractionResult)
    prompt = f"""
Phân loại email thành đúng một loại: QUOTE (yêu cầu báo giá sản phẩm),
ORDER (đặt/mua hàng), hoặc OTHER. Chỉ trích xuất items cho QUOTE.
Mỗi mặt hàng có tên và số lượng nguyên dương. Nếu không nêu số lượng thì hỏi
trong nội dung, không tự đoán. Phân biệt yêu cầu báo giá với hỏi tình trạng đơn cũ.

Subject: {state['subject']}
Body:
{state['body']}
""".strip()
    result: EmailExtractionResult = structured_llm.invoke([
        SystemMessage(content="Bạn phân loại email kinh doanh và trích xuất chính xác."),
        HumanMessage(content=prompt),
    ])
    return {
        "email_type": result.email_type,
        "extracted_items": [{"name": x.name, "quantity": x.quantity} for x in result.items],
    }


def match_and_calculate_node(state: RFQState) -> dict:
    products_path = os.getenv("PRODUCTS_PATH", "data/products.xlsx")
    df = pd.read_excel(products_path)
    required = {"name", "price", "code"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Catalog thiếu các cột: {', '.join(sorted(missing))}")
    df["_norm_name"] = df["name"].astype(str).apply(normalize_text)
    choices = df["_norm_name"].tolist()
    quoted_items, total_amount = [], 0.0
    for item in state["extracted_items"]:
        raw_name, qty = item["name"], int(item["quantity"])
        # Token-set scoring avoids WRatio ties between unrelated products that
        # share only a brand/number (e.g. Dell laptop vs Dell monitor).
        best = process.extractOne(
            normalize_text(raw_name), choices, scorer=fuzz.token_set_ratio
        )
        if best and best[1] >= int(os.getenv("PRODUCT_MATCH_THRESHOLD", "80")):
            row = df.iloc[best[2]]
            price = float(row["price"])
            subtotal = qty * price
            total_amount += subtotal
            unit = str(row["unit"]) if "unit" in df.columns else "Cái"
            quoted_items.append({"code": str(row["code"]), "name": str(row["name"]), "unit": unit,
                                 "quantity": qty, "price": price, "subtotal": subtotal,
                                 "matched": True, "score": round(float(best[1]), 1)})
        else:
            quoted_items.append({"code": "N/A", "name": raw_name, "unit": "Cái", "quantity": qty,
                                 "price": 0.0, "subtotal": 0.0, "matched": False,
                                 "score": round(float(best[1]), 1) if best else 0.0})
    return {"quoted_items": quoted_items, "total_amount": total_amount}


def export_excel_node(state: RFQState) -> dict:
    out_dir = Path(os.getenv("QUOTES_OUT_DIR", "runtime/output/quotes"))
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_sender = re.sub(r"[^a-zA-Z0-9_-]", "_", state["sender_email"])
    file_path = out_dir / f"BAO_GIA_{timestamp}_{safe_sender}.xlsx"
    rows = [{"Mã SP": x["code"], "Tên sản phẩm": x["name"], "ĐVT": x["unit"],
             "Số lượng": x["quantity"], "Đơn giá": x["price"], "Thành tiền": x["subtotal"],
             "Trạng thái đối chiếu": "Khớp catalog" if x["matched"] else "Không tìm thấy trong catalog"}
            for x in state["quoted_items"]]
    rows.append({"Mã SP": "", "Tên sản phẩm": "TỔNG CỘNG", "ĐVT": "", "Số lượng": "",
                 "Đơn giá": "", "Thành tiền": state["total_amount"], "Trạng thái đối chiếu": ""})
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="BaoGia")
        ws = writer.sheets["BaoGia"]
        for r in range(2, len(rows) + 2):
            ws[f"E{r}"].number_format = "#,##0"
            ws[f"F{r}"].number_format = "#,##0"
    return {"excel_path": str(file_path.resolve()), "reply_text": "Vui lòng xem báo giá trong file Excel đính kèm.",
            "status": "COMPLETED"}


def order_node(state: RFQState) -> dict:
    return {"reply_text": "OK, order done!", "status": "ORDER_RECEIVED"}


def other_node(state: RFQState) -> dict:
    return {"reply_text": "Email đã được tiếp nhận.", "status": "SKIPPED_OTHER"}


def route_email(state: RFQState) -> Literal["match_and_calculate", "order", "other"]:
    if state["email_type"] == "QUOTE" and state["extracted_items"]:
        return "match_and_calculate"
    if state["email_type"] == "ORDER":
        return "order"
    return "other"


def build_rfq_graph():
    graph = StateGraph(RFQState)
    for name, fn in [("extract", extract_items_node), ("match_and_calculate", match_and_calculate_node),
                     ("export_excel", export_excel_node), ("order", order_node), ("other", other_node)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", route_email)
    graph.add_edge("match_and_calculate", "export_excel")
    graph.add_edge("export_excel", END)
    graph.add_edge("order", END)
    graph.add_edge("other", END)
    return graph.compile()


def initial_state(sender_email: str, subject: str, body: str) -> RFQState:
    return {"sender_email": sender_email, "subject": subject, "body": body, "email_type": "OTHER",
            "extracted_items": [], "quoted_items": [], "total_amount": 0.0, "excel_path": "",
            "reply_text": "", "status": "PENDING"}


if __name__ == "__main__":
    app = build_rfq_graph()
    for email_file in sorted(Path("samples/emails").glob("*.json")):
        payload = json.loads(email_file.read_text(encoding="utf-8"))
        result = app.invoke(initial_state(**payload))
        print(f"{email_file.name}: {result['email_type']} -> {result['status']}")
        if result["excel_path"]:
            print("Excel:", result["excel_path"], "| Tổng:", f"{result['total_amount']:,.0f}")
