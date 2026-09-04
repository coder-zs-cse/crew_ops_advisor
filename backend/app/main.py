"""FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.deps import get_advisor, get_world
from .api.routes import chat, evaluation, observability, ops, simulate, world as world_routes
from .config import get_settings
from .db.session import init_db
from .jobs import scheduler
from .obs.sinks import EVENT_BUS, MEMORY_SINK, DatabaseSink
from .obs.tracer import TRACER

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("crewops")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Tracing sinks: memory + live bus always; database when persistence is on.
    TRACER.add_sink(MEMORY_SINK)
    TRACER.add_sink(EVENT_BUS)

    init_db()
    if settings.persist_traces:
        from .db.session import get_session_factory

        TRACER.add_sink(DatabaseSink(get_session_factory()))

    world = get_world()
    advisor = get_advisor()
    log.info(
        "world loaded: seed=%s dir=%s | %d flights, %d crew, %d pairings | agent engine=%s",
        settings.data_seed,
        settings.data_dir,
        len(world.flights),
        len(world.crew),
        len(world.pairings),
        advisor.engine,
    )

    # Populate the alert board immediately so the console is never blank on
    # first load, then hand over to the scheduler.
    try:
        scheduler.sweep_alerts()
    except Exception as exc:  # noqa: BLE001
        log.warning("initial alert sweep failed: %s", exc)
    scheduler.start()

    yield

    scheduler.stop()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
    description=(
        "Conversational Crew Control advisor. The language model classifies questions "
        "and writes explanations; a deterministic rules engine computes every number, "
        "verdict, cost and ranking. Narration is verified against the run's fact ledger "
        "before it is returned."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (chat, world_routes, simulate, observability, evaluation, ops):
    app.include_router(module.router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "docs": "/docs",
        "boundary": (
            "LLM: intent + entity proposal + narration. "
            "Code: all arithmetic, legality, cost and ranking. "
            "Narration is verified against the fact ledger before return."
        ),
        "key_endpoints": {
            "chat": "POST /api/chat",
            "chat_stream": "POST /api/chat/stream (SSE)",
            "recommend": "POST /api/recommend/cover",
            "simulate": "POST /api/simulate/{sick,station-closure,delay,cert-lapse,cancellation,chain}",
            "trace": "GET /api/runs/{run_id}",
            "receipt": "GET /api/runs/{run_id}/receipt",
            "eval": "POST /api/eval/run?suite=all",
            "alerts": "GET /api/alerts",
            "health": "GET /api/health",
        },
    }
