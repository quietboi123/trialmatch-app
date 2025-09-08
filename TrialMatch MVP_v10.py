# -*- coding: utf-8 -*-
"""
TrialMatch Recruiter (v8, preset criteria, hidden JSON, contact form)
- Uses pre-set inclusion/exclusion criteria (no user prompt for criteria).
- Hides the machine JSON from the UI, but still parses & saves it to Supabase.
- When ready for contact info, the chat temporarily swaps to a 3-field form:
    email (text), phone (number-like), consent (checkbox).
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
CONTACT_TOKEN = "[CONTACT_INFO_FORM]"  # sentinel emitted by the model to request the form

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
    3) Remove the contact token if present (token is for UI only)
    """
    t = re.sub(r"```(?:json)?\s*{[\s\S]*?}\s*```", "", text).strip()
    t = re.sub(r"\s*{[\s\S]*}\s*$", "", t).strip()
    t = t.replace(CONTACT_TOKEN, "").strip()
    return t

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

def looks_like_phone(s: str) -> bool:
    """Basic phone validation: allow digits and common symbols, ensure 10-15 digits total."""
    digits = re.sub(r"\D", "", s or "")
    return 10 <= len(digits) <= 15

def normalize_phone(s: str) -> str:
    """Return just digits for consistency; model/DB don't require formatting."""
    return re.sub(r"\D", "", s or "")

def looks_like_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))

# =========================
# 3) STREAMLIT PAGE
# =========================
st.set_page_config(page_title="TrialMatch Recruiter", page_icon="🧪")
st.title("🧪 TrialMatch Recruiter")
st.markdown("Chat with a friendly assistant to quickly pre-screen for clinical trials.")

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []        # full history we send to the model (hide seed)
if "bootstrapped" not in st.session_state:
    st.session_state.bootstrapped = False
if "intake_complete" not in st.session_state:
    st.session_state.intake_complete = False
if "awaiting_contact" not in st.session_state:
    st.session_state.awaiting_contact = False

# =========================
# 4) SYSTEM PROMPT
# =========================
system_prompt = f"""
You are Pre-Screen PA, a clinical trial pre-screening assistant. Your job is to:
1) Parse the provided inclusion/exclusion criteria into structured rules.
2) Immediately act as if you are interviewing a patient with the fewest, most important questions (see rules below).
3) Maximize the chances of the patient answering all of your questions by keeping them engaged and occasionally positively reinforcing them if their answers make them eligible.
4) Decide: Eligible / Likely Eligible / Likely Ineligible / Unknown, with a rationale tied to exact criteria.
5) If a patient is Eligible or Likely Eligible, the UI will collect email, phone, and consent via a form. When you are ready for that step, output exactly this single token on its own line: {CONTACT_TOKEN}
6) After the form is submitted, continue with a human-readable summary and a machine-readable JSON object (see keys below). Do NOT show the JSON until after contact info is provided.

Tone & Boundaries
- Friendly, concise, clinically literate—like a trained PA. Keep the patient engaged.
- Only ask ONE question at a time, like a real conversation.
- Never give medical advice or diagnosis—only assess trial fit from provided criteria.
- Always add the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”

Pre-Screening Efficiency Rule
- Never ask more than 5 questions total.
- Default to 3–5 highest-yield, easiest-to-answer questions.
- Stop early if ineligibility is obvious.

Operating Loop
1) Parse criteria silently.
2) Plan interview silently. Pick top 3–5 questions only.
3) Immediately begin asking questions one at a time.
4) Stop early if exclusion criteria are met.
5) When you reach your final decision and the patient is Eligible/Likely Eligible, output the token {CONTACT_TOKEN} to trigger the form (no extra text needed if you prefer).
6) AFTER the form info is provided by the user, produce:
   - Readable summary (5–10 lines)
   - Decision with rationale referencing specific criteria
   - Next steps / missing info
   - Machine-readable JSON with keys:
     decision, rationale, asked_questions, answers, missing_info, parsed_rules,
     contact_info (email, phone, consent: true/false), final: true

JSON Formatting
- Place the JSON in a single fenced block: ```json {{ ... }} ```
- Do not include any other JSON-looking code blocks.

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
    # Hidden seed "user" message (not rendered)
    st.session_state.messages.append({"role": "user", "content": criteria_md, "hide": True})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
        temperature=0.4,
    )
    first_reply_raw = response.choices[0].message.content.strip()
    # Detect if model already requested contact form (unusual but safe)
    if CONTACT_TOKEN in first_reply_raw:
        st.session_state.awaiting_contact = True
    first_reply_display = strip_machine_json(first_reply_raw)

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
# 7) CONTACT FORM (shown only when the model requests it)
# =========================
def render_contact_form():
    with st.form("contact_form", clear_on_submit=False):
        st.markdown("**Almost done — please share your contact details:**")
        email = st.text_input("Email", placeholder="name@example.com")
        phone = st.text_input("Phone", placeholder="(555) 123-4567 or +1 555 123 4567")
        consent = st.checkbox("I consent to be contacted about this study.")
        submitted = st.form_submit_button("Submit")
        if submitted:
            errors = []
            if not looks_like_email(email):
                errors.append("Please enter a valid email.")
            if not looks_like_phone(phone):
                errors.append("Please enter a valid phone number (10–15 digits).")
            if errors:
                for e in errors:
                    st.error(e)
                return None
            return {
                "email": email.strip(),
                "phone": normalize_phone(phone),
                "consent": bool(consent),
            }
    return None

if st.session_state.awaiting_contact:
    contact = render_contact_form()
    if contact:
        # Inform the model of contact info in a clean, structured user turn
        contact_text = (
            "Here is my contact information from the form:\n"
            f"Email: {contact['email']}\n"
            f"Phone: {contact['phone']}\n"
            f"Consent: {'true' if contact['consent'] else 'false'}"
        )
        st.session_state.messages.append({"role": "user", "content": contact_text})
        st.chat_message("user").markdown("Submitted contact details ✅")

        # Resume model to produce final summary + JSON (JSON remains hidden in UI)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
            temperature=0.4,
        )
        raw_reply = response.choices[0].message.content.strip()

        # Save before stripping (we need the JSON)
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

        display_reply = strip_machine_json(raw_reply)
        st.session_state.messages.append({"role": "assistant", "content": display_reply})
        st.chat_message("assistant").markdown(display_reply)

        # Exit form mode
        st.session_state.awaiting_contact = False

# =========================
# 8) CHAT INPUT (disabled while awaiting contact form)
# =========================
placeholder = "Answer the PA's question here..."
if not st.session_state.awaiting_contact:
    if user_text := st.chat_input(placeholder):
        st.session_state.messages.append({"role": "user", "content": user_text})
        st.chat_message("user").markdown(user_text)

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
            temperature=0.4,
        )
        raw_reply = response.choices[0].message.content.strip()

        # If the model signals the contact form, enter form mode (don't persist yet)
        if CONTACT_TOKEN in raw_reply:
            st.session_state.awaiting_contact = True

        # Persist only on final decision (after contact form step)
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

        display_reply = strip_machine_json(raw_reply)
        st.session_state.messages.append({"role": "assistant", "content": display_reply})
        st.chat_message("assistant").markdown(display_reply)
else:
    st.info("Please complete the contact form above to continue.")
