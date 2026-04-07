"""
Product relevance filtering service
"""


def is_product_related(text: str, product_name: str = "") -> bool:
    """
    Simple heuristic to determine if a comment is product-related.
    Checks for product name and common tech keywords.
    """
    text_lower = text.lower()
    
    # Check for product name
    if product_name and product_name.lower() in text_lower:
        return True
    
    # Check for common tech keywords
    keywords = ["price", "spec", "battery", "performance", "quality", "feature", 
                "design", "review", "recommend", "issue", "problem", "bug", "error",
                "upgrade", "worth", "value", "camera", "screen", "cpu", "gpu",
                "ram", "storage", "display", "build", "material"]
    
    for keyword in keywords:
        if keyword in text_lower:
            return True
    
    return False
