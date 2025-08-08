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