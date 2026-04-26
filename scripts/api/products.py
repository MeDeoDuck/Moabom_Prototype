"""
Product-related API routes
"""
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from scripts.database.queries import query_one, query_all, execute_insert, execute_update

templates = Jinja2Templates(directory="templates")


def register_product_routes(app):
    """Register all product-related routes"""
    
    @app.get("/", response_class=HTMLResponse)
    async def root():
        """Redirect to products page."""
        return "<script>window.location.href='/products'</script>"
    
    @app.get("/products", response_class=HTMLResponse)
    async def list_products(request: Request):
        """List all products."""
        products = query_all("SELECT * FROM tech_products ORDER BY created_at DESC")
        return templates.TemplateResponse("products.html", {
            "request": request,
            "products": products,
        })
    
    @app.post("/products")
    async def create_product(data: dict):
        """Create a new product."""
        name = data.get("name", "").strip()
        brand = data.get("brand", "").strip() or None
        category = data.get("category", "").strip() or None
        
        if not name:
            raise HTTPException(status_code=400, detail="Product name is required")
        
        product_id = execute_insert(
            "INSERT INTO tech_products (name, brand, category) VALUES (%s, %s, %s) RETURNING product_id",
            (name, brand, category)
        )
        
        product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
        return product
    
    @app.get("/products/{product_id}", response_class=HTMLResponse)
    async def product_detail(request: Request, product_id: int):
        """Show product detail page with videos."""
        product = query_one("SELECT * FROM tech_products WHERE product_id = %s", (product_id,))
        
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        videos = query_all(
            "SELECT * FROM videos WHERE product_id = %s ORDER BY view_count DESC",
            (product_id,)
        )
        
        return templates.TemplateResponse("product_detail.html", {
            "request": request,
            "product": product,
            "videos": videos,
        })

    @app.delete("/products/{product_id}")
    async def delete_product(product_id: int):
        """Delete a product. CASCADE removes related videos, comments, transcripts, reports."""
        affected = execute_update(
            "DELETE FROM tech_products WHERE product_id = %s",
            (product_id,)
        )
        if affected == 0:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"deleted": True, "product_id": product_id}
