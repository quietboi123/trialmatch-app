# -*- coding: utf-8 -*-
"""
TrialMatch Recruiter (v8, preset criteria, hidden JSON)
- Uses pre-set inclusion/exclusion criteria (no user prompt for criteria).
- Persists the model's final JSON to Supabase, but strips/hides JSON from the chat UI.
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
USE_PRESET_CRITERIA = True  # keep True to avoid prompting for criteria

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
    """
    Parse the last JSON object from assistant reply.
    Supports ```json ...``` fenced or raw {...}.
    """
    try:
        blocks = re.findall(r"```(?:json)?\s*({[\s\S]*?})\s*```", text)
        candidate = blocks[-1] if blocks else re.findall(r"({[\s\S]*})", text)[-1]
        return json.loads(candidate)
    except Exception:
        return None

def strip_machine_json(text: str) -> str:
    """
    Remove any machine JSON from an assistant reply so users never see it.
    1) Remove fenced ```json { ... }``` (or ``` { ... } ```)
    2) Remove a trailing standalone {...} block if present
    """
    without_fenced = re.sub(r"```(?:json)?\s*{[\s\S]*?}\s*```", "", text).strip()
    # If there's a raw JSON object at the very end, drop it
    without_trailing = re.sub(r"\s*{[\s\S]*}\s*$", "", without_fenced).strip()
    return without_trailing

def persist_result(reply_text: str, session_id: str = None):
    """
    Saves to Supabase on ANY decision. (Keeps same schema/behavior.)
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

# =========================
# 3) STREAMLIT PAGE
# =========================
st.set_page_config(page_title="TrialMatch Recruiter", page_icon="🧪")
st.title("🧪 TrialMatch Recruiter")
st.markdown("Chat with a friendly assistant to quickly pre-screen for clinical trials.")

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []        # history to send to model (no machine JSON needed in history)
if "bootstrapped" not in st.session_state:
    st.session_state.bootstrapped = False
if "intake_complete" not in st.session_state:
    st.session_state.intake_complete = False

# =========================
# 4) SYSTEM PROMPT
# =========================
system_prompt = """
You are Pre-Screen PA, a clinical trial pre-screening assistant. Your job is to:
1) Parse the provided inclusion/exclusion criteria into structured rules.
2) Immediately act as if you are interviewing a patient with the fewest, most important questions (see rules below).
3) Maximize the chances of the patient answering all of your questions by keeping them engaged and occasionally positively reinforcing them if their answers make them eligible.
4) Decide: Eligible / Likely Eligible / Likely Ineligible / Unknown, with a rationale tied to exact criteria.
5) If a patient is Eligible or Likely Eligible, prompt them for their email, phone number, and consent to be contacted BEFORE outputting a summary and JSON.
6) Output a clear summary and machine-readable JSON for CRM/CSV export.

Tone & Boundaries
- Friendly, concise, clinically literate—like a trained PA. Keep the patient engaged.
- Only ask ONE question at a time, like a real conversation.
- Never give medical advice or diagnosis—only assess trial fit from provided criteria.
- Always add the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”

Interaction Flow
- The app has already supplied the trial criteria as the FIRST user message (do NOT ask the patient to provide criteria).
- Silently parse criteria into structured rules.
- Immediately begin the prescreen interview, speaking directly to the patient, asking one question at a time.
- At the end, if the patient is Eligible or Likely Eligible, PROMPT them for email, phone, and consent. Only after that, generate the summary and JSON.
- Always roleplay as a PA conducting a quick eligibility check.

Pre-Screening Efficiency Rule
- Never ask more than 5 questions total.
- Default to 3–5 highest-yield, easiest-to-answer questions.
- Stop early if ineligibility is obvious.

Operating Loop
1) Parse criteria silently.
2) Plan interview silently. Pick top 3–5 questions only.
3) Immediately begin asking questions one at a time.
4) Stop early if exclusion criteria are met.
5) When you reach your final eligibility decision, if Eligible/Likely Eligible, PROMPT for contact info & consent.
6) AFTER the patient provides contact info & consent, produce:
   - Readable summary (5–10 lines)
   - Decision with rationale referencing specific criteria
   - Next steps / missing info
   - Machine-readable JSON with keys:
     decision, rationale, asked_questions, answers, missing_info, parsed_rules,
     contact_info (email, phone, consent: true/false), final: true

IMPORTANT (UI hygiene)
- Put the machine-readable JSON in a single fenced JSON block (```json ... ```).
- Do not include any other code blocks that look like JSON.
- The human-facing text should be complete WITHOUT the JSON (summary + next steps + disclaimer).
- The JSON is for backend use; the patient should not need to see it.

Parsing Rules
- Normalize units; convert time windows explicitly.
- Recognize synonyms (MI = heart attack).
- Flag vague items as Unknown.
- Preserve verbatim criteria text.

Decision Logic
- Any exclusion met -> Likely Ineligible.
- All key inclusions met & no major exclusion -> Likely Eligible.
- Minimal/critical data missing -> Unknown.

Always include the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”
"""

# =========================
# 5) FIRST-RUN BOOTSTRAP: seed criteria & get first assistant turn
# =========================
if USE_PRESET_CRITERIA and not st.session_state.bootstrapped:
    criteria_md = criteria_to_markdown(PRESET_CRITERIA)
    # Store as a hidden "user" message in history; not rendered directly
    st.session_state.messages.append({"role": "user", "content": criteria_md, "hide": True})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
        temperature=0.4,
    )
    first_reply_raw = response.choices[0].message.content.strip()
    first_reply_display = strip_machine_json(first_reply_raw)

    # We only store/display the stripped version in chat history shown to the user
    st.session_state.messages.append({"role": "assistant", "content": first_reply_display})
    st.session_state.bootstrapped = True

# =========================
# 6) DISPLAY CHAT HISTORY (skip hidden seed)
# =========================
for msg in st.session_state.messages:
    if msg.get("hide"):
        continue
    st.chat_message(msg["role"]).markdown(msg["content"])

# =========================
# 7) CHAT INPUT (no criteria prompt needed)
# =========================
placeholder = "Answer the PA's question here..."
if user_text := st.chat_input(placeholder):
    st.session_state.messages.append({"role": "user", "content": user_text})
    st.chat_message("user").markdown(user_text)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
        temperature=0.4,
    )
    raw_reply = response.choices[0].message.content.strip()

    # Persist decision & consent if final, BEFORE stripping for display
    if is_final_decision(raw_reply):
        st.session_state.intake_complete = True
        ok, msg = persist_result(
            reply_text=raw_reply,
            session_id=st.session_state.get("_session_id")
        )
        if ok:
            st.toast("✅ Saved final decision + consent + answers to Supabase.")
        else:
            st.caption(f"Note: {msg}")

    # Always strip machine JSON before showing to the user
    display_reply = strip_machine_json(raw_reply)

    # Append/display stripped assistant message
    st.session_state.messages.append({"role": "assistant", "content": display_reply})
    st.chat_message("assistant").markdown(display_reply)
