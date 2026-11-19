"""Response of POST /predict (algorithms.md 11).

One item per ingredient; it maps 1:1 onto `Detection` in
backend/app/db/repositories/recognition.py (B-19 does the mapping):
label -> label, confidence -> confidence, grams -> grams (None takes the fallback),
alternatives -> tuple of (label, confidence).
"""

from typing import Annotated

from pydantic import BaseModel, Field

MAX_ALTERNATIVES = 2  # K = 3 candidates: the label plus at most 2 alternatives
# bounds the answer so a crowded photo cannot reach the output token limit
MAX_ITEMS = 20

Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class Alternative(BaseModel):
    label: str
    confidence: Confidence


class Item(BaseModel):
    label: str
    confidence: Confidence
    # the model's estimate of the eaten portion; None when it gave 0 or less
    grams: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None
    alternatives: list[Alternative] = Field(max_length=MAX_ALTERNATIVES)


class ModelInfo(BaseModel):
    name: str  # GEMINI_MODEL
    version: str  # the response's model_version, else the model name


class Prediction(BaseModel):
    model: ModelInfo
    items: list[Item]
