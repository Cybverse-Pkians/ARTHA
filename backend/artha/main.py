"""ARTHA decision service.

A stateless FastAPI application in front of the orchestrator (report §8:
"Backend API — FastAPI (Python), stateless decision service"). It is a transport
layer and nothing more: every behaviour that affects a lending outcome lives in
:mod:`artha.orchestrator` and the engines beneath it.

Deployment note (report §8.1, §9.2): this runs inside the bank's own virtual
private cloud or data centre. It consumes transactions through change-data-
capture and writes back only decisions and audit records — no modification to
core banking is required.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import audit, banker, catalogue, decisions, journey
from .config import settings

DESCRIPTION = """
A suitability-first lending intelligence layer.

**Every bank can decide whether to lend. ARTHA decides how much, when,
structured how — and when to stay silent.**

All figures returned by this service are *illustrative*, generated from the
synthetic transaction generator described in report §11.1. No integration with a
live bank, Account Aggregator or credit bureau has been performed, and nothing
here is a measured portfolio result.
"""

app = FastAPI(
    title="ARTHA",
    version="0.1.0",
    description=DESCRIPTION,
    contact={"name": "Team Wowwsters"},
)

# The console and customer app are served separately in development. A bank
# deployment fronts both from the same origin and this list is narrowed to it.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:8787"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(decisions.router)
app.include_router(journey.router)
app.include_router(banker.router)
app.include_router(audit.router)
app.include_router(catalogue.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "artha",
        "version": "0.1.0",
        "env": settings.env,
        "language_provider": settings.language_provider,
        "stage": "concept and wireframe — all figures illustrative (report §11)",
    }


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": "ARTHA",
        "tagline": (
            "We do not maximise how much a customer borrows. "
            "We maximise the probability that they keep paying."
        ),
        "docs": "/docs",
        "surfaces": {
            "customer": "/journey/*",
            "banker": "/banker/*",
            "audit": "/audit/*",
        },
    }
