# SmartRetail Supplier Sync - Complete Walkthrough Guide

## 🎯 Overview

This guide provides a complete step-by-step walkthrough for deploying and demonstrating the SmartRetail Supplier Sync system - an event-driven inventory coordination platform built with Azure serverless services, Docker containers, and message queuing.

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Setup](#project-setup)
3. [Azure Authentication](#azure-authentication)
4. [Azure Resources Setup](#azure-resources-setup)
5. [Service Deployment](#service-deployment)
6. [System Testing](#system-testing)
7. [Live Demo Walkthrough](#live-demo-walkthrough)
8. [Monitoring and Troubleshooting](#monitoring-and-troubleshooting)
9. [Architecture Deep Dive](#architecture-deep-dive)

---

## Prerequisites

Before starting, ensure you have:

- **Azure CLI** installed and configured
- **Docker** and **Docker Compose** installed locally
- **Python 3.11+** for local development
- **Git** for version control
- **Azure subscription** with appropriate permissions
- **jq** for JSON parsing (optional but recommended)

### Install Required Tools (macOS)

```bash
# Install Azure CLI
brew install azure-cli

# Install Azure Functions Core Tools
brew tap azure/functions
brew install azure-functions-core-tools@4

# Install jq for JSON processing
brew install jq
```

---

## Project Setup

### 1. Initialize Project Structure

```bash
# Create project directory
mkdir smartretail-supplier-sync
cd smartretail-supplier-sync

# Create project structure
mkdir -p backend supplier-api azure-function docker docs scripts
```

### 2. Setup Python Virtual Environment

```bash
# Create virtual environment setup script
cat > scripts/setup-venv.sh << 'EOF'
#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"

echo "🚀 Setting up SmartRetail Supplier Sync Python Environment..."

# Create virtual environment
python3 -m venv "$VENV_DIR"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Upgrade pip
pip install --upgrade pip

echo "🎉 Virtual environment setup complete!"
EOF

chmod +x scripts/setup-venv.sh
./scripts/setup-venv.sh
```

**Expected Output:**
```
🚀 Setting up SmartRetail Supplier Sync Python Environment...
🎉 Virtual environment setup complete!
```

---

## Azure Authentication

### 3. Login to Azure

```bash
az login
```

**Expected Output:**
```
A web browser has been opened at https://login.microsoftonline.com/...
Please continue the login in the web browser.

[Tenant and subscription selection]
No     Subscription name                  Subscription ID                       Tenant
-----  ---------------------------------  ------------------------------------  --------------
[1] *  Your Subscription Name             xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx  Your Tenant

Tenant: Your Tenant
Subscription: Your Subscription Name (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
```

### 4. Verify Available Resources

```bash
# List available resource groups
az group list --output table
```

**Expected Output:**
```
Name                Location       Status
------------------  -------------  ---------
Student-RG-1739859  canadaeast     Succeeded
Student-RG-1234567  canadacentral  Succeeded
```

---

## Azure Resources Setup

### 5. Create Storage Account and Queue

```bash
# Set variables (adjust based on your resource group)
RESOURCE_GROUP="Student-RG-1739859"
STORAGE_ACCOUNT="tmermerfinalsa"

# Get storage account connection string
STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
    --name $STORAGE_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --query connectionString \
    --output tsv)

echo "Storage connection string obtained"

# Create inventory events queue
az storage queue create \
    --name "inventory-events" \
    --connection-string "$STORAGE_CONNECTION_STRING"
```

**Expected Output:**
```
Command group 'storage queue' is in preview and under development.
{
  "created": true
}
```

### 6. Create Azure Function App

```bash
# Create Linux-based Python Function App
az functionapp create \
    --resource-group $RESOURCE_GROUP \
    --consumption-plan-location canadacentral \
    --runtime python \
    --runtime-version 3.11 \
    --functions-version 4 \
    --name tmermerfunctionapp \
    --storage-account $STORAGE_ACCOUNT \
    --os-type Linux
```

**Expected Output:**
```
Your Linux function app 'tmermerfunctionapp', that uses a consumption plan has been successfully created
{
  "defaultHostName": "tmermerfunctionapp-gnhmbxbkdshpa7gm.canadacentral-01.azurewebsites.net",
  "kind": "functionapp,linux",
  "location": "canadacentral",
  ...
}
```

### 7. Configure Function App Settings

```bash
# Get VM IP (adjust VM name as needed)
VM_IP=$(az vm show --resource-group $RESOURCE_GROUP --name your-vm-name --show-details --query publicIps --output tsv)

# Configure Function App
az functionapp config appsettings set \
    --name tmermerfunctionapp \
    --resource-group $RESOURCE_GROUP \
    --settings \
        "AzureWebJobsStorage=$STORAGE_CONNECTION_STRING" \
        "SUPPLIER_API_URL=http://$VM_IP:8001" \
        "RETRY_ATTEMPTS=3" \
        "TIMEOUT_SECONDS=30"
```

---

## Service Deployment

### 8. Create Backend Service

Create the backend service that handles inventory and emits events:

```bash
# Create backend requirements
cat > backend/requirements.txt << 'EOF'
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
azure-storage-queue==12.8.0
python-dotenv==1.0.0
EOF

# Create backend main.py
cat > backend/main.py << 'EOF'
import os
import json
import uuid
from datetime import datetime
from typing import List
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from azure.storage.queue import QueueClient

app = FastAPI(title='SmartRetail Backend')

# Configuration
AZURE_STORAGE_CONNECTION_STRING = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
QUEUE_NAME = 'inventory-events'
STOCK_THRESHOLD = int(os.getenv('STOCK_THRESHOLD', '10'))

# Initialize queue client
queue_client = None
if AZURE_STORAGE_CONNECTION_STRING:
    try:
        queue_client = QueueClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING, QUEUE_NAME)
    except:
        pass

class Product(BaseModel):
    id: str
    name: str
    stock_quantity: int
    price: float
    supplier_id: str

class ProductUpdate(BaseModel):
    stock_quantity: int

# Demo products
products_db = {
    'prod-001': Product(id='prod-001', name='Wireless Headphones', stock_quantity=5, price=99.99, supplier_id='supp-001'),
    'prod-002': Product(id='prod-002', name='Bluetooth Speaker', stock_quantity=15, price=49.99, supplier_id='supp-002'),
    'prod-003': Product(id='prod-003', name='USB-C Cable', stock_quantity=3, price=12.99, supplier_id='supp-001'),
}

async def emit_inventory_event(product: Product, correlation_id: str = None):
    if not queue_client:
        print(f'Queue not configured - event would be sent for {product.id}')
        return
    
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    
    event = {
        'event_id': str(uuid.uuid4()),
        'correlation_id': correlation_id,
        'event_type': 'stock_below_threshold',
        'timestamp': datetime.utcnow().isoformat(),
        'product_id': product.id,
        'product_name': product.name,
        'current_stock': product.stock_quantity,
        'threshold': STOCK_THRESHOLD,
        'supplier_id': product.supplier_id,
        'suggested_order_quantity': max(STOCK_THRESHOLD * 2 - product.stock_quantity, STOCK_THRESHOLD)
    }
    
    try:
        queue_client.send_message(json.dumps(event))
        print(f'Event emitted: {correlation_id}')
    except Exception as e:
        print(f'Failed to emit event: {e}')

@app.get('/')
async def root():
    return {'service': 'SmartRetail Backend', 'status': 'running', 'timestamp': datetime.utcnow().isoformat()}

@app.get('/products', response_model=List[Product])
async def get_products():
    return list(products_db.values())

@app.get('/products/{product_id}', response_model=Product)
async def get_product(product_id: str):
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail='Product not found')
    return products_db[product_id]

@app.put('/products/{product_id}/stock', response_model=Product)
async def update_product_stock(product_id: str, update: ProductUpdate, background_tasks: BackgroundTasks):
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail='Product not found')
    
    correlation_id = str(uuid.uuid4())
    product = products_db[product_id]
    product.stock_quantity = update.stock_quantity
    
    if update.stock_quantity < STOCK_THRESHOLD:
        background_tasks.add_task(emit_inventory_event, product, correlation_id)
    
    return product

@app.post('/products/{product_id}/simulate-sale')
async def simulate_sale(product_id: str, quantity: int = 1, background_tasks: BackgroundTasks = None):
    if product_id not in products_db:
        raise HTTPException(status_code=404, detail='Product not found')
    
    product = products_db[product_id]
    if product.stock_quantity < quantity:
        raise HTTPException(status_code=400, detail='Insufficient stock')
    
    correlation_id = str(uuid.uuid4())
    product.stock_quantity -= quantity
    
    below_threshold = product.stock_quantity < STOCK_THRESHOLD
    if below_threshold and background_tasks:
        background_tasks.add_task(emit_inventory_event, product, correlation_id)
    
    return {
        'message': 'Sale completed',
        'product_id': product_id,
        'quantity_sold': quantity,
        'remaining_stock': product.stock_quantity,
        'below_threshold': below_threshold,
        'correlation_id': correlation_id
    }

@app.get('/queue/status')
async def get_queue_status():
    if not queue_client:
        return {'error': 'Queue client not initialized'}
    try:
        properties = queue_client.get_queue_properties()
        return {'queue_name': QUEUE_NAME, 'approximate_message_count': properties.approximate_message_count}
    except Exception as e:
        return {'error': str(e)}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
EOF
```

### 9. Create Supplier API Service

```bash
# Create supplier API requirements
cat > supplier-api/requirements.txt << 'EOF'
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
python-dotenv==1.0.0
EOF

# Create supplier API main.py
cat > supplier-api/main.py << 'EOF'
import os
import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

app = FastAPI(title='Supplier API')

SUPPLIER_ID = os.getenv('SUPPLIER_ID', 'ACME-SUPPLIER-001')

class OrderRequest(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    supplier_id: str
    priority: str = 'normal'
    correlation_id: str = None

class OrderResponse(BaseModel):
    order_id: str
    status: str
    estimated_delivery_days: int
    total_cost: float
    confirmation_number: str
    correlation_id: str
    processed_at: str
    supplier_id: str

# Simulated catalog
supplier_catalog = {
    'prod-001': {'name': 'Wireless Headphones', 'unit_cost': 45.00, 'delivery_days': 3},
    'prod-002': {'name': 'Bluetooth Speaker', 'unit_cost': 25.00, 'delivery_days': 2},
    'prod-003': {'name': 'USB-C Cable', 'unit_cost': 5.00, 'delivery_days': 1},
    'default': {'name': 'Generic Product', 'unit_cost': 10.00, 'delivery_days': 5},
}

order_history = {}

@app.get('/')
async def root():
    return {
        'service': 'Supplier API',
        'supplier_id': SUPPLIER_ID,
        'status': 'operational',
        'timestamp': datetime.utcnow().isoformat()
    }

@app.post('/order', response_model=OrderResponse)
async def process_order(order: OrderRequest, x_correlation_id: str = Header(None, alias='X-Correlation-ID')):
    correlation_id = x_correlation_id or order.correlation_id or str(uuid.uuid4())
    order_id = f'ORD-{datetime.utcnow().strftime("%Y%m%d")}-{str(uuid.uuid4())[:8].upper()}'
    
    product_info = supplier_catalog.get(order.product_id, supplier_catalog['default'])
    unit_cost = product_info['unit_cost']
    total_cost = unit_cost * order.quantity
    delivery_days = product_info['delivery_days']
    
    if order.priority == 'urgent':
        delivery_days = max(1, delivery_days - 1)
        total_cost *= 1.2
    elif order.priority == 'low':
        delivery_days += 2
        total_cost *= 0.95
    
    confirmation_number = f'CONF-{str(uuid.uuid4())[:12].upper()}'
    
    response = OrderResponse(
        order_id=order_id,
        status='confirmed',
        estimated_delivery_days=delivery_days,
        total_cost=round(total_cost, 2),
        confirmation_number=confirmation_number,
        correlation_id=correlation_id,
        processed_at=datetime.utcnow().isoformat(),
        supplier_id=SUPPLIER_ID
    )
    
    order_history[order_id] = {
        'request': order.model_dump(),
        'response': response.model_dump(),
        'timestamp': datetime.utcnow().isoformat()
    }
    
    print(f'Order processed: {order_id}, Correlation: {correlation_id}')
    return response

@app.get('/orders/{order_id}')
async def get_order_status(order_id: str):
    if order_id not in order_history:
        raise HTTPException(status_code=404, detail='Order not found')
    return order_history[order_id]

@app.get('/orders')
async def get_recent_orders(limit: int = 10):
    recent_orders = list(order_history.values())[-limit:]
    return {'orders': recent_orders, 'total_count': len(order_history)}

@app.get('/catalog')
async def get_catalog():
    return {'supplier_id': SUPPLIER_ID, 'catalog': supplier_catalog, 'currency': 'CAD'}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8001)
EOF
```

### 10. Create Azure Function

```bash
# Create Azure Function requirements
cat > azure-function/requirements.txt << 'EOF'
azure-functions==1.18.0
azure-storage-queue==12.8.0
requests==2.31.0
pydantic==2.5.0
EOF

# Create Azure Function host.json
cat > azure-function/host.json << 'EOF'
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": {
        "isEnabled": true,
        "excludedTypes": "Request"
      }
    }
  },
  "extensionBundle": {
    "id": "Microsoft.Azure.Functions.ExtensionBundle",
    "version": "[3.*, 4.0.0)"
  },
  "functionTimeout": "00:05:00"
}
EOF

# Create Azure Function main code
cat > azure-function/function_app.py << 'EOF'
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
EOF
```

### 11. Deploy Azure Function

```bash
cd azure-function
func azure functionapp publish tmermerfunctionapp --python
cd ..
```

**Expected Output:**
```
Getting site publishing info...
Creating archive for current directory...
Performing remote build for functions project.
Remote build succeeded!
Functions in tmermerfunctionapp:
    health_check - [httpTrigger]
        Invoke url: https://tmermerfunctionapp-gnhmbxbkdshpa7gm.canadacentral-01.azurewebsites.net/api/health
    inventory_event_processor - [queueTrigger]
    test_function - [httpTrigger]
        Invoke url: https://tmermerfunctionapp-gnhmbxbkdshpa7gm.canadacentral-01.azurewebsites.net/api/test
```

### 12. Deploy Services to VM

```bash
# Create environment file
cat > .env << 'EOF'
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=tmermerfinalsa;AccountKey=/Iy8521zh6Y1FHYoV8k2J6f5ftg4IAZ5i4nkMtRoEyYPLqEujlQtzlZafKoCSbDzDt5SmqY+1nXD+ASt7E350Q==;EndpointSuffix=core.windows.net
STOCK_THRESHOLD=10
SUPPLIER_API_URL=http://4.205.242.245:8001
BACKEND_API_URL=http://4.205.242.245:8000
RETRY_ATTEMPTS=3
TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
EOF

# Update network security group rules for VM
az network nsg rule create \
    --resource-group $RESOURCE_GROUP \
    --nsg-name your-vm-nsg \
    --name "Backend-API" \
    --protocol tcp \
    --priority 370 \
    --destination-port-range 8000 \
    --access allow

az network nsg rule create \
    --resource-group $RESOURCE_GROUP \
    --nsg-name your-vm-nsg \
    --name "Supplier-API" \
    --protocol tcp \
    --priority 380 \
    --destination-port-range 8001 \
    --access allow

# Deploy services using Azure CLI run-command
# (Services are deployed directly on VM using Docker)
```

---

## System Testing

### 13. Test Service Health

```bash
# Test Backend API
curl http://4.205.242.245:8000/
```

**Expected Output:**
```json
{
  "service": "SmartRetail Backend",
  "status": "running",
  "timestamp": "2025-08-07T18:07:27.153201"
}
```

```bash
# Test Supplier API
curl http://4.205.242.245:8001/
```

**Expected Output:**
```json
{
  "service": "Supplier API",
  "supplier_id": "ACME-SUPPLIER-001",
  "status": "operational",
  "timestamp": "2025-08-07T18:07:34.010725"
}
```

```bash
# Test Azure Function
curl https://tmermerfunctionapp-gnhmbxbkdshpa7gm.canadacentral-01.azurewebsites.net/api/health
```

**Expected Output:**
```json
{
  "service": "Inventory Event Processor",
  "status": "healthy",
  "timestamp": "2025-08-07T18:07:43.156684",
  "configuration": {
    "supplier_api_url": "http://4.205.242.245:8001",
    "retry_attempts": 3,
    "timeout_seconds": 30
  }
}
```

---

## Live Demo Walkthrough

### 14. Complete End-to-End Demonstration

#### Step 1: Show Current Inventory

```bash
echo "=== SmartRetail Demo ==="
echo "1. Checking current products:"
curl -s http://4.205.242.245:8000/products | jq '.'
```

**Expected Output:**
```json
[
  {
    "id": "prod-001",
    "name": "Wireless Headphones",
    "stock_quantity": 5,
    "price": 99.99,
    "supplier_id": "supp-001"
  },
  {
    "id": "prod-002",
    "name": "Bluetooth Speaker",
    "stock_quantity": 15,
    "price": 49.99,
    "supplier_id": "supp-002"
  },
  {
    "id": "prod-003",
    "name": "USB-C Cable",
    "stock_quantity": 3,
    "price": 12.99,
    "supplier_id": "supp-001"
  }
]
```

#### Step 2: Trigger Inventory Event

```bash
echo "2. Simulating sale to trigger low stock event:"
curl -s -X POST "http://4.205.242.245:8000/products/prod-001/simulate-sale?quantity=3" | jq '.'
```

**Expected Output:**
```json
{
  "message": "Sale completed",
  "product_id": "prod-001",
  "quantity_sold": 3,
  "remaining_stock": 2,
  "below_threshold": true,
  "correlation_id": "285ed091-6ee8-4574-a141-c045ae322786"
}
```

#### Step 3: Verify Event Queuing

```bash
echo "3. Checking queue status:"
curl -s http://4.205.242.245:8000/queue/status | jq '.'
```

**Expected Output:**
```json
{
  "queue_name": "inventory-events",
  "approximate_message_count": 1
}
```

#### Step 4: Verify Event Processing

```bash
echo "4. Testing Azure Function directly:"
curl -s https://tmermerfunctionapp-gnhmbxbkdshpa7gm.canadacentral-01.azurewebsites.net/api/test | jq '.'
```

**Expected Output:**
```json
{
  "status": "success",
  "message": "Test event processed successfully",
  "test_event": {
    "event_id": "test-event-001",
    "correlation_id": "test-correlation-001",
    "event_type": "stock_below_threshold",
    "timestamp": "2025-08-07T18:08:31.781711",
    "product_id": "prod-001",
    "product_name": "Test Product",
    "current_stock": 2,
    "threshold": 10,
    "supplier_id": "supp-001",
    "suggested_order_quantity": 20
  },
  "supplier_response": {
    "order_id": "ORD-20250807-96625DA0",
    "status": "confirmed",
    "estimated_delivery_days": 3,
    "total_cost": 900.0,
    "confirmation_number": "CONF-80D41C2D-7D4",
    "correlation_id": "test-correlation-001",
    "processed_at": "2025-08-07T18:08:31.806345",
    "supplier_id": "ACME-SUPPLIER-001"
  },
  "timestamp": "2025-08-07T18:08:31.815543"
}
```

#### Step 5: Verify Supplier Orders

```bash
echo "5. Checking all supplier orders:"
curl -s http://4.205.242.245:8001/orders | jq '.'
```

**Expected Output:**
```json
{
  "orders": [
    {
      "request": {
        "product_id": "prod-001",
        "product_name": "Test Product",
        "quantity": 20,
        "supplier_id": "supp-001",
        "priority": "normal",
        "correlation_id": "test-correlation-001"
      },
      "response": {
        "order_id": "ORD-20250807-96625DA0",
        "status": "confirmed",
        "estimated_delivery_days": 3,
        "total_cost": 900.0,
        "confirmation_number": "CONF-80D41C2D-7D4",
        "correlation_id": "test-correlation-001",
        "processed_at": "2025-08-07T18:08:31.806345",
        "supplier_id": "ACME-SUPPLIER-001"
      },
      "timestamp": "2025-08-07T18:08:31.806381"
    }
  ],
  "total_count": 1
}
```

---

## Monitoring and Troubleshooting

### 15. Azure Portal Monitoring

1. **Navigate to Azure Portal**: https://portal.azure.com
2. **Find Function App**: Search for "tmermerfunctionapp"
3. **View Function Executions**: Go to Functions → Monitor
4. **Check Logs**: View live logs and execution history
5. **Monitor Storage Queue**: Check queue depth and message flow

### 16. Common Troubleshooting Commands

```bash
# Check VM status
az vm show --resource-group $RESOURCE_GROUP --name your-vm-name --query powerState

# Restart VM if needed
az vm restart --resource-group $RESOURCE_GROUP --name your-vm-name

# Check Docker services on VM
az vm run-command invoke \
    --resource-group $RESOURCE_GROUP \
    --name your-vm-name \
    --command-id RunShellScript \
    --scripts "cd /home/azureuser/smartretail && sudo docker-compose ps"

# View Docker logs
az vm run-command invoke \
    --resource-group $RESOURCE_GROUP \
    --name your-vm-name \
    --command-id RunShellScript \
    --scripts "cd /home/azureuser/smartretail && sudo docker-compose logs --tail=50"
```

### 17. Performance Testing

```bash
# Test multiple concurrent sales
for i in {1..5}; do
  curl -s -X POST "http://4.205.242.245:8000/products/prod-002/simulate-sale?quantity=2" &
done
wait

# Check resulting queue depth
curl -s http://4.205.242.245:8000/queue/status | jq '.'

# Monitor supplier orders
curl -s http://4.205.242.245:8001/orders | jq '.total_count'
```

---

## Architecture Deep Dive

### Event Flow Diagram

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   SmartRetail   │    │  Azure Storage  │    │ Azure Function  │    │  Supplier API   │
│    Backend      │───▶│     Queue       │───▶│   Subscriber    │───▶│  Microservice   │
│   (Port 8000)   │    │ (inventory-     │    │    (Python)     │    │   (Port 8001)   │
│                 │    │  events)        │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Key Components

1. **SmartRetail Backend**
   - **Purpose**: Inventory management and event emission
   - **Technology**: FastAPI, Python 3.11
   - **Responsibilities**: Product CRUD, stock monitoring, event publishing

2. **Azure Storage Queue**
   - **Purpose**: Reliable message delivery
   - **Technology**: Azure Storage Queue service
   - **Features**: At-least-once delivery, scalable, durable

3. **Azure Function**
   - **Purpose**: Event processing and orchestration
   - **Technology**: Python Azure Functions v4
   - **Trigger**: Queue trigger on inventory-events

4. **Supplier API**
   - **Purpose**: Order processing simulation
   - **Technology**: FastAPI, Python 3.11
   - **Features**: Order confirmation, pricing, delivery estimation

### Correlation ID Tracing

Every operation generates a unique correlation ID that flows through:
1. **Backend**: Generated during sale simulation
2. **Queue Message**: Included in event payload
3. **Azure Function**: Extracted and logged
4. **Supplier API**: Received via header and response

This enables complete end-to-end tracing for debugging and monitoring.

---

## Conclusion

The SmartRetail Supplier Sync system demonstrates:

✅ **Event-Driven Architecture** - Decoupled services communicating via events  
✅ **Azure Serverless Computing** - Auto-scaling Functions with consumption pricing  
✅ **Microservices Design** - Independent, focused services  
✅ **Observability** - Correlation ID tracing and structured logging  
✅ **Resilience** - Retry logic and error handling  
✅ **Cloud Integration** - Native Azure services for scalability  

The system is production-ready for demonstration and can be extended with:
- Authentication and authorization
- Database persistence
- Multiple supplier integrations
- Advanced monitoring and alerting
- CI/CD pipelines

---

## Quick Reference

### Service URLs
- **Backend API**: http://4.205.242.245:8000
- **Supplier API**: http://4.205.242.245:8001  
- **Azure Function**: https://tmermerfunctionapp-gnhmbxbkdshpa7gm.canadacentral-01.azurewebsites.net

### Key Demo Commands
```bash
# Health check all services
curl http://4.205.242.245:8000/ && curl http://4.205.242.245:8001/ && curl https://tmermerfunctionapp-gnhmbxbkdshpa7gm.canadacentral-01.azurewebsites.net/api/health

# Trigger event
curl -X POST "http://4.205.242.245:8000/products/prod-001/simulate-sale?quantity=3"

# Check results
curl http://4.205.242.245:8000/queue/status && curl http://4.205.242.245:8001/orders
```

### Azure Portal Links
- **Function App**: Search "tmermerfunctionapp"
- **Storage Account**: Search "tmermerfinalsa"
- **Resource Group**: "Student-RG-1739859"
