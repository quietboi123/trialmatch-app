# -*- coding: utf-8 -*-
"""
TrialMatch Recruiter (v8, preset criteria, hidden JSON, contact FORM-as-CARD)
- Pre-set inclusion/exclusion criteria (no user paste)
- Hides machine JSON from the UI, still saves to Supabase
- Switches to a 3-field form (email, phone, consent) when contact info is needed
- After submit, shows a read-only "form card" in history (NOT a user bubble),
  sends contact to the model via a hidden turn, and continues to the closing message.
"""

import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
import json
import re
from datetime import datetime, timezone

# =========================
# 0) CONFIG: PRESET CRITERIA
# =========================
USE_PRESET_CRITERIA = True
CONTACT_TOKEN = "[CONTACT_INFO_FORM]"  # sentinel the model outputs to trigger the form

PRESET_CRITERIA = {
    "title": "MDD / TRD Outpatient Study (Example)",
    "inclusion": [
        "Participant is ≥ 18 years old",
        "Primary diagnosis of recurrent MDD (moderate or severe) OR persistent depressive disorder",
        "Inadequate response to oral antidepressants in the current episode",
        "On a stable oral antidepressant regimen for ≥ 8 weeks prior to screening",
        "Willing and able to comply with all study procedures and restrictions"
    ],
    "exclusion": [
        "Primary focus of treatment in the last 12 months is a psychiatric disorder other than MDD",
        "Considered by the investigator to be at imminent risk of suicide or self-harm"
    ],
}

def criteria_to_markdown(criteria: dict) -> str:
    inc = "\n".join(f"* {item}" for item in criteria.get("inclusion", []))
    exc = "\n".join(f"* {item}" for item in criteria.get("exclusion", []))
    title = criteria.get("title", "Trial Criteria")
    return (
        f"**{title}**\n\n"
        f"**Key Inclusion Criteria:**\n{inc}\n\n"
        f"**Key Exclusion Criteria:**\n{exc}"
    )

# =========================
# 1) CLIENTS
# =========================
client = OpenAI(api_key=st.secrets["openai"]["api_key"])

def get_supabase() -> Client:
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["service_key"]
    )

# =========================
# 2) HELPERS
# =========================
def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "y", "true", "t", "1", "consent", "agree", "agreed"}
    return False

def _normalize_decision(s: str) -> str:
    s = (s or "").strip().lower()
    if "likely ineligible" in s or "ineligible" in s:
        return "Likely Ineligible"
    if "likely eligible" in s:
        return "Likely Eligible"
    if s == "eligible" or ("eligible" in s and "likely" not in s and "ineligible" not in s):
        return "Eligible"
    if "unknown" in s:
        return "Unknown"
    return "Unknown"

def extract_last_json_block(text: str):
    """Parse the last JSON object from assistant reply."""
    try:
        blocks = re.findall(r"```(?:json)?\s*({[\s\S]*?})\s*```", text)
        candidate = blocks[-1] if blocks else re.findall(r"({[\s\S]*})", text)[-1]
        return json.loads(candidate)
    except Exception:
        return None

def strip_machine_json(text: str) -> str:
    """Hide machine JSON & the contact token from user-visible content."""
    t = re.sub(r"```(?:json)?\s*{[\s\S]*?}\s*```", "", text).strip()
    t = re.sub(r"\s*{[\s\S]*}\s*$", "", t).strip()
    t = t.replace(CONTACT_TOKEN, "").strip()
    return t

def persist_result(reply_text: str, session_id: str = None):
    """
    Saves to Supabase on ANY decision.
    Fields: created_at, trial_title, decision, rationale, asked_questions, answers,
            parsed_rules, contact_email, contact_phone, consent, session_id
    """
    sb = get_supabase()
    data = extract_last_json_block(reply_text)

    decision = "Unknown"
    rationale = "No JSON payload found."
    answers = None
    parsed_rules = None
    contact = {}
    trial_title = None
    questions = None

    if data:
        decision = _normalize_decision(data.get("decision"))
        rationale = data.get("rationale")
        answers = data.get("answers")
        parsed_rules = data.get("parsed_rules")
        contact = data.get("contact_info") or {}
        trial_title = (parsed_rules or {}).get("trial_title")
        questions = data.get("asked_questions")

    consent_val = _as_bool(contact.get("consent"))
    contact_email = contact.get("email")
    contact_phone = contact.get("phone")

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trial_title": trial_title,
        "decision": decision,
        "rationale": rationale,
        "asked_questions": questions,
        "answers": answers,
        "parsed_rules": parsed_rules,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "consent": consent_val,
        "session_id": session_id,
    }

    try:
        sb.table("prescreen_contacts").insert(payload).execute()
        return True, "Saved."
    except Exception as e:
        return False, f"DB error: {e}"

def is_final_decision(reply_text: str) -> bool:
    data = extract_last_json_block(reply_text)
    return bool(isinstance(data, dict) and data.get("final") is True)

def looks_like_phone(s: str) -> bool:
    """Basic phone validation: allow digits and common symbols, ensure 10–15 digits total."""
    digits = re.sub(r"\D", "", s or "")
    return 10 <= len(digits) <= 15

def normalize_phone(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def looks_like_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))

def should_trigger_contact_form(text: str) -> bool:
    """Robust trigger: token OR common phrasing asking for email/phone/consent."""
    if CONTACT_TOKEN in (text or ""):
        return True
    if re.search(r"\b(email|e-mail)\b", text or "", re.I) and re.search(r"\b(phone|number)\b", text or "", re.I):
        return
