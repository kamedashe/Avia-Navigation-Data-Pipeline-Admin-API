# main.py
import logging
from fastapi import FastAPI
from app.routers import (
    a_router,
    admin_router,
    b_router,
    changes_router,
    f_router,
    d_router,
    maps_router,
    t_router,
    c_router,
    e_router,
    g_router,
    n_router,
    r_router,
)


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logging.info("Starting Avia Navigation API")


app = FastAPI(
    title="Avia Navigation API",
    version="1.0",
    description="This is a very fast backend for Avia Navigation",
)

# Include routers
app.include_router(a_router.router)
app.include_router(admin_router.router)
app.include_router(changes_router.router)
app.include_router(b_router.router)
app.include_router(f_router.router)
app.include_router(d_router.router)
app.include_router(t_router.router)
app.include_router(c_router.router)
app.include_router(e_router.router)
app.include_router(g_router.router)
app.include_router(n_router.router)
app.include_router(r_router.router)
app.include_router(maps_router.router)


@app.get("/")
def read_root():
    """Test endpoint"""
    return {"Privet": "Mir"}
