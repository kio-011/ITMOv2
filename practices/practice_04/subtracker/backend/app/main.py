from fastapi import FastAPI

from app.routers import stats

app = FastAPI(title="subtracker")
app.include_router(stats.router)
