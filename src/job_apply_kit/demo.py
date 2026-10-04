"""Clearly fictional offline fixtures; demo mode makes no provider requests."""

from __future__ import annotations

import json

import httpx


def postings() -> list[dict]:
    return [
        {
            "demo": True,
            "title": "Example Role Title",
            "company": "Example Company",
            "location": "Remote",
            "url": "https://example.invalid/jobs/demo",
            "salary_amount": 105000,
            "salary_currency": "USD",
            "salary_period": "annual",
            "description": "Requirements: 2+ years of experience. Python required; SQL preferred.",
        }
    ]


def jev_transport() -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        selections = {
            "min_years": "2",
            "clearance_required": "not_required",
            "work_mode": "remote",
            "skill::Python": "required",
            "skill::SQL": "preferred",
        }
        answers = {}
        for name, question in body["questions"].items():
            choice = selections.get(name, "unspecified")
            if choice not in question["criteria"]:
                choice = "not_mentioned"
            answers[name] = {
                "choice": choice,
                "confidence": 1.0,
                "probabilities": {key: int(key == choice) for key in question["criteria"]},
            }
        return httpx.Response(200, json={"answers": answers, "usage": {"input_tokens": 100}})

    return httpx.MockTransport(respond)
