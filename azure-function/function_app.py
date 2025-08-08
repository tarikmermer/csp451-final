import os
import json
import requests
from datetime import datetime
import azure.functions as func
from pydantic import BaseModel, ValidationError

# Configuration
SUPPLIER_API_URL = os.getenv("SUPPLIER_API_URL", "http://localhost:8001")
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "3"))
TIMEOUT_SECONDS = int(os.getenv("TIMEOUT_SECONDS", "30"))

app = func.FunctionApp()

class InventoryEvent(BaseModel):
    event_id: str
    correlation_id: str
    event_type: str
    timestamp: str
    product_id: str
    product_name: str
    current_stock: int
    threshold: int
    supplier_id: str
    suggested_order_quantity: int

class SupplierOrderRequest(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    supplier_id: str
    priority: str = "normal"
    correlation_id: str

def call_supplier_api(order_request: SupplierOrderRequest, correlation_id: str):
    url = f"{SUPPLIER_API_URL}/order"
    headers = {
        "Content-Type": "application/json",
        "X-Correlation-ID": correlation_id
    }
    
    payload = order_request.model_dump()
    
    print(f"Calling Supplier API: {url}, Correlation: {correlation_id}")
    
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS)
            
            if response.status_code == 200:
                response_data = response.json()
                print(f"Supplier API success: Order {response_data.get('order_id')}")
                return response_data
            else:
                print(f"Supplier API failed: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            print(f"Supplier API exception: {e}")
            
        if attempt < RETRY_ATTEMPTS:
            import time
            time.sleep(2 ** attempt)
    
    raise Exception(f"Failed to call Supplier API after {RETRY_ATTEMPTS} attempts")

@app.queue_trigger(
    arg_name="msg", 
    queue_name="inventory-events",
    connection="AzureWebJobsStorage"
)
def inventory_event_processor(msg: func.QueueMessage) -> None:
    try:
        message_body = msg.get_body().decode('utf-8')
        print(f"Processing inventory event: {message_body}")
        
        event_data = json.loads(message_body)
        inventory_event = InventoryEvent(**event_data)
        
        correlation_id = inventory_event.correlation_id
        
        supplier_order = SupplierOrderRequest(
            product_id=inventory_event.product_id,
            product_name=inventory_event.product_name,
            quantity=inventory_event.suggested_order_quantity,
            supplier_id=inventory_event.supplier_id,
            priority="urgent" if inventory_event.current_stock <= inventory_event.threshold // 2 else "normal",
            correlation_id=correlation_id
        )
        
        supplier_response = call_supplier_api(supplier_order, correlation_id)
        
        print(f"Event processed successfully: {inventory_event.event_id}, Order: {supplier_response.get('order_id')}")
        
    except Exception as e:
        print(f"Function execution failed: {e}")
        raise

@app.route(route="health", auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    health_status = {
        "service": "Inventory Event Processor",
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "configuration": {
            "supplier_api_url": SUPPLIER_API_URL,
            "retry_attempts": RETRY_ATTEMPTS,
            "timeout_seconds": TIMEOUT_SECONDS
        }
    }
    
    return func.HttpResponse(
        json.dumps(health_status),
        status_code=200,
        mimetype="application/json"
    )

@app.route(route="test", auth_level=func.AuthLevel.ANONYMOUS)
def test_function(req: func.HttpRequest) -> func.HttpResponse:
    try:
        test_event = {
            "event_id": "test-event-001",
            "correlation_id": "test-correlation-001",
            "event_type": "stock_below_threshold",
            "timestamp": datetime.utcnow().isoformat(),
            "product_id": "prod-001",
            "product_name": "Test Product",
            "current_stock": 2,
            "threshold": 10,
            "supplier_id": "supp-001",
            "suggested_order_quantity": 20
        }
        
        inventory_event = InventoryEvent(**test_event)
        
        supplier_order = SupplierOrderRequest(
            product_id=inventory_event.product_id,
            product_name=inventory_event.product_name,
            quantity=inventory_event.suggested_order_quantity,
            supplier_id=inventory_event.supplier_id,
            priority="normal",
            correlation_id=inventory_event.correlation_id
        )
        
        supplier_response = call_supplier_api(supplier_order, inventory_event.correlation_id)
        
        response_data = {
            "status": "success",
            "message": "Test event processed successfully",
            "test_event": test_event,
            "supplier_response": supplier_response,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return func.HttpResponse(
            json.dumps(response_data),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        error_response = {
            "status": "error",
            "message": "Test function execution failed",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return func.HttpResponse(
            json.dumps(error_response),
            status_code=500,
            mimetype="application/json"
        )