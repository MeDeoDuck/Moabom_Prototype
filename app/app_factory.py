from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import Settings
from app.database import Database
from app.repositories import ProductRepository, VideoRepository
from app.schemas import (
    ProductCreateRequest,
    ProductResponse,
    SyncVideosRequest,
    VideoResponse,
)
from app.services import ProductVideoService, YouTubeClient
from app.templates import TemplateProvider


class ApplicationContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings)
        self.product_repository = ProductRepository(self.database)
        self.video_repository = VideoRepository(self.database)
        self.youtube_client = YouTubeClient(settings)
        self.service = ProductVideoService(
            product_repository=self.product_repository,
            video_repository=self.video_repository,
            youtube_client=self.youtube_client,
        )
        self.templates = TemplateProvider(settings).renderer()


def create_app() -> FastAPI:
    settings = Settings.from_env()
    container = ApplicationContainer(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        container.database.initialize()
        yield

    app = FastAPI(title="Tech Product Video Demo", lifespan=lifespan)
    app.state.container = container

    @app.get("/")
    def root() -> JSONResponse:
        return JSONResponse({"message": "Open /products to use the demo."})

    @app.post("/products", response_model=ProductResponse)
    def create_product(payload: ProductCreateRequest) -> ProductResponse:
        product = container.service.create_product(name=payload.name, brand=payload.brand)
        return ProductResponse(**product.__dict__)

    @app.post("/products/{product_id}/sync", response_model=list[VideoResponse])
    def sync_product_videos(
        product_id: int,
        payload: SyncVideosRequest = Body(default_factory=SyncVideosRequest),
    ) -> list[VideoResponse]:
        videos = container.service.sync_product_videos(product_id=product_id, max_results=payload.max_results)
        return [VideoResponse(**video.__dict__) for video in videos]

    @app.get("/products", response_class=HTMLResponse)
    def list_products(request: Request):
        products = container.service.list_products()
        return container.templates.TemplateResponse(
            request,
            "products.html",
            {"products": products},
        )

    @app.get("/products/{product_id}", response_class=HTMLResponse)
    def product_detail(product_id: int, request: Request):
        product = container.service.get_product(product_id)
        videos = container.service.list_product_videos(product_id)
        return container.templates.TemplateResponse(
            request,
            "product_detail.html",
            {"product": product, "videos": videos},
        )

    return app