import json
from fastapi.testclient import TestClient
from secure_app import app
from sample_data import sample_bytes

def test_local_workflow():
    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert c.get("/health").status_code == 200
    files = {"current_store": ("store.csv", sample_bytes("store"), "text/csv"), "supplier": ("supplier.csv", sample_bytes("supplier"), "text/csv")}
    assert c.post("/preview", files=files).status_code == 200
    data = {"store_mapping": json.dumps({"sku": "SKU", "current_cost": "Cost per item", "selling_price": "Price"}), "supplier_mapping": json.dumps({"supplier_sku": "Item No", "new_cost": "Wholesale price"})}
    for _ in range(2):
        response = c.post("/analyze", files=files, data=data)
        assert response.status_code == 200
        assert len(response.json()["rows"]) == 50
    assert c.post("/preview", files=files, headers={"Origin": "https://example.com"}).status_code == 403
