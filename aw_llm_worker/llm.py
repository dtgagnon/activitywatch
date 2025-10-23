"""
LLM classification via Ollama (local) or OpenAI API.

Implements the LLM contract from goal.md with strict JSON output.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

import requests

from aw_llm_worker.config import Config
from aw_llm_worker.models import Category, CategoryResult, EnrichedFeatures

logger = logging.getLogger(__name__)


# System prompt defining the classification contract
SYSTEM_PROMPT = """You are a deterministic classifier. Output strict JSON only. No prose. Labels:
Top: ["Client Work","Hobby","Entertainment","Uncategorized"]
Sub:
- Client Work: ["STS Contract","Qualira (AWP)","Xodus Medical","Hand Consultants","DTG Engineering","Docs & Spreadsheets","Code & IDE","Comms","Admin & Billing"]
- Hobby: ["Programming","Machining & CAD","Video-Learning","Comms"]
- Entertainment: ["Gaming","Video","Social"]
Rules:
1) Any client indicator → Client Work with that client.
2) Prefer Hobby over Entertainment when educational/DIY terms are present.
3) Video domains without educational terms → Entertainment/Video.
4) Tie-break priority: Client Work > Hobby > Entertainment.
Return: {category, subcategory, client|null, confidence, rationale<=140}"""


def build_user_prompt(features: EnrichedFeatures, config: Config) -> str:
    """
    Build user prompt with redacted features and hints.

    Args:
        features: Redacted enriched features
        config: Configuration with hints

    Returns:
        JSON string for LLM
    """
    # Extract hints from config
    client_domains = {
        name: cfg.get("domains", [])
        for name, cfg in config.clients.items()
    }
    client_keywords = {
        name: cfg.get("keywords", [])
        for name, cfg in config.clients.items()
    }

    prompt_data = {
        "app": features.app,
        "domain": features.domain,
        "title": features.title,
        "path_root": features.path_root,
        "hints": {
            "client_domains": client_domains,
            "client_keywords": client_keywords,
            "edu_keywords": config.rules.get("edu_keywords", []),
            "hobby_prog_keywords": config.rules.get("hobby_prog_keywords", []),
        },
    }

    return json.dumps(prompt_data)


def call_ollama(
    user_prompt: str,
    system_prompt: str,
    config_llm: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Call Ollama API for classification.

    Args:
        user_prompt: User message content
        system_prompt: System message content
        config_llm: LLM configuration

    Returns:
        Parsed JSON response or None on error
    """
    host = config_llm.get("host", "http://localhost:11434")
    model = config_llm.get("model", "llama3")
    temperature = config_llm.get("temperature", 0.0)
    max_tokens = config_llm.get("max_tokens", 256)
    timeout = config_llm.get("timeout", 30)

    try:
        response = requests.post(
            f"{host}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
                "stream": False,
                "format": "json",  # Request JSON output
            },
            timeout=timeout,
        )
        response.raise_for_status()

        result = response.json()
        message_content = result.get("message", {}).get("content", "")

        # Parse JSON from response
        try:
            return json.loads(message_content)
        except json.JSONDecodeError as e:
            logger.error(f"Ollama returned non-JSON: {message_content}")
            return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error calling Ollama: {e}")
        return None


def call_openai(
    user_prompt: str,
    system_prompt: str,
    config_llm: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Call OpenAI API for classification.

    Args:
        user_prompt: User message content
        system_prompt: System message content
        config_llm: LLM configuration

    Returns:
        Parsed JSON response or None on error
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package not installed")
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable not set")
        return None

    model = config_llm.get("model", "gpt-4o-mini")
    temperature = config_llm.get("temperature", 0.0)
    max_tokens = config_llm.get("max_tokens", 256)
    timeout = config_llm.get("timeout", 30)

    try:
        client = OpenAI(api_key=api_key, timeout=timeout)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        message_content = response.choices[0].message.content
        if not message_content:
            logger.error("OpenAI returned empty response")
            return None

        # Parse JSON from response
        try:
            return json.loads(message_content)
        except json.JSONDecodeError as e:
            logger.error(f"OpenAI returned non-JSON: {message_content}")
            return None

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return None


def validate_llm_response(response: Dict[str, Any]) -> bool:
    """
    Validate LLM response has required fields.

    Args:
        response: Parsed JSON response

    Returns:
        True if valid, False otherwise
    """
    required = ["category", "confidence"]
    return all(field in response for field in required)


def parse_llm_response(response: Dict[str, Any]) -> CategoryResult:
    """
    Parse and validate LLM JSON response into CategoryResult.

    Args:
        response: Parsed JSON from LLM

    Returns:
        CategoryResult

    Raises:
        ValueError: If response is invalid
    """
    if not validate_llm_response(response):
        raise ValueError(f"Invalid LLM response: missing required fields")

    # Parse category
    category_str = response.get("category", "Uncategorized")
    try:
        category = Category(category_str)
    except ValueError:
        logger.warning(f"Invalid category '{category_str}', using Uncategorized")
        category = Category.UNCATEGORIZED

    # Extract other fields
    subcategory = response.get("subcategory")
    client = response.get("client")
    confidence = float(response.get("confidence", 0.0))
    rationale = response.get("rationale", "")

    # Validate confidence range
    if not (0.0 <= confidence <= 1.0):
        logger.warning(f"Confidence {confidence} out of range, clamping")
        confidence = max(0.0, min(1.0, confidence))

    # Truncate rationale
    if len(rationale) > 140:
        rationale = rationale[:137] + "..."

    return CategoryResult(
        category=category,
        subcategory=subcategory,
        client=client,
        confidence=confidence,
        source="llm",
        rationale=rationale,
    )


def classify_with_llm(
    features: EnrichedFeatures,
    config: Config,
) -> Optional[CategoryResult]:
    """
    Classify event using LLM (Ollama or OpenAI).

    Args:
        features: Redacted enriched features
        config: Configuration

    Returns:
        CategoryResult if successful, None on error
    """
    provider = config.llm_provider
    config_llm = config.llm_config

    # Build prompts
    user_prompt = build_user_prompt(features, config)
    system_prompt = SYSTEM_PROMPT

    logger.debug(f"Calling {provider} LLM for classification")

    # Call appropriate provider
    if provider == "ollama":
        response = call_ollama(user_prompt, system_prompt, config_llm)
    elif provider == "openai":
        response = call_openai(user_prompt, system_prompt, config_llm)
    else:
        logger.error(f"Unknown LLM provider: {provider}")
        return None

    if response is None:
        logger.error("LLM call failed")
        return None

    # Parse response
    try:
        result = parse_llm_response(response)
        logger.info(
            f"LLM classified as {result.category.value}/{result.subcategory} "
            f"(confidence={result.confidence:.2f})"
        )
        return result
    except (ValueError, KeyError) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return None
