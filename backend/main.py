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