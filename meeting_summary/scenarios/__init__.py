"""Scenario registry for AVIA modular demos.
Add new scenario modules here and register them in SCENARIOS dict.
"""
from typing import Dict, Callable
import streamlit as st

# Type alias for scenario render function
ScenarioFn = Callable[[], None]

SCENARIOS: Dict[str, Dict[str, object]] = {}


def register_scenario(key: str, title: str, description: str, keywords: str):
    def decorator(func: ScenarioFn):
        SCENARIOS[key] = {
            "title": title,
            "description": description,
            "keywords": keywords,
            "render": func,
        }
        return func
    return decorator


def list_scenarios():
    return SCENARIOS
