# -*- coding: utf-8 -*-
"""
Created on Tue Aug  5 20:46:47 2025

@author: Andres Hoffman
"""

# -*- coding: utf-8 -*-
"""
Created on Mon Jul 14 21:53:09 2025

@author: Andres Hoffman
"""

# Importing necessary packages
import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
import os
import json
import re
from datetime import datetime, timezone

# === 1A. OpenAI client from Streamlit secrets ===
client = OpenAI(api_key=st.secrets["openai"]["api_key"])

# === 1B. Supabase client from Streamlit secrets ===
def get_supabase() -> Client:
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["service_key"]
    )

# === 1C. Helpers to extract JSON from model reply & persist results (any decision) ===
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
    Tries to parse the last JSON object the assistant included in its reply.
    Works if the JSON is in a ```json ...``` block or just plain {...}.
    """
    try:
        # Prefer fenced blocks like ```json { ... } ```
        blocks = re.findall(r"```(?:json)?\s*({[\s\S]*?})\s*```", text)
        candidate = blocks[-1] if blocks else re.findall(r"({[\s\S]*})", text)[-1]
        return json.loads(candidate)
    except Exception:
        return None

def persist_result(reply_text: str, session_id: str = None):
    """
    Saves to Supabase on ANY decision (Eligible, Likely Eligible, Likely Ineligible, Unknown).
    Also saves the consent flag exactly as answered (True/False).
    Adds a timestamp at insert time (sets created_at explicitly in UTC).
    """
    sb = get_supabase()
    data = extract_last_json_block(reply_text)

    # Defaults if JSON is missing
    decision = "Unknown"
    rationale = "No JSON payload found."
    answers = None
    parsed_rules = None
    contact = {}
    trial_title = None

    if data:
        decision = _normalize_decision(data.get("decision"))
        rationale = data.get("rationale")
        answers = data.get("answers")
        parsed_rules = data.get("parsed_rules")
        contact = data.get("contact_info") or {}
        trial_title = (parsed_rules or {}).get("trial_title")

    consent_val = _as_bool(contact.get("consent"))
    contact_email = contact.get("email")
    contact_phone = contact.get("phone")

    payload = {
        # explicitly set created_at; table also has a default if omitted
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trial_title": trial_title,
        "decision": decision,                 # always include the decision
        "rationale": rationale,
        "answers": answers,
        "parsed_rules": parsed_rules,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "consent": consent_val,               # always include consent answer (True/False)
        "session_id": session_id,
    }

    try:
        sb.table("prescreen_contacts").insert(payload).execute()
        return True, "Saved."
    except Exception as e:
        return False, f"DB error: {e}"
    
def is_final_decision(reply_text: str) -> bool:
    """
    Returns True only when the assistant has reached a final decision.
    One signal:
      1) The reply contains a JSON block whose top-level key 'final' is True
    """
    data = extract_last_json_block(reply_text)
    if isinstance(data, dict) and data.get("final") is True:
        return True
    return False


# === 2. Page Setup ===
st.set_page_config(page_title="TrialMatch Recruiter", page_icon="🧪")
st.title("🧪 TrialMatch Recruiter")
st.markdown("Chat with a friendly assistant to quickly pre-screen for clinical trials.")

# === 3. Initialize State ===
if "messages" not in st.session_state:
    st.session_state.messages = []
    intro_message = (
        "Hi there! 👋 To get started, please paste the **inclusion and exclusion criteria** "
        "for a clinical trial you're interested in. I’ll parse them and then ask you a few quick questions "
        "to see if you might qualify."
    )
    st.session_state.messages.append({"role": "assistant", "content": intro_message})

if "intake_complete" not in st.session_state:
    st.session_state.intake_complete = False

# === 4. System Prompt for GPT ===
# Replaced with your PA-style TrialMatch prompt
system_prompt = """
You are Pre-Screen PA, a clinical trial pre-screening assistant. Your job is to:
1) Parse free-text inclusion/exclusion criteria into structured rules.
2) Immediately act as if you are interviewing a patient with the fewest, most important questions (see rules below).
3) Maximize the chances of the patient answering all of your questions by keeping them engaged and occasionally positively reinforcing them if their answers make them eligible.
4) Decide: Eligible / Likely Eligible / Likely Ineligible / Unknown, with a rationale tied to exact criteria.
5) If a patient is Eligible or Likely Eligible, prompt them for their email, phone number, and consent to be contacted.
6) Output a clear summary and machine-readable JSON for CRM/CSV export.

Tone & Boundaries
- Friendly, concise, clinically literate—like a trained PA. Keep the patient engaged.
- Only ask ONE question at a time, like a real conversation.
- Never give medical advice or diagnosis—only assess trial fit from provided criteria.
- Always add the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”

Interaction Flow
- The first input from the user will be the inclusion/exclusion criteria.
- Silently parse criteria into structured rules.
- Immediately begin the prescreen interview, speaking directly to the patient, asking one question at a time.
- At the end, if a patient is deemed Eligible, prompt them for their email and phone number and consent to be contacted.
- Always roleplay as a PA conducting a quick eligibility check.

Maximizing Engagement & Completion
- Build rapport quickly: brief welcome + benefit framing (“This only takes a few minutes…”).
- Use micro-commitments: ask easy questions first; acknowledge and positively reinforce where appropriate.
- Encourage and reassure; use light social proof.
- Be supportive, not curt (e.g., “Yes, that makes sense — thank you for confirming.”).
- Frame progress positively (“We’re almost done — just a couple more quick questions.”).
- Emphasize the importance of completion.
- Close with gratitude and affirmation.

Pre-Screening Efficiency Rule
- Never ask more than 5 questions total.
- Default to 3–5 highest-yield, easiest-to-answer questions that most determine eligibility.
- High-yield: absolute requirements (age; confirmed diagnosis; duration/severity) or common disqualifiers (recent MI/stroke, pregnancy).
- Skip nuanced rules (lab values, detailed meds, investigator’s discretion) at this stage — mark Unknown.
- Phrase questions clearly for quick answers (yes/no, single number).
- Stop early if ineligibility is obvious.

Questioning Principles
- Friendly, concise, binary where possible.
- Bundle exclusions safely (e.g., “Any of the following in last 6 months: heart attack, stroke, unstable angina?”).
- Always allow “Don’t know.”

Operating Loop
1) Parse criteria silently.
2) Plan interview silently. Pick top 3–5 questions only.
3) Immediately begin asking questions one at a time in a patient-facing style.
4) Stop early if exclusion criteria are met.
5) When you reach your final eligibiliy decision, if patient is Eligible or Likely Eligible, PROMPT them (not ask) for their email and phone number and consent to be contacted.
6) After questions, produce decision + outputs:
   - Readable summary (5–10 lines)
   - Decision (Eligible / Likely Eligible / Likely Ineligible / Unknown) with rationale referencing specific criteria
   - Next steps / missing info
   - machine-readable JSON object with keys:
  decision, rationale, asked_questions, answers, missing_info, parsed_rules,
  contact_info (with keys: email, phone, consent: true/false),
  and also include: final: true
   - Do NOT output the machine-readable JSON until you have finished questioning and reached a final decision.


Parsing Rules
- Normalize units; convert “within X months” into explicit windows.
- Recognize synonyms (MI = heart attack).
- Flag vague items (e.g., “adequate organ function”) as Unknown.
- Preserve verbatim criteria text.

Decision Logic
- Any exclusion met -> Likely Ineligible.
- All key inclusions met & no major exclusion -> Likely Eligible.
- Minimal/critical data missing -> Unknown.

Always include the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”
"""

# === 5. Display Chat History ===
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).markdown(msg["content"])

# === 6. (Optional) Structured extraction disabled for this PA flow ===
# The previous version extracted a demographic profile after intake completion.
# That no longer applies cleanly to this PA-style prescreen, so we skip it to
# let the PA-style flow and JSON output from the assistant stand as the source of truth.

# === 7. Unified Chat Input Handler ===
if prompt := st.chat_input("Paste criteria first, then answer questions one at a time..."):

    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").markdown(prompt)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
        temperature=0.4
    )
    reply = response.choices[0].message.content.strip()

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").markdown(reply)


    # Save only when the final decision is emitted (guarded by sentinel/JSON 'final': true)
    if is_final_decision(reply):
        st.session_state.intake_complete = True

        ok, msg = persist_result(
            reply_text=reply,
            session_id=st.session_state.get("_session_id")
        )
        if ok:
            st.toast("✅ Saved final decision + consent + answers to Supabase.")
        else:
            st.caption(f"Note: {msg}")
      
