import json
from pathlib import Path


sample_dir = Path(__file__).resolve().parents[1] / "samples" / "emails"
sample_dir.mkdir(parents=True, exist_ok=True)

samples = {
    "quote_test.json": {
        "sender_email": "quote.demo@example.com",
        "subject": "Yêu cầu báo giá màn hình và chuột",
        "body": "Báo giá giúp tôi 5 màn hình Dell 24 inch và 10 chuột Logitech G102.",
    },
    "order_test.json": {
        "sender_email": "order.demo@example.com",
        "subject": "Đặt hàng thiết bị văn phòng",
        "body": "Tôi muốn đặt 2 màn hình Dell P2422H. Vui lòng xác nhận đơn hàng.",
    },
    "quote_test_02.json": {
        "sender_email": "quote.02.demo@example.com",
        "subject": "Báo giá màn hình Dell và chuột Logitech",
        "body": "Vui lòng báo giá 3 màn hình Dell P2422H và 5 chuột Logitech G102.",
    },
    "quote_test_03.json": {
        "sender_email": "quote.03.demo@example.com",
        "subject": "Yêu cầu báo giá thiết bị",
        "body": "Cho tôi xin báo giá 2 màn hình Dell 24 inch cùng 4 chuột Logitech G102.",
    },
    "quote_test_04.json": {
        "sender_email": "quote.04.demo@example.com",
        "subject": "Xin báo giá 1 màn hình và 2 chuột",
        "body": "Báo giá giúp tôi 1 Dell P2422H và 2 Logitech G102, ghi rõ đơn giá từng mặt hàng.",
    },
    "order_test_02.json": {
        "sender_email": "order.02.demo@example.com",
        "subject": "Đặt mua màn hình Dell P2422H",
        "body": "Tôi xác nhận đặt mua 3 màn hình Dell P2422H. Nhờ xử lý đơn hàng này.",
    },
    "order_test_03.json": {
        "sender_email": "order.03.demo@example.com",
        "subject": "Đơn hàng chuột Logitech",
        "body": "Tôi muốn đặt 10 chuột Logitech G102. Vui lòng ghi nhận đơn hàng.",
    },
    "order_test_04.json": {
        "sender_email": "order.04.demo@example.com",
        "subject": "Đặt hàng thiết bị văn phòng",
        "body": "Đặt giúp tôi 2 màn hình Dell và 5 chuột Logitech để giao trong tuần này.",
    },
}

for filename, email in samples.items():
    path = sample_dir / filename
    path.write_text(json.dumps(email, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Created {path}")
